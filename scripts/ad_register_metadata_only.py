"""Register THM Ads JPGs in client_ads with parsed filename metadata only — no vision extraction.

Uses ad_load_to_supabase's parsing + client matcher (with the 2026-05-06 safety rules)
so client_id, zone_id, ad_size, and issue_code are populated. Headline / offers /
extraction stay NULL — to be backfilled later by the vision pipeline.

Idempotent: upserts on storage_path and the matcher's preserve-existing-client_id
guard keeps any manual mappings intact.

Usage:
  python scripts/ad_register_metadata_only.py            # all ads
  python scripts/ad_register_metadata_only.py --folder "THM Texas 2025-05"
  python scripts/ad_register_metadata_only.py --since 2024-01    # folders >= YYYY-MM
"""

import os
import re
import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(override=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from supabase import create_client
from ad_vision_batch import parse_filename
import ad_load_to_supabase as loader

ADS_ROOT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\THM Ads")
IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", help="Only register a specific folder under THM Ads")
    ap.add_argument("--since", help="Only register folders with YYYY-MM >= this (e.g. 2025-01)")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY not set")
        sys.exit(1)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("Building indexes...")
    zone_idx, zone_to_market = loader.build_zone_index(sb)
    market_idx = loader.build_market_index(sb)
    clients, idx_norm, idx_lc = loader.build_client_index(sb)

    # Discover files
    if args.folder:
        roots = [ADS_ROOT / args.folder]
    else:
        roots = [p for p in ADS_ROOT.iterdir() if p.is_dir() and not p.name.startswith("_")]
        if args.since:
            since_re = re.compile(r"(\d{4})-(\d{2})")
            cutoff = args.since
            kept = []
            for p in roots:
                m = since_re.search(p.name)
                if m and f"{m.group(1)}-{m.group(2)}" >= cutoff:
                    kept.append(p)
            roots = kept

    files: list[Path] = []
    for r in sorted(roots):
        if not r.exists():
            print(f"  skip (missing): {r.name}")
            continue
        for p in r.rglob("*"):
            if p.suffix.lower() in IMAGE_EXTS:
                files.append(p)
    if args.limit:
        files = files[: args.limit]
    print(f"Discovered {len(files)} ads across {len(roots)} folders")

    rows = []
    unmatched_names = set()
    matched = 0
    for path in files:
        relpath = str(path.relative_to(ADS_ROOT)).replace("\\", "/")
        folder = path.relative_to(ADS_ROOT).parts[0]
        meta = parse_filename(path.name)
        raw_name = meta.get("client_raw") or ""
        size_code = meta.get("size_code")
        zone_code_raw = meta.get("zone_code")
        issue_code = meta.get("issue_code") or ""

        is_cross_book = zone_code_raw == "XBO" or "XBO" in relpath
        is_supplement = issue_code.endswith("s")

        zone_abbr = loader.ZONE_CODE_MAP.get(zone_code_raw) if zone_code_raw else None
        zone_id = zone_idx.get(zone_abbr) if zone_abbr else None

        ad_market_id = zone_to_market.get(zone_id) if zone_id else None
        if ad_market_id is None:
            ad_market_id = loader.market_id_from_filename_hints(path.name, folder, market_idx)

        client_id = loader.match_client(raw_name, clients, idx_norm, idx_lc, ad_market_id)
        if client_id:
            matched += 1
        else:
            unmatched_names.add(raw_name)

        ad_size = loader.SIZE_CODE_MAP.get(size_code) if size_code else None

        rows.append({
            "client_id": client_id,
            "zone_id": zone_id,
            "market_id": ad_market_id,
            "issue_code": issue_code.rstrip("s") if is_supplement else issue_code,
            "ad_size": ad_size,
            "ad_size_code_raw": size_code,
            "is_cross_book": is_cross_book,
            "is_supplement": is_supplement,
            "storage_path": relpath,
            "filename_original": path.name,
            "source_client_name": raw_name,
            "source_folder": folder,
        })

    print(f"Parsed {len(rows)} rows. Matched: {matched} ({100*matched/max(1,len(rows)):.1f}%)")
    if unmatched_names:
        sample = sorted(unmatched_names)[:15]
        print(f"Unmatched name examples ({len(unmatched_names)} unique): {sample}")

    # Filter out rows that already exist in client_ads — never UPDATE existing rows
    # because that would clobber extraction data populated by the vision pipeline.
    # Only INSERT brand-new storage_paths.
    storage_paths = [r["storage_path"] for r in rows if r.get("storage_path")]
    print(f"Checking {len(storage_paths)} storage paths for existing rows...")
    existing_paths: set[str] = set()
    BATCH = 200
    for i in range(0, len(storage_paths), BATCH):
        chunk = storage_paths[i : i + BATCH]
        result = sb.table("client_ads").select("storage_path").in_("storage_path", chunk).execute()
        for r in result.data:
            existing_paths.add(r["storage_path"])
    print(f"  {len(existing_paths)} already exist — will skip those.")

    new_rows = [r for r in rows if r["storage_path"] not in existing_paths]
    print(f"  {len(new_rows)} brand-new rows to insert.")

    if not new_rows:
        print("Nothing to do.")
        return

    BATCH = 100
    total = 0
    for i in range(0, len(new_rows), BATCH):
        batch = new_rows[i:i + BATCH]
        sb.table("client_ads").insert(batch).execute()
        total += len(batch)
        if total % 500 == 0 or total == len(new_rows):
            print(f"  {total}/{len(new_rows)}")

    print(f"\nDone. Inserted {total} new client_ads rows. Vision extraction skipped — run later if needed.")


if __name__ == "__main__":
    main()
