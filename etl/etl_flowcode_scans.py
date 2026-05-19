"""Ingest Flowcode QR-scan data into Supabase.

Pulls scan totals from the Flowcode Analytics API (`GetConversionRateSummary`)
for every TX Suite-level row in `client_platform_ids` (platform='flowcode',
external_id LIKE 'FC-S-%') and upserts daily/monthly buckets into
`qr_scan_daily`.

Granularity gotcha: Flowcode's API auto-coarsens to monthly buckets when the
requested time range exceeds ~30 days. For backfill (full lifetime), the API
returns monthly buckets keyed at the first of each month. We store those rows
with scan_date = first-of-month. Incremental daily mode would need ~30-day
chunked windows; not implemented here yet.

Usage:
  python etl/etl_flowcode_scans.py --dry-run   # show what would happen
  python etl/etl_flowcode_scans.py --commit    # write to Supabase
  python etl/etl_flowcode_scans.py --commit --start 2024-01-01 --end 2026-05-19
  python etl/etl_flowcode_scans.py --commit --suite-id <uuid>   # just one Suite
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

# Stable namespace for hashing dedupe tuples into row IDs. Same scan event
# always maps to the same UUID, so we can use ON CONFLICT (id) instead of
# fighting the partial-unique index.
SCAN_ROW_NS = uuid.UUID("8b3f1ab5-1e44-4f5b-9f7e-7e0c5af3f9aa")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import supabase as sb
from etl.flowcode_client import FlowcodeClient

ETL_NAME = "flowcode_scans"
DEFAULT_START = "2022-01-01"  # well before TX Flowcode adoption


def fetch_flowcode_cpis(suite_filter: str | None = None) -> list[dict]:
    """Return all TX Suite-level Flowcode rows from client_platform_ids."""
    rows: list[dict] = []
    offset = 0
    while True:
        q = (
            sb.table("client_platform_ids")
            .select("client_id, external_id, external_name, notes")
            .eq("platform", "flowcode")
            .like("external_id", "FC-S-%")
            .range(offset, offset + 999)
        )
        batch = q.execute().data
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    if suite_filter:
        rows = [r for r in rows if suite_filter in r["external_id"]]
    return rows


def parse_suite_id(external_id: str) -> str | None:
    if not external_id.startswith("FC-S-"):
        return None
    return external_id[len("FC-S-"):]


def bucket_to_row(bucket: dict, suite_id: str, client_id: str,
                  period: str, timezone_str: str) -> dict | None:
    """Convert a Flowcode summary rate-bucket into a qr_scan_daily row.

    Empty buckets (no scans/visits) are returned as zero-rows so the table
    reflects "we checked this day and nothing happened" -- useful for the
    Streamlit dashboards downstream so days don't silently disappear.
    """
    d = bucket.get("date") or {}
    y, m, day = d.get("year"), d.get("month"), d.get("day")
    if not (y and m and day):
        return None
    scan_date = f"{y:04d}-{m:02d}-{day:02d}"
    # Deterministic UUID so re-runs hit the same row -> upsert by id works
    dedupe_key = f"flowcode|{suite_id}||{scan_date}|{timezone_str}"
    row_id = str(uuid.uuid5(SCAN_ROW_NS, dedupe_key))
    return {
        "id": row_id,
        "platform": "flowcode",
        "suite_id": suite_id,
        "code_id": None,           # Suite-level rollup
        "batch_id": None,
        "client_id": client_id,
        "scan_date": scan_date,
        "scans": int(bucket.get("scans") or 0),
        "views": int(bucket.get("visits") or 0),
        "unique_visitors": int(bucket.get("uniques") or bucket.get("uniqueVisitors") or 0),
        "timezone": timezone_str,
    }


def audit_start(dry_run: bool) -> str | None:
    try:
        result = (
            sb.table("etl_runs")
            .insert({
                "etl_name": ETL_NAME,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "dry_run": dry_run,
                "host": socket.gethostname(),
                "github_run_id": os.getenv("GITHUB_RUN_ID"),
            })
            .execute()
        )
        return result.data[0]["id"] if result.data else None
    except Exception as e:
        print(f"  WARNING: audit start failed: {e}")
        return None


def audit_finish(run_id: str | None, *, success: bool,
                 stats: dict | None = None,
                 error_message: str | None = None) -> None:
    if run_id is None:
        return
    try:
        update = {
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "error_message": error_message,
        }
        if stats:
            update["rows_read"] = stats.get("suites_pulled")
            update["notes"] = stats
        sb.table("etl_runs").update(update).eq("id", run_id).execute()
    except Exception as e:
        print(f"  WARNING: audit finish failed: {e}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START, help="YYYY-MM-DD inclusive (default %(default)s)")
    ap.add_argument("--end", default=date.today().isoformat(), help="YYYY-MM-DD inclusive (default today)")
    ap.add_argument("--commit", action="store_true", help="Actually write to Supabase")
    ap.add_argument("--dry-run", action="store_true", help="No writes (default if --commit absent)")
    ap.add_argument("--suite-id", help="Process only one Suite UUID (substring match)")
    ap.add_argument("--timezone", default="America/Denver")
    ap.add_argument("--sleep", type=float, default=0.5, help="Sleep between API calls (sec)")
    args = ap.parse_args()
    dry_run = not args.commit

    fc = FlowcodeClient()
    print(f"Pulling Flowcode Suite-level CPIs from Supabase ...")
    cpis = fetch_flowcode_cpis(args.suite_id)
    print(f"  {len(cpis)} Suite-level CPI rows")
    if not cpis:
        print("Nothing to do.")
        return 0

    run_id = audit_start(dry_run) if args.commit else None

    api_base = {
        "interval": "INTERVAL_CUSTOM",
        "timezone": args.timezone,
        "orgId": fc.org_id,
        "workspaceId": fc.workspace_id,
        "period": "PERIOD_DAY",  # API may auto-coarsen to PERIOD_MONTH
        "timeRange": {
            "startTime": f"{args.start}T00:00:00Z",
            "endTime": f"{args.end}T23:59:59Z",
        },
    }

    total_suites = 0
    total_buckets = 0
    total_scans = 0
    upserted_rows = 0
    period_seen = {"PERIOD_DAY": 0, "PERIOD_MONTH": 0, "OTHER": 0}
    failed: list[dict] = []

    pending_batch: list[dict] = []
    BATCH_SIZE = 250  # PostgREST upsert chunk

    def flush(rows: list[dict]) -> int:
        if not rows:
            return 0
        if dry_run:
            return len(rows)
        sb.table("qr_scan_daily").upsert(
            rows,
            on_conflict="id",
        ).execute()
        return len(rows)

    for i, cpi in enumerate(cpis, 1):
        suite_id = parse_suite_id(cpi["external_id"])
        if not suite_id:
            continue
        body = {**api_base, "filter": {"suiteId": suite_id}}
        try:
            res = fc.post("/abacus.v2.AbacusService/GetConversionRateSummary", body)
        except Exception as e:
            failed.append({"suite_id": suite_id, "err": str(e)[:200]})
            continue

        summary = res.get("summary") or {}
        period = summary.get("period", "OTHER")
        period_seen[period] = period_seen.get(period, 0) + 1
        rates = summary.get("rates") or []
        suite_total = int(summary.get("totalScans") or 0)
        total_scans += suite_total
        total_suites += 1

        for bucket in rates:
            row = bucket_to_row(bucket, suite_id, cpi["client_id"], period, args.timezone)
            if row is None:
                continue
            total_buckets += 1
            pending_batch.append(row)
            if len(pending_batch) >= BATCH_SIZE:
                upserted_rows += flush(pending_batch)
                pending_batch = []

        if i % 25 == 0:
            print(f"  {i}/{len(cpis)} Suites pulled "
                  f"({total_buckets} buckets, {total_scans} total scans so far)")
        time.sleep(args.sleep)

    upserted_rows += flush(pending_batch)
    pending_batch = []

    stats = {
        "suites_pulled": total_suites,
        "buckets_received": total_buckets,
        "total_scans_lifetime": total_scans,
        "rows_upserted": upserted_rows,
        "period_breakdown": period_seen,
        "failed_suites": len(failed),
        "range": {"start": args.start, "end": args.end},
        "timezone": args.timezone,
    }
    print()
    print("=" * 60)
    print(f"Suites pulled:       {total_suites}")
    print(f"Buckets received:    {total_buckets}")
    print(f"  -> period seen:    {period_seen}")
    print(f"Total scans:         {total_scans:,}")
    print(f"Rows upserted:       {upserted_rows}{'  (dry run)' if dry_run else ''}")
    print(f"Failed suites:       {len(failed)}")
    for f in failed[:5]:
        print(f"  {f['suite_id'][:8]}...  {f['err'][:120]}")

    audit_finish(run_id, success=(len(failed) == 0), stats=stats,
                 error_message=(f"{len(failed)} suites failed" if failed else None))

    return 0 if not failed else 2


if __name__ == "__main__":
    sys.exit(main())
