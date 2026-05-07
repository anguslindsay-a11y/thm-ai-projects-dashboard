"""
Backfill: Re-sync call_tags from CallRail for a date range.

Re-fetches each call's current tag list from CallRail, compares to what's
in our call_tags table, and applies the diff (INSERT missing pairs +
DELETE stale pairs).

Use this when tags have been corrected in CallRail (added or removed) on
calls that fall outside the daily ETL's 30-day window, or for any case
where you need to reconcile our tags with CallRail's source of truth.

Usage:
  python scripts/resync_call_tags.py --start 2025-01-01           # dry-run preview
  python scripts/resync_call_tags.py --start 2025-01-01 --apply   # write changes
  python scripts/resync_call_tags.py --start 2025-01-01 --account ACCe42c... --apply
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from etl.etl_callrail import (
    CALLRAIL_ACCOUNTS,
    SUPABASE_URL,
    SUPABASE_KEY,
    fetch_calls,
    build_callrail_tag_to_local_map,
    log,
)
from supabase import create_client


def fetch_local_call_ids(sb, callrail_ids: list[str]) -> dict[str, str]:
    """Map CallRail call IDs to local UUIDs via batched lookups."""
    out = {}
    BATCH = 200
    for i in range(0, len(callrail_ids), BATCH):
        chunk = callrail_ids[i : i + BATCH]
        result = sb.table("calls").select("id,callrail_id").in_("callrail_id", chunk).execute()
        for r in result.data:
            out[r["callrail_id"]] = r["id"]
    return out


def fetch_current_pairs(sb, local_call_ids: list[str]) -> dict[str, set]:
    """For the given local call IDs, return {call_id: set(tag_id)} from call_tags."""
    out: dict[str, set] = {}
    BATCH = 200
    for i in range(0, len(local_call_ids), BATCH):
        chunk = local_call_ids[i : i + BATCH]
        result = sb.table("call_tags").select("call_id,tag_id").in_("call_id", chunk).execute()
        for r in result.data:
            out.setdefault(r["call_id"], set()).add(r["tag_id"])
    return out


def apply_diff(sb, to_insert: list[dict], to_delete: dict[str, set]) -> tuple[int, int]:
    """Apply the diff. Inserts go in batches of 500. Deletes go per-call."""
    inserted = 0
    deleted = 0

    if to_insert:
        BATCH = 500
        for i in range(0, len(to_insert), BATCH):
            batch = to_insert[i : i + BATCH]
            try:
                sb.table("call_tags").upsert(batch, on_conflict="call_id,tag_id").execute()
                inserted += len(batch)
            except Exception as e:
                log.warning(f"  insert batch failed, falling back per-row: {str(e)[:100]}")
                for row in batch:
                    try:
                        sb.table("call_tags").upsert(row, on_conflict="call_id,tag_id").execute()
                        inserted += 1
                    except Exception:
                        pass
            if inserted % 2000 == 0:
                log.info(f"  ... {inserted} inserts applied")

    if to_delete:
        for call_id, tag_ids in to_delete.items():
            if not tag_ids:
                continue
            try:
                sb.table("call_tags").delete().eq("call_id", call_id).in_("tag_id", list(tag_ids)).execute()
                deleted += len(tag_ids)
            except Exception as e:
                log.warning(f"  delete failed for call {call_id}: {str(e)[:100]}")
            if deleted % 2000 == 0 and deleted > 0:
                log.info(f"  ... {deleted} deletes applied")

    return inserted, deleted


def resync_account(sb, account_id: str, account_name: str, start_date: str, end_date: str,
                   tag_map: dict, apply: bool) -> dict:
    """Resync one CallRail account's tags for the date window."""
    log.info(f"\n=== {account_name} ({account_id}) ===")
    log.info(f"Fetching calls from CallRail {start_date} → {end_date}...")

    raw_calls = list(fetch_calls(start_date, end_date, account_id=account_id))
    log.info(f"  {len(raw_calls)} calls fetched from CallRail")

    if not raw_calls:
        return {"calls": 0, "inserts": 0, "deletes": 0, "missing": 0}

    cr_ids = [str(c.get("id")) for c in raw_calls if c.get("id")]
    cr_to_local = fetch_local_call_ids(sb, cr_ids)
    log.info(f"  {len(cr_to_local)} calls resolved to local IDs ({len(cr_ids) - len(cr_to_local)} not in our DB)")

    desired_per_call: dict[str, set] = {}
    unknown_tag_count = 0
    for call in raw_calls:
        cr_id = str(call.get("id", ""))
        local_call_id = cr_to_local.get(cr_id)
        if not local_call_id:
            continue
        desired: set = set()
        for t in (call.get("tags") or []):
            cr_tag_id = t.get("id")
            local_tag_id = tag_map.get(cr_tag_id)
            if local_tag_id:
                desired.add(local_tag_id)
            else:
                unknown_tag_count += 1
        desired_per_call[local_call_id] = desired

    if unknown_tag_count:
        log.warning(f"  {unknown_tag_count} CallRail tag references not found in local tags table — ignored")

    log.info(f"  Reading current call_tags for {len(desired_per_call)} calls...")
    current_per_call = fetch_current_pairs(sb, list(desired_per_call.keys()))

    to_insert: list[dict] = []
    to_delete: dict[str, set] = {}
    calls_with_diff = 0
    for local_call_id, desired in desired_per_call.items():
        current = current_per_call.get(local_call_id, set())
        adds = desired - current
        removes = current - desired
        if adds or removes:
            calls_with_diff += 1
        for tag_id in adds:
            to_insert.append({"call_id": local_call_id, "tag_id": tag_id})
        if removes:
            to_delete[local_call_id] = removes

    log.info(f"  Diff: {len(to_insert)} pairs to insert, "
             f"{sum(len(v) for v in to_delete.values())} pairs to delete, "
             f"{calls_with_diff} calls affected")

    if not apply:
        log.info("  DRY RUN — no changes written")
        return {
            "calls": len(desired_per_call),
            "inserts": len(to_insert),
            "deletes": sum(len(v) for v in to_delete.values()),
            "missing": len(cr_ids) - len(cr_to_local),
        }

    log.info(f"  Applying changes...")
    inserted, deleted = apply_diff(sb, to_insert, to_delete)
    log.info(f"  Applied: {inserted} inserts, {deleted} deletes")

    return {
        "calls": len(desired_per_call),
        "inserts": inserted,
        "deletes": deleted,
        "missing": len(cr_ids) - len(cr_to_local),
    }


def main():
    parser = argparse.ArgumentParser(description="Resync call_tags from CallRail for a date range")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="End date (YYYY-MM-DD, default: today)")
    parser.add_argument("--apply", action="store_true",
                        help="Write changes. Without this flag, runs as a dry-run preview.")
    parser.add_argument("--account", type=str, default=None,
                        help="Limit to a specific CallRail account ID. Default: all 3.")
    args = parser.parse_args()

    start_date = args.start
    end_date = args.end or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    if not SUPABASE_URL or not SUPABASE_KEY:
        log.error("Missing SUPABASE_URL or SUPABASE_KEY in env")
        sys.exit(1)

    accounts = CALLRAIL_ACCOUNTS
    if args.account:
        accounts = [(aid, name) for aid, name in CALLRAIL_ACCOUNTS if aid == args.account]
        if not accounts:
            log.error(f"Unknown account: {args.account}")
            sys.exit(1)

    log.info(f"Call tags resync — {start_date} → {end_date} ({'APPLY' if args.apply else 'DRY-RUN'})")
    log.info(f"Accounts: {', '.join(name for _, name in accounts)}")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    log.info("Building CallRail tag → local tag map...")
    tag_map = build_callrail_tag_to_local_map(sb)
    log.info(f"  {len(tag_map)} CallRail tag IDs mapped to local tags")

    totals = {"calls": 0, "inserts": 0, "deletes": 0, "missing": 0}
    for account_id, account_name in accounts:
        result = resync_account(sb, account_id, account_name, start_date, end_date, tag_map, args.apply)
        for k, v in result.items():
            totals[k] += v

    log.info(f"\n{'=' * 60}")
    log.info(f"  TOTALS ({'APPLIED' if args.apply else 'DRY-RUN'})")
    log.info(f"{'=' * 60}")
    log.info(f"  Calls processed:     {totals['calls']}")
    log.info(f"  Pairs to insert:     {totals['inserts']}")
    log.info(f"  Pairs to delete:     {totals['deletes']}")
    log.info(f"  Calls not in DB:     {totals['missing']}")
    log.info(f"{'=' * 60}")

    if not args.apply:
        log.info("\nThis was a DRY RUN. Re-run with --apply to write changes.")


if __name__ == "__main__":
    main()
