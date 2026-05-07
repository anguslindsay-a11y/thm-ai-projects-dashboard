"""
Seed magazine_issues with the 2026 print schedules for CO, UT, AU, SA.

Source: Print Schedule PDFs uploaded 2026-04-29.
  - data/Print Schedule - CO 2026 (1).pdf
  - data/Print Schedule - UT 2026 (1).pdf
  - data/Print Schedule - TX 2026.pdf

Creates one row per zone × issue (13 issues × 11 zones = 143 rows).
All zones in a market share the same schedule (per the PDFs).

Idempotent — uses upsert on (zone_id, issue_code).

Issue codes match the format used in orders.issue_date:
  YYMM      = monthly issue (2601, 2602, ...)
  YYMMs     = special spring issue (2603s)

Usage:
  python setup/import_magazine_issues_2026.py
  python setup/import_magazine_issues_2026.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# Each market shares one schedule across its zones.
# Format: { market_code: [ {issue_code, issue_month, year, month, ad_deadline, payment_due, in_home}, ... ] }
SCHEDULES = {
    "CO": [
        {"issue_code": "2601",  "issue_month": "January",   "year": 2026, "month": 1,
         "ad_space_deadline": "2025-12-08", "payment_due": "2025-12-08", "in_home_date": "2026-01-08"},
        {"issue_code": "2602",  "issue_month": "February",  "year": 2026, "month": 2,
         "ad_space_deadline": "2026-01-19", "payment_due": "2026-01-12", "in_home_date": "2026-02-05"},
        {"issue_code": "2603",  "issue_month": "March",     "year": 2026, "month": 3,
         "ad_space_deadline": "2026-02-16", "payment_due": "2026-02-09", "in_home_date": "2026-03-05"},
        {"issue_code": "2603s", "issue_month": "Spring",    "year": 2026, "month": 3,
         "ad_space_deadline": "2026-03-09", "payment_due": "2026-03-02", "in_home_date": "2026-03-26"},
        {"issue_code": "2604",  "issue_month": "April",     "year": 2026, "month": 4,
         "ad_space_deadline": "2026-04-06", "payment_due": "2026-03-30", "in_home_date": "2026-04-23"},
        {"issue_code": "2605",  "issue_month": "May",       "year": 2026, "month": 5,
         "ad_space_deadline": "2026-05-04", "payment_due": "2026-04-27", "in_home_date": "2026-05-21"},
        {"issue_code": "2606",  "issue_month": "June",      "year": 2026, "month": 6,
         "ad_space_deadline": "2026-06-01", "payment_due": "2026-05-25", "in_home_date": "2026-06-18"},
        {"issue_code": "2607",  "issue_month": "July",      "year": 2026, "month": 7,
         "ad_space_deadline": "2026-06-29", "payment_due": "2026-06-22", "in_home_date": "2026-07-16"},
        {"issue_code": "2608",  "issue_month": "August",    "year": 2026, "month": 8,
         "ad_space_deadline": "2026-07-27", "payment_due": "2026-07-20", "in_home_date": "2026-08-13"},
        {"issue_code": "2609",  "issue_month": "September", "year": 2026, "month": 9,
         "ad_space_deadline": "2026-08-24", "payment_due": "2026-08-17", "in_home_date": "2026-09-10"},
        {"issue_code": "2610",  "issue_month": "October",   "year": 2026, "month": 10,
         "ad_space_deadline": "2026-09-21", "payment_due": "2026-09-14", "in_home_date": "2026-10-08"},
        {"issue_code": "2611",  "issue_month": "November",  "year": 2026, "month": 11,
         "ad_space_deadline": "2026-10-19", "payment_due": "2026-10-12", "in_home_date": "2026-11-05"},
        {"issue_code": "2612",  "issue_month": "December",  "year": 2026, "month": 12,
         "ad_space_deadline": "2026-11-16", "payment_due": "2026-11-09", "in_home_date": "2026-12-03"},
    ],
    "UT": [
        {"issue_code": "2601",  "issue_month": "January",   "year": 2026, "month": 1,
         "ad_space_deadline": "2025-12-15", "payment_due": "2025-12-15", "in_home_date": "2026-01-15"},
        {"issue_code": "2602",  "issue_month": "February",  "year": 2026, "month": 2,
         "ad_space_deadline": "2026-01-19", "payment_due": "2026-01-19", "in_home_date": "2026-02-12"},
        {"issue_code": "2603",  "issue_month": "March",     "year": 2026, "month": 3,
         "ad_space_deadline": "2026-02-16", "payment_due": "2026-02-16", "in_home_date": "2026-03-12"},
        {"issue_code": "2603s", "issue_month": "Spring",    "year": 2026, "month": 4,
         "ad_space_deadline": "2026-03-09", "payment_due": "2026-03-09", "in_home_date": "2026-04-02"},
        {"issue_code": "2604",  "issue_month": "April",     "year": 2026, "month": 4,
         "ad_space_deadline": "2026-04-06", "payment_due": "2026-04-06", "in_home_date": "2026-04-30"},
        {"issue_code": "2605",  "issue_month": "May",       "year": 2026, "month": 5,
         "ad_space_deadline": "2026-05-04", "payment_due": "2026-05-04", "in_home_date": "2026-05-28"},
        {"issue_code": "2606",  "issue_month": "June",      "year": 2026, "month": 6,
         "ad_space_deadline": "2026-06-01", "payment_due": "2026-06-01", "in_home_date": "2026-06-25"},
        {"issue_code": "2607",  "issue_month": "July",      "year": 2026, "month": 7,
         "ad_space_deadline": "2026-06-29", "payment_due": "2026-06-29", "in_home_date": "2026-07-23"},
        {"issue_code": "2608",  "issue_month": "August",    "year": 2026, "month": 8,
         "ad_space_deadline": "2026-07-27", "payment_due": "2026-07-27", "in_home_date": "2026-08-20"},
        {"issue_code": "2609",  "issue_month": "September", "year": 2026, "month": 9,
         "ad_space_deadline": "2026-08-24", "payment_due": "2026-08-24", "in_home_date": "2026-09-17"},
        {"issue_code": "2610",  "issue_month": "October",   "year": 2026, "month": 10,
         "ad_space_deadline": "2026-09-21", "payment_due": "2026-09-21", "in_home_date": "2026-10-15"},
        {"issue_code": "2611",  "issue_month": "November",  "year": 2026, "month": 11,
         "ad_space_deadline": "2026-10-19", "payment_due": "2026-10-19", "in_home_date": "2026-11-12"},
        {"issue_code": "2612",  "issue_month": "December",  "year": 2026, "month": 12,
         "ad_space_deadline": "2026-11-16", "payment_due": "2026-11-16", "in_home_date": "2026-12-10"},
    ],
    "TX": [   # AU + SA share the same schedule
        {"issue_code": "2601",  "issue_month": "January",   "year": 2026, "month": 1,
         "ad_space_deadline": "2025-12-10", "payment_due": "2025-12-08", "in_home_date": "2026-01-02"},
        {"issue_code": "2602",  "issue_month": "February",  "year": 2026, "month": 2,
         "ad_space_deadline": "2026-01-07", "payment_due": "2026-01-05", "in_home_date": "2026-01-29"},
        {"issue_code": "2603",  "issue_month": "March",     "year": 2026, "month": 3,
         "ad_space_deadline": "2026-02-04", "payment_due": "2026-02-02", "in_home_date": "2026-02-26"},
        {"issue_code": "2603s", "issue_month": "Spring",    "year": 2026, "month": 3,
         "ad_space_deadline": "2026-02-25", "payment_due": "2026-02-23", "in_home_date": "2026-03-19"},
        {"issue_code": "2604",  "issue_month": "April",     "year": 2026, "month": 4,
         "ad_space_deadline": "2026-03-25", "payment_due": "2026-03-23", "in_home_date": "2026-04-16"},
        {"issue_code": "2605",  "issue_month": "May",       "year": 2026, "month": 5,
         "ad_space_deadline": "2026-04-22", "payment_due": "2026-04-20", "in_home_date": "2026-05-14"},
        {"issue_code": "2606",  "issue_month": "June",      "year": 2026, "month": 6,
         "ad_space_deadline": "2026-05-20", "payment_due": "2026-05-18", "in_home_date": "2026-06-11"},
        {"issue_code": "2607",  "issue_month": "July",      "year": 2026, "month": 7,
         "ad_space_deadline": "2026-06-17", "payment_due": "2026-06-15", "in_home_date": "2026-07-09"},
        {"issue_code": "2608",  "issue_month": "August",    "year": 2026, "month": 8,
         "ad_space_deadline": "2026-07-15", "payment_due": "2026-07-13", "in_home_date": "2026-08-06"},
        {"issue_code": "2609",  "issue_month": "September", "year": 2026, "month": 9,
         "ad_space_deadline": "2026-08-12", "payment_due": "2026-08-10", "in_home_date": "2026-09-03"},
        {"issue_code": "2610",  "issue_month": "October",   "year": 2026, "month": 10,
         "ad_space_deadline": "2026-09-09", "payment_due": "2026-09-07", "in_home_date": "2026-10-01"},
        {"issue_code": "2611",  "issue_month": "November",  "year": 2026, "month": 11,
         "ad_space_deadline": "2026-10-07", "payment_due": "2026-10-05", "in_home_date": "2026-10-29"},
        {"issue_code": "2612",  "issue_month": "December",  "year": 2026, "month": 12,
         "ad_space_deadline": "2026-11-04", "payment_due": "2026-11-02", "in_home_date": "2026-11-26"},
    ],
}

# Which zones belong to which schedule.
MARKET_TO_ZONES = {
    "CO": ["NOCO", "ND", "SD", "EPC"],
    "UT": ["NW", "CW", "SW"],
    "TX": ["AN", "AS", "SAE", "SAW"],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Resolve zone abbreviations to ids
    zones = sb.table("zones").select("id,abbreviation").execute().data
    abbr_to_id = {z["abbreviation"]: z["id"] for z in zones}
    print(f"Loaded {len(abbr_to_id)} zones from DB")

    rows = []
    for market, zone_abbrs in MARKET_TO_ZONES.items():
        schedule = SCHEDULES[market]
        for abbr in zone_abbrs:
            zone_id = abbr_to_id.get(abbr)
            if not zone_id:
                print(f"  WARNING: zone {abbr} not in DB, skipping")
                continue
            for issue in schedule:
                rows.append({
                    "zone_id": zone_id,
                    "issue_code": issue["issue_code"],
                    "issue_month": issue["issue_month"],
                    "year": issue["year"],
                    "month": issue["month"],
                    "ad_space_deadline": issue["ad_space_deadline"],
                    "payment_due": issue["payment_due"],
                    "in_home_date": issue["in_home_date"],
                    "issue_date": issue["in_home_date"],  # default issue_date to delivery
                    "status": "planned",
                })

    print(f"\n{len(rows)} rows to upsert ({len(SCHEDULES)} markets × 13 issues × ~zones)")

    if args.dry_run:
        print("--dry-run: showing first 3:")
        for r in rows[:3]:
            print(f"  {r}")
        return

    # Upsert in chunks
    CHUNK = 100
    written = 0
    for i in range(0, len(rows), CHUNK):
        batch = rows[i:i + CHUNK]
        sb.table("magazine_issues").upsert(batch, on_conflict="zone_id,issue_code").execute()
        written += len(batch)
    print(f"  Upserted {written} rows")

    print("\nDone.")


if __name__ == "__main__":
    main()
