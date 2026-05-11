"""ETL: MagManager Opportunities -> Supabase opportunities

Pulls api_OpportunityGetTHM across all 3 tenants and upserts into opportunities.
Greenfield — we had no pipeline data before this.

Identity:
  - opportunities.mm_database + mm_opportunity_id is the natural key
  - opportunities.client_id resolved via (mm_database, mm_customer_id) lookup on clients

Updates:
  - Always upserts on (mm_database, mm_opportunity_id) — idempotent
  - Skip-if-unchanged via mm_modified_date prefix comparison

Usage:
  python etl/etl_mm_opportunities.py [--dry-run] [--tenant CO|UT|SA] [--no-audit]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from etl.magmanager_client import MagManagerClient

load_dotenv()

DATABASES = [
    "thehomemagcolorado",
    "thehomemagutah",
    "thehomemagsanantonio",
]
UPSERT_BATCH_SIZE = 200


def parse_int_array(s: str | None) -> list[int]:
    """Parse comma-joined int string like '8214, 8233' -> [8214, 8233]."""
    if not s:
        return []
    out = []
    for part in s.split(","):
        part = part.strip()
        if part.isdigit():
            out.append(int(part))
    return out


def parse_string_array(s: str | None) -> list[str]:
    """Split comma-joined string and strip empties."""
    if not s:
        return []
    return [p.strip() for p in s.split(",") if p.strip()]


def parse_date(s: str | None) -> str | None:
    if not s:
        return None
    return s[:10] if len(s) >= 10 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tenant", choices=["CO", "UT", "SA"])
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    print("=" * 70)
    print("MAGMANAGER OPPORTUNITIES ETL")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print("=" * 70)

    mm = MagManagerClient()
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 0) Lookups
    # ------------------------------------------------------------------
    print("\n[0/4] Loading reference data...")

    # Client lookup by (mm_database, mm_customer_id)
    client_lookup = {}
    offset = 0
    while True:
        batch = (
            sb.table("clients")
            .select("id,mm_database,mm_customer_id")
            .not_.is_("mm_database", "null")
            .not_.is_("mm_customer_id", "null")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for c in batch:
            client_lookup[(c["mm_database"], c["mm_customer_id"])] = c["id"]
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  client lookup keys: {len(client_lookup):,}")

    # Existing opportunities (for skip-if-unchanged)
    existing_opps = {}
    offset = 0
    while True:
        batch = (
            sb.table("opportunities")
            .select("mm_database,mm_opportunity_id,mm_modified_date")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for o in batch:
            key = (o["mm_database"], o["mm_opportunity_id"])
            existing_opps[key] = o.get("mm_modified_date")
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  existing opportunities: {len(existing_opps):,}")

    # ------------------------------------------------------------------
    # 1) Pull opportunities per tenant
    # ------------------------------------------------------------------
    print("\n[1/4] Pulling opportunities...")
    tenants_to_run = [d for d in DATABASES if not args.tenant
                       or (args.tenant == "CO" and d == "thehomemagcolorado")
                       or (args.tenant == "UT" and d == "thehomemagutah")
                       or (args.tenant == "SA" and d == "thehomemagsanantonio")]

    all_opps: list[dict] = []
    for db in tenants_to_run:
        page = 1
        while True:
            body = mm.get_opportunities_page(page=page, database_name=db)
            rows = body.get("Data") or []
            for r in rows:
                r.setdefault("DatabaseName", db)
            all_opps.extend(rows)
            print(f"  {db} page {page}: {len(rows)} rows")
            if len(rows) < 1000:
                break
            page += 1
            if page > 50:
                break
    print(f"  TOTAL: {len(all_opps):,} opportunities pulled")

    # ------------------------------------------------------------------
    # 2) Build upsert payloads
    # ------------------------------------------------------------------
    print("\n[2/4] Building payloads...")
    payloads = []
    no_client_match = []
    stats = defaultdict(Counter)

    for o in all_opps:
        db = o["DatabaseName"]
        opp_id = o.get("OpportunityID")
        if opp_id is None:
            continue
        mm_modified = o.get("ModifiedDate") or o.get("CreatedDate")
        key = (db, opp_id)

        # Skip-if-unchanged
        existing_modified = existing_opps.get(key)
        if (existing_modified and mm_modified
                and existing_modified[:19] == mm_modified[:19]):
            stats[db]["skip_unchanged"] += 1
            continue

        # Resolve client
        customer_id = o.get("CustomerID")
        client_id = client_lookup.get((db, customer_id)) if customer_id is not None else None
        if customer_id is not None and client_id is None:
            no_client_match.append({"db": db, "customer_id": customer_id,
                                     "name": o.get("Customer"),
                                     "opp_id": opp_id})

        status_in = o.get("Status")
        is_won = o.get("IsWon")
        # Normalize is_won to -1/0/1 ints
        if isinstance(is_won, bool):
            is_won = 1 if is_won else 0

        payload = {
            "mm_database": db,
            "mm_opportunity_id": int(opp_id),
            "client_id": client_id,
            "mm_contact_id": o.get("ContactID"),
            "name": o.get("OpportunityName"),
            "description": o.get("Description"),
            "next_step": o.get("NextStep"),
            "notes": o.get("Notes"),
            "stage_id": o.get("StageID"),
            "stage_name": o.get("Stage"),
            "stage_percent_closed": o.get("StagePercentClosed"),
            "status": status_in,
            "is_won": is_won,
            "opportunity_type": o.get("OpportunityType"),
            "source": o.get("Source"),
            "loss_reason": o.get("LossReason"),
            "owner_rep_id": o.get("OwnerID"),
            "owner_rep_name": o.get("Owner"),
            "assigned_rep_id": o.get("AssignedToID"),
            "assigned_rep_name": o.get("AssignedTo"),
            "business_unit_primary": o.get("BusinessUnit"),
            "business_units": parse_string_array(o.get("BusinessUnits")) or None,
            "product_primary": o.get("Product"),
            "products": parse_string_array(o.get("Products")) or None,
            "proposal_ids": parse_int_array(o.get("ProposalIDs")) or None,
            "amount": o.get("Amount"),
            "probability": o.get("Probability"),
            "expected_revenue": o.get("ExpectedRevenue"),
            "close_date": parse_date(o.get("CloseDate")),
            "actual_close_date": parse_date(o.get("ActualCloseDate")),
            "mm_created_date": o.get("CreatedDate"),
            "mm_modified_date": o.get("ModifiedDate"),
        }

        stats[db]["insert_or_update"] += 1
        stats[db][f"status_{status_in or 'NULL'}"] += 1
        payloads.append(payload)

    total_writes = sum(s.get("insert_or_update", 0) for s in stats.values())
    total_skipped = sum(s.get("skip_unchanged", 0) for s in stats.values())
    print(f"  to write: {total_writes:,}")
    print(f"  skipped unchanged: {total_skipped:,}")
    print(f"  no client match: {len(no_client_match):,}")
    print(f"  status distribution: ")
    for db in tenants_to_run:
        for k, v in sorted(stats[db].items()):
            if k.startswith("status_"):
                print(f"    {db} {k.replace('status_','')}: {v}")

    # ------------------------------------------------------------------
    # 3) Upsert
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[3/4] DRY-RUN — skipping writes")
    elif payloads:
        print(f"\n[3/4] Upserting {len(payloads):,} rows in batches of {UPSERT_BATCH_SIZE}...")
        for i in range(0, len(payloads), UPSERT_BATCH_SIZE):
            chunk = payloads[i : i + UPSERT_BATCH_SIZE]
            sb.table("opportunities").upsert(
                chunk, on_conflict="mm_database,mm_opportunity_id"
            ).execute()
            if (i // UPSERT_BATCH_SIZE) % 5 == 0:
                print(f"  {i + len(chunk):,} / {len(payloads):,}")
        print(f"  upserted {len(payloads):,} rows")
    else:
        print("\n[3/4] Nothing to write")

    # ------------------------------------------------------------------
    # 4) Audit + summary
    # ------------------------------------------------------------------
    finished_at = datetime.now(timezone.utc)
    elapsed = (finished_at - started_at).total_seconds()
    print(f"\n[4/4] Elapsed: {elapsed:.1f}s")

    summary = {
        "mode": "dry-run" if args.dry_run else "write",
        "tenants": tenants_to_run,
        "stats_by_db": {k: dict(v) for k, v in stats.items()},
        "total_pulled": len(all_opps),
        "total_writes": total_writes,
        "total_skipped_unchanged": total_skipped,
        "no_client_match_count": len(no_client_match),
        "no_client_match_first10": no_client_match[:10],
    }

    if not args.no_audit and not args.dry_run:
        sb.table("etl_runs").insert({
            "etl_name": "mm_opportunities",
            "source": "magmanager_api",
            "dry_run": False,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "success": True,
            "rows_read": len(all_opps),
            "rows_upserted_campaigns": total_writes,
            "host": socket.gethostname(),
            "notes": summary,
        }).execute()
        print("  etl_runs row recorded")

    print("\nSummary:")
    print(json.dumps({k: v for k, v in summary.items() if "first10" not in k}, indent=2, default=str))


if __name__ == "__main__":
    main()
