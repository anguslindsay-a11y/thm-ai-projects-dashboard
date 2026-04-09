"""
Import Waterfall Order Data into Supabase orders table.

Reads the Waterfall Order Data 4-9 spreadsheet and populates the orders table.
Matches companies to existing clients by name. Creates new clients for unmatched.
Uses mm_order_id + zone_id as the unique key (upsert).

Usage:
  python setup/import_orders.py --dry-run   # Preview only
  python setup/import_orders.py              # Run the import
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client
from openpyxl import load_workbook

EXCEL_PATH = Path(__file__).resolve().parent.parent / "data" / "Waterfall Order Data 4-9.xlsx"

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Mkt values in spreadsheet -> zone names in Supabase
MKT_TO_ZONE_NAME = {
    "CO": "Colorado",
    "UT": "Utah",
    "AU": "Austin",
    "SA": "San Antonio",
}

# Columns to import (index -> field name)
# Skipping Excel helper columns: Issue Date Filter, Company Match, Mkt Filter,
# Start Issue, Category, Start Issue Filter, Priority, Priority Filter
COL_MAP = {
    0: "mkt",              # -> zone lookup
    1: "issue_date",       # text format like "24.02.Feb"
    2: "company",          # -> client lookup
    3: "product",
    4: "size",
    5: "position",
    6: "notes",
    7: "net",
    8: "gross",
    9: "sales_rep",
    10: "commission_rep",
    11: "contact_type",
    12: "ia_category",
    13: "opp_category",
    14: "mm_order_id",
    15: "special_section",
    16: "amount_due",
    17: "proposal_type",
    18: "space",
    25: "biz_category",
    28: "date",            # parsed date
    29: "year",
}


def read_spreadsheet():
    wb = load_workbook(str(EXCEL_PATH), read_only=True, data_only=True)
    ws = wb.active
    all_rows = list(ws.iter_rows(values_only=True))
    headers = all_rows[0]
    data = []
    for row in all_rows[1:]:
        record = {}
        for idx, field in COL_MAP.items():
            record[field] = row[idx]
        data.append(record)
    wb.close()
    return data


def parse_date(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_year(val):
    if val is None:
        return None
    try:
        return int(str(val).strip())
    except (ValueError, TypeError):
        return None


def to_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def to_str(val):
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def run_import(rows, dry_run=True):
    total = len(rows)
    unique_companies = set(to_str(r["company"]) for r in rows if r.get("company"))
    mkts = {}
    for r in rows:
        m = to_str(r.get("mkt"))
        if m:
            mkts[m] = mkts.get(m, 0) + 1

    print(f"\n{'='*50}")
    print(f"  WATERFALL ORDER DATA ANALYSIS")
    print(f"{'='*50}")
    print(f"  Total rows:          {total}")
    print(f"  Unique companies:    {len(unique_companies)}")
    print(f"  Markets:             {mkts}")
    print(f"{'='*50}\n")

    if dry_run:
        print("  DRY RUN — no data will be written.\n")
        print(f"  Would insert up to {total} order records")
        print(f"  Would create clients for any unmatched companies")
        print()
        return

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load zones
    zones_result = sb.table("zones").select("*").execute()
    zone_by_name = {z["name"]: z for z in zones_result.data}
    zone_lookup = {}  # mkt code -> zone row
    for mkt_code, zone_name in MKT_TO_ZONE_NAME.items():
        if zone_name in zone_by_name:
            zone_lookup[mkt_code] = zone_by_name[zone_name]

    # Load all clients
    print("Loading existing clients...")
    all_clients = []
    offset = 0
    while True:
        batch = sb.table("clients").select("id,name").range(offset, offset + 999).execute()
        all_clients.extend(batch.data)
        if len(batch.data) < 1000:
            break
        offset += 1000
    client_lookup = {c["name"]: c["id"] for c in all_clients}
    print(f"  {len(client_lookup)} clients in DB")

    # Find unmatched companies and create them
    unmatched = set()
    for r in rows:
        company = to_str(r.get("company"))
        if company and company not in client_lookup:
            unmatched.add(company)

    if unmatched:
        print(f"\nCreating {len(unmatched)} new clients for unmatched companies...")
        created = 0
        for company in sorted(unmatched):
            result = sb.table("clients").insert({"name": company}).execute()
            client_lookup[company] = result.data[0]["id"]
            created += 1
            if created % 100 == 0:
                print(f"  ... {created} created")
        print(f"  Created {created} new clients")

    # Insert orders in batches
    print(f"\nInserting {total} orders...")
    inserted = 0
    skipped = 0
    errors = 0
    batch = []
    BATCH_SIZE = 100

    for r in rows:
        company = to_str(r.get("company"))
        mkt = to_str(r.get("mkt"))
        order_id = r.get("mm_order_id")

        if not order_id or not mkt or mkt not in zone_lookup:
            skipped += 1
            continue

        client_id = client_lookup.get(company) if company else None
        zone_id = zone_lookup[mkt]["id"]

        record = {
            "mm_order_id": int(order_id),
            "client_id": client_id,
            "zone_id": zone_id,
            "issue_date": to_str(r.get("issue_date")),
            "issue_date_parsed": parse_date(r.get("date")),
            "product": to_str(r.get("product")),
            "size": to_str(r.get("size")),
            "position": to_str(r.get("position")),
            "notes": to_str(r.get("notes")),
            "net": to_float(r.get("net")),
            "gross": to_float(r.get("gross")),
            "amount_due": to_float(r.get("amount_due")),
            "sales_rep": to_str(r.get("sales_rep")),
            "commission_rep": to_str(r.get("commission_rep")),
            "contact_type": to_str(r.get("contact_type")),
            "ia_category": to_str(r.get("ia_category")),
            "opp_category": to_str(r.get("opp_category")),
            "biz_category": to_str(r.get("biz_category")),
            "special_section": to_str(r.get("special_section")),
            "proposal_type": to_str(r.get("proposal_type")),
            "space": to_str(r.get("space")),
            "year": parse_year(r.get("year")),
        }
        batch.append(record)

        if len(batch) >= BATCH_SIZE:
            try:
                sb.table("orders").upsert(
                    batch, on_conflict="mm_order_id,zone_id"
                ).execute()
                inserted += len(batch)
            except Exception as e:
                # Fall back to one-by-one for this batch
                for rec in batch:
                    try:
                        sb.table("orders").upsert(
                            rec, on_conflict="mm_order_id,zone_id"
                        ).execute()
                        inserted += 1
                    except Exception as e2:
                        errors += 1
                        if errors <= 5:
                            print(f"  WARNING: Order {rec['mm_order_id']}: {str(e2)[:100]}")
            batch = []
            if inserted % 2000 == 0 and inserted > 0:
                print(f"  ... {inserted} orders inserted")

    # Flush remaining batch
    if batch:
        try:
            sb.table("orders").upsert(
                batch, on_conflict="mm_order_id,zone_id"
            ).execute()
            inserted += len(batch)
        except Exception:
            for rec in batch:
                try:
                    sb.table("orders").upsert(
                        rec, on_conflict="mm_order_id,zone_id"
                    ).execute()
                    inserted += 1
                except Exception as e2:
                    errors += 1

    print(f"\n{'='*50}")
    print(f"  ORDER IMPORT COMPLETE")
    print(f"{'='*50}")
    print(f"  Orders inserted:     {inserted}")
    print(f"  Skipped:             {skipped}")
    print(f"  Errors:              {errors}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Import Waterfall order data into Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set in .env")
        sys.exit(1)
    if not EXCEL_PATH.exists():
        print(f"ERROR: Spreadsheet not found at {EXCEL_PATH}")
        sys.exit(1)

    print(f"Reading spreadsheet: {EXCEL_PATH.name}")
    rows = read_spreadsheet()
    run_import(rows, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
