"""Ad JPGs ETL — discover new ad images in the Design CO/UT/TX folders on
SharePoint, upload them to Supabase Storage, register metadata rows in
client_ads. INSERT-only — never overwrites existing rows so any vision
extraction data already in the table is safe.

Three-phase pipeline:
  1. Discovery (cheap): list immediate subfolders of each market's JPG root,
     compare each subfolder's lastModifiedDateTime against the most recent
     successful run. Skip subfolders unchanged since then.
  2. Diff: enumerate files inside the changed subfolders, compute the
     storage_path each would have, query client_ads to find which paths are
     already registered, return the new-file set.
  3. Process: for each new file — download from SharePoint, upload to the
     'client_ads' bucket, parse filename for client/zone/size, INSERT.

Common case (biweekly): no subfolders modified since last run -> exit ~5 sec
with a clean "nothing to do" audit row.

Usage:
  python etl/etl_ad_jpgs.py --dry-run                  # discovery+diff, no writes
  python etl/etl_ad_jpgs.py --dry-run --limit 5         # cap to first 5 new files
  python etl/etl_ad_jpgs.py                             # full run
  python etl/etl_ad_jpgs.py --markets CO                # one market only
  python etl/etl_ad_jpgs.py --since 2026-01-01          # ignore stored history
"""

import os
import re
import sys
import socket
import argparse
import traceback
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

from etl.sharepoint_client import (
    SharePointClient,
    SharePointAuthError,
    SharePointAPIError,
)
import ad_load_to_supabase as adloader  # legacy matcher/index helpers in scripts/

# parse_filename is inlined below rather than imported from scripts/ad_vision_batch
# because that module imports `anthropic` at top level (for the vision pipeline)
# which we do not need here and which isn't in requirements.txt. Keeping this
# function inline avoids dragging that dependency into the JPG ETL.

def parse_filename(filename: str) -> dict:
    """Parse {Client}-THM{MK}-{Size}-{Zone}-{Issue}.jpg variants.

    MK = CO/UT/TX/SA/AU market prefix.
    Zone can contain & for combined zones (e.g. AUN&S, SAE&W).
    Size can be 1-3 chars (F, Fb, BC, BCB, etc.).

    Returns dict with keys: client_raw, market, size_code, zone_code, issue_code.
    Any field that can't be parsed is set to None.
    """
    base = Path(filename).stem
    # Primary pattern
    m = re.match(
        r"^(.+?)-THM([A-Z]{2})-([A-Za-z]+)[-\s]+([A-Z&]+)(?:-[A-Za-z0-9]+)?-(\d{4}s?)$",
        base,
    )
    if m:
        return {"client_raw": m.group(1), "market": m.group(2), "size_code": m.group(3),
                "zone_code": m.group(4), "issue_code": m.group(5)}
    # Fallback: size missing entirely (seen in TX)
    m = re.match(r"^(.+?)-THM([A-Z]{2})-([A-Z&]+)-(\d{4}s?)$", base)
    if m:
        return {"client_raw": m.group(1), "market": m.group(2), "size_code": None,
                "zone_code": m.group(3), "issue_code": m.group(4)}
    return {"client_raw": base, "market": None, "size_code": None,
            "zone_code": None, "issue_code": None}

ETL_NAME = "ad_jpgs"
SP_SITE_URL = "https://thehomemagwest.sharepoint.com/sites/Sales"
SP_LIBRARY_NAME = "Sales (Corner)"
BUCKET = "client_ads"
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}  # PDFs intentionally excluded

# (market_code, sp_root_path) — subtree inside the Sales (Corner) library.
JPG_TARGETS = [
    ("CO", "Design CO/THM Colorado Ad JPGs"),
    ("UT", "Design UT/THM Utah Ad JPGs"),
    ("TX", "Design TX/THM Texas Ad JPGs"),
]


def storage_path_from_sp(sp_path: str, market_root: str) -> str:
    """Strip the SP market-root prefix so storage_path matches the
    legacy scheme: 'THM Colorado YYYY-MM/Filename.jpg'."""
    if sp_path.startswith(market_root + "/"):
        return sp_path[len(market_root) + 1:]
    return sp_path


def storage_path_to_source_folder(storage_path: str) -> str:
    """First path segment — used for the source_folder column."""
    parts = storage_path.split("/")
    return parts[0] if parts else ""


_YEAR_RE = re.compile(r"\b(20\d{2})\b")

def folder_year(name: str) -> int | None:
    """Extract leading 4-digit year from a folder name. Returns None if
    no year is present (which is unusual but possible — those folders are
    always included since we can't categorize them).
    """
    m = _YEAR_RE.search(name)
    return int(m.group(1)) if m else None


# ---------- audit ----------

def _audit_client():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def audit_start(sb, dry_run: bool, source: str = "sharepoint") -> str | None:
    if sb is None:
        return None
    try:
        row = {
            "etl_name": ETL_NAME,
            "source": source,
            "dry_run": dry_run,
            "host": socket.gethostname(),
            "github_run_id": os.getenv("GITHUB_RUN_ID"),
            "github_run_url": (
                f"{os.getenv('GITHUB_SERVER_URL', '')}/"
                f"{os.getenv('GITHUB_REPOSITORY', '')}/actions/runs/"
                f"{os.getenv('GITHUB_RUN_ID', '')}"
                if os.getenv("GITHUB_RUN_ID") else None
            ),
        }
        result = sb.table("etl_runs").insert(row).execute()
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        print(f"  WARNING: audit start failed: {type(e).__name__}: {e}")
        return None


def audit_finish(sb, run_id, *, success, counts=None, notes=None,
                 error_stage=None, error_message=None):
    if sb is None or run_id is None:
        return
    try:
        update = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "error_stage": error_stage,
            "error_message": error_message,
        }
        if counts:
            update["rows_read"] = counts.get("files_scanned")
            update["rows_upserted_campaigns"] = counts.get("rows_inserted")
            update["unmatched_clients"] = counts.get("rows_unmatched_client")
        if notes is not None:
            update["notes"] = notes
        sb.table("etl_runs").update(update).eq("id", run_id).execute()
    except Exception as e:
        print(f"  WARNING: audit finish failed: {type(e).__name__}: {e}")


def get_last_successful_run_finish(sb) -> datetime | None:
    if sb is None:
        return None
    try:
        result = (
            sb.table("etl_runs")
            .select("finished_at")
            .eq("etl_name", ETL_NAME)
            .eq("success", True)
            .eq("dry_run", False)
            .order("finished_at", desc=True)
            .limit(1)
            .execute()
        )
        if result.data and result.data[0]["finished_at"]:
            ts = result.data[0]["finished_at"].replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
    except Exception as e:
        print(f"  WARNING: last-finish lookup failed: {type(e).__name__}: {e}")
    return None


# ---------- email failure ----------

def email_failure(subject: str, html_body: str) -> None:
    try:
        from scripts.import_report import send_email
        send_email(subject, html_body)
    except Exception as e:
        print(f"  WARNING: failed to send failure email: {type(e).__name__}: {e}")


# ---------- discovery / diff helpers ----------

def list_files_recursive(sp: SharePointClient, site_id: str, drive_id: str,
                          folder_path: str, year_min: int | None = None) -> list[dict]:
    """Recursively enumerate all image-extension files under folder_path.
    Each return entry: {sp_path, name, size, modified_at, item_id}.

    If year_min is given, nested subfolders whose names contain a year
    earlier than year_min are skipped entirely (deterministic name-based
    filter — independent of SharePoint mtime which is often unreliable
    on year-bundled folders).
    """
    items = sp.list_folder(site_id, folder_path, drive_id=drive_id,
                           top=500, paginate=True)
    out = []
    for item in items:
        name = item.get("name", "")
        if "folder" in item:
            if year_min is not None:
                fy = folder_year(name)
                if fy is not None and fy < year_min:
                    continue
            sub_path = f"{folder_path}/{name}"
            out.extend(list_files_recursive(sp, site_id, drive_id, sub_path,
                                            year_min=year_min))
        elif "file" in item:
            if Path(name).suffix.lower() in IMAGE_EXTS:
                out.append({
                    "sp_path": f"{folder_path}/{name}",
                    "name": name,
                    "size": item.get("size"),
                    "modified_at": item.get("lastModifiedDateTime"),
                    "item_id": item.get("id"),
                })
    return out


def fetch_all_existing_storage_paths(sb) -> set[str]:
    """Return every non-null storage_path in client_ads as a set.

    client_ads is small (~7k rows), so it's cheaper to pull everything once
    and diff in memory than to do per-batch .in_() lookups (which hit
    PostgREST URL-length limits with multi-hundred path lists).
    """
    out: set[str] = set()
    offset = 0
    while True:
        result = sb.table("client_ads").select("storage_path").range(
            offset, offset + 999
        ).execute()
        rows = result.data or []
        for r in rows:
            sp = r.get("storage_path")
            if sp:
                out.add(sp)
        if len(rows) < 1000:
            break
        offset += 1000
    return out


# ---------- main ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Discovery + diff only — no downloads, uploads, or inserts.")
    parser.add_argument("--no-email", action="store_true")
    parser.add_argument("--no-audit", action="store_true")
    parser.add_argument("--markets", type=str, default=None,
                        help="Comma-separated market codes to scan (e.g. 'CO,UT'). "
                        "Default: all (CO, UT, TX).")
    parser.add_argument("--since", type=str, default=None,
                        help="ISO date — override stored history, treat folders "
                        "modified since this date as fresh (e.g. 2026-01-01).")
    parser.add_argument("--limit", type=int, default=None,
                        help="Cap the number of new files processed this run.")
    parser.add_argument("--full-scan", action="store_true",
                        help="Don't skip subfolders by mtime — scan everything. "
                        "Useful for backfill or sanity checks.")
    parser.add_argument("--year-min", type=int, default=None,
                        help="Hard-skip any subfolder whose name contains a year "
                        "earlier than this (e.g. --year-min 2025). Applied at "
                        "every recursion level. More reliable than --since for "
                        "year-bundled folders with stale parent mtimes.")
    args = parser.parse_args()

    print("=" * 70)
    print(f"Ad JPGs ETL — dry_run={args.dry_run}  full_scan={args.full_scan}")
    print("=" * 70)

    target_markets = [t for t in JPG_TARGETS]
    if args.markets:
        wanted = {m.strip().upper() for m in args.markets.split(",") if m.strip()}
        target_markets = [t for t in target_markets if t[0] in wanted]
    if not target_markets:
        print("ERROR: no markets to process.")
        sys.exit(1)

    # Two clients: sb_db for read queries (always needed for the diff to work),
    # sb_audit for writing audit rows (suppressible via --no-audit).
    sb_db = _audit_client()  # same constructor; just a clearer name
    if sb_db is None:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY required even with --no-audit "
              "(needed for the diff query against client_ads).")
        sys.exit(1)
    sb_audit = None if args.no_audit else sb_db
    run_id = audit_start(sb_audit, dry_run=args.dry_run)
    if run_id:
        print(f"  audit run_id: {run_id}")

    # Resolve "since" cutoff
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) \
            if datetime.fromisoformat(args.since).tzinfo is None \
            else datetime.fromisoformat(args.since)
    elif not args.full_scan:
        since = get_last_successful_run_finish(sb_db)
    print(f"  Subfolder mtime cutoff: {since or '(none — full scan)'}")

    counts = {
        "subfolders_scanned": 0,
        "subfolders_skipped_unchanged": 0,
        "files_scanned": 0,
        "files_already_in_db": 0,
        "files_new": 0,
        "files_uploaded": 0,
        "files_inserted": 0,
        "rows_inserted": 0,
        "rows_unmatched_client": 0,
        "files_failed": 0,
    }
    market_notes: dict = {}
    error_stage = None
    error_message = None

    try:
        # 1) Connect to SharePoint
        print(f"\n[1/4] Connecting to SharePoint...")
        try:
            sp = SharePointClient()
            site_id = sp.resolve_site_id(SP_SITE_URL)
            drive_id = sp.resolve_drive_id(site_id, SP_LIBRARY_NAME)
            print(f"  site_id  = {site_id}")
            print(f"  drive_id = {drive_id}")
        except (SharePointAuthError, SharePointAPIError) as e:
            error_stage = "fetch"
            error_message = f"{type(e).__name__}: {e}"
            print(f"  ABORT: {error_message}")
            if not args.no_email and not args.dry_run:
                email_failure(
                    "[ALERT] Ad JPGs ETL aborted — SharePoint connection failed",
                    f"<pre>{error_message}</pre>"
                )
            sys.exit(1)

        # 2) Per-market discovery + diff
        print(f"\n[2/4] Per-market discovery + diff...")

        # Pre-fetch all existing storage_paths (one batched query) so we can
        # diff in memory instead of hitting PostgREST per market.
        print("  Loading existing client_ads.storage_path values...")
        existing_paths = fetch_all_existing_storage_paths(sb_db)
        print(f"  {len(existing_paths)} storage_path values currently in client_ads")

        all_new_files: list[dict] = []  # one dict per file to download

        for market_code, market_root in target_markets:
            print(f"\n  --- {market_code}: {market_root} ---")
            market_summary = {"subfolders": [], "files_new": 0, "files_already_in_db": 0}

            try:
                subs = sp.list_folder(site_id, market_root, drive_id=drive_id,
                                      top=200, paginate=True)
            except SharePointAPIError as e:
                print(f"  WARN: list failed for {market_root}: {e}")
                market_summary["error"] = str(e)[:300]
                market_notes[market_code] = market_summary
                continue

            sub_dirs = [s for s in subs if "folder" in s]
            print(f"  {len(sub_dirs)} immediate subfolders")

            files_to_diff: list[tuple[str, dict]] = []  # (storage_path, file_meta)

            for sub in sub_dirs:
                counts["subfolders_scanned"] += 1
                sub_name = sub.get("name", "")
                sub_modified = sub.get("lastModifiedDateTime")

                # Hard year-name filter (deterministic, doesn't trust mtime)
                if args.year_min is not None:
                    fy = folder_year(sub_name)
                    if fy is not None and fy < args.year_min:
                        counts["subfolders_skipped_unchanged"] += 1
                        market_summary["subfolders"].append({
                            "name": sub_name,
                            "skip": f"below_year_min_{args.year_min}",
                            "folder_year": fy,
                        })
                        continue

                # mtime-based filter (soft, in addition to year-name)
                if since and sub_modified:
                    sub_dt = datetime.fromisoformat(sub_modified.replace("Z", "+00:00"))
                    if sub_dt <= since:
                        counts["subfolders_skipped_unchanged"] += 1
                        market_summary["subfolders"].append({
                            "name": sub_name,
                            "skip": "unchanged",
                            "modified_at": sub_modified,
                        })
                        continue

                # Enumerate files in this changed subfolder (recursive)
                sub_path = f"{market_root}/{sub_name}"
                files_in_sub = list_files_recursive(sp, site_id, drive_id, sub_path,
                                                     year_min=args.year_min)
                counts["files_scanned"] += len(files_in_sub)
                market_summary["subfolders"].append({
                    "name": sub_name,
                    "skip": None,
                    "modified_at": sub_modified,
                    "files_listed": len(files_in_sub),
                })
                print(f"    {sub_name}: modified {sub_modified}, {len(files_in_sub)} files")

                for f in files_in_sub:
                    storage_path = storage_path_from_sp(f["sp_path"], market_root)
                    files_to_diff.append((storage_path, {
                        **f,
                        "storage_path": storage_path,
                        "market_code": market_code,
                        "market_root": market_root,
                    }))

            # Diff against in-memory set of existing paths
            new_in_market = [meta for sp_path, meta in files_to_diff
                             if sp_path not in existing_paths]
            counts["files_already_in_db"] += len(files_to_diff) - len(new_in_market)
            counts["files_new"] += len(new_in_market)
            market_summary["files_already_in_db"] = len(files_to_diff) - len(new_in_market)
            market_summary["files_new"] = len(new_in_market)
            print(f"  {market_code}: {len(files_to_diff)} files in changed subfolders, "
                  f"{len(new_in_market)} new, {len(files_to_diff) - len(new_in_market)} already in DB")

            all_new_files.extend(new_in_market)
            market_notes[market_code] = market_summary

        # Apply --limit AFTER per-market reporting
        if args.limit:
            all_new_files = all_new_files[: args.limit]
            print(f"\n  --limit {args.limit}: capped to {len(all_new_files)} files for processing")

        if not all_new_files:
            print(f"\n[3/4] Nothing new to process. Done.")
            counts["rows_inserted"] = 0
            return  # caught by finally → audit_finish

        # 3) Process new files (only if --dry-run is OFF)
        if args.dry_run:
            print(f"\n[3/4] DRY RUN — would process {len(all_new_files)} new files. "
                  f"No downloads, no uploads, no inserts.")
            print(f"      Sample of first 5:")
            for f in all_new_files[:5]:
                print(f"        - {f['storage_path']}  ({f.get('size'):,}b)")
            return  # caught by finally

        # Real processing
        print(f"\n[3/4] Processing {len(all_new_files)} new file(s)...")
        sb_write = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

        # Build matching indexes once
        print("  Building client/zone/market indexes...")
        zone_idx, zone_to_market = adloader.build_zone_index(sb_write)
        market_idx = adloader.build_market_index(sb_write)
        clients, idx_norm, idx_lc = adloader.build_client_index(sb_write)

        rows_to_insert = []
        for i, f in enumerate(all_new_files):
            try:
                # Download from SharePoint
                data = sp.download_file_bytes(site_id, f["sp_path"], drive_id=drive_id)

                # Upload to Supabase Storage
                ext = Path(f["name"]).suffix.lower().lstrip(".")
                content_type = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                                "png": "image/png"}.get(ext, "image/jpeg")
                try:
                    sb_write.storage.from_(BUCKET).upload(
                        path=f["storage_path"],
                        file=data,
                        file_options={"content-type": content_type},
                    )
                    counts["files_uploaded"] += 1
                except Exception as up_err:
                    msg = str(up_err).lower()
                    if "already exists" in msg or "duplicate" in msg or "409" in msg:
                        # Object exists in Storage but not in client_ads — orphan upload
                        counts["files_uploaded"] += 1
                    else:
                        raise

                # Parse filename for client/zone/size metadata
                meta = parse_filename(f["name"])
                raw_name = meta.get("client_raw") or ""
                size_code = meta.get("size_code")
                zone_code_raw = meta.get("zone_code")
                issue_code = meta.get("issue_code") or ""

                is_cross_book = zone_code_raw == "XBO" or "XBO" in f["storage_path"]
                is_supplement = issue_code.endswith("s")

                zone_abbr = adloader.ZONE_CODE_MAP.get(zone_code_raw) if zone_code_raw else None
                zone_id = zone_idx.get(zone_abbr) if zone_abbr else None

                source_folder = storage_path_to_source_folder(f["storage_path"])
                ad_market_id = zone_to_market.get(zone_id) if zone_id else None
                if ad_market_id is None:
                    ad_market_id = adloader.market_id_from_filename_hints(
                        f["name"], source_folder, market_idx
                    )

                client_id = adloader.match_client(
                    raw_name, clients, idx_norm, idx_lc, ad_market_id
                )
                if not client_id:
                    counts["rows_unmatched_client"] += 1

                ad_size = adloader.SIZE_CODE_MAP.get(size_code) if size_code else None

                rows_to_insert.append({
                    "client_id": client_id,
                    "zone_id": zone_id,
                    "market_id": ad_market_id,
                    "issue_code": issue_code.rstrip("s") if is_supplement else issue_code,
                    "ad_size": ad_size,
                    "ad_size_code_raw": size_code,
                    "is_cross_book": is_cross_book,
                    "is_supplement": is_supplement,
                    "storage_path": f["storage_path"],
                    "filename_original": f["name"],
                    "source_client_name": raw_name,
                    "source_folder": source_folder,
                })

                if (i + 1) % 25 == 0:
                    print(f"    progress: {i+1}/{len(all_new_files)}")
            except Exception as e:
                counts["files_failed"] += 1
                print(f"    FAIL on {f['storage_path']}: {type(e).__name__}: {str(e)[:200]}")

        # 4) Insert in batches
        if rows_to_insert:
            print(f"\n[4/4] Inserting {len(rows_to_insert)} client_ads rows...")
            BATCH = 100
            for i in range(0, len(rows_to_insert), BATCH):
                batch = rows_to_insert[i:i + BATCH]
                sb_write.table("client_ads").insert(batch).execute()
                counts["rows_inserted"] += len(batch)
                if (i + BATCH) % 500 == 0 or i + BATCH >= len(rows_to_insert):
                    print(f"    {min(i+BATCH, len(rows_to_insert))}/{len(rows_to_insert)} inserted")
        else:
            print(f"\n[4/4] No rows to insert (all {len(all_new_files)} files failed).")

        print(f"\nAd JPGs ETL completed.")
    except Exception as e:
        if error_stage is None:
            error_stage = "unknown"
            error_message = f"{type(e).__name__}: {e}"
            tb = traceback.format_exc(limit=4)
            print(f"\nABORT: {error_message}\n{tb}")
            if not args.no_email and not args.dry_run:
                email_failure(
                    "[ALERT] Ad JPGs ETL failed",
                    f"<pre>{error_message}\n\n{tb}</pre>"
                )
        raise
    finally:
        success = error_stage is None
        notes = {
            "markets": market_notes,
            "args": {
                "markets": args.markets,
                "since": args.since,
                "limit": args.limit,
                "full_scan": args.full_scan,
            },
        }
        audit_finish(sb_audit, run_id, success=success, counts=counts,
                     notes=notes, error_stage=error_stage, error_message=error_message)
        # Print a tidy summary
        print()
        print("=" * 70)
        print(f"  Subfolders scanned:   {counts['subfolders_scanned']}")
        print(f"  Subfolders skipped:   {counts['subfolders_skipped_unchanged']}")
        print(f"  Files scanned:        {counts['files_scanned']}")
        print(f"  Files already in DB:  {counts['files_already_in_db']}")
        print(f"  Files new:            {counts['files_new']}")
        print(f"  Files uploaded:       {counts['files_uploaded']}")
        print(f"  Files failed:         {counts['files_failed']}")
        print(f"  Rows inserted:        {counts['rows_inserted']}")
        print("=" * 70)


if __name__ == "__main__":
    main()
