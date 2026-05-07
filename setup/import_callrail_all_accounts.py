"""
Import CallRail calls from ALL accounts (UT, TX) into Supabase.

The main ETL only pulls from one account. This script pulls historical data
from the Utah and Austin/San Antonio accounts.

Usage:
  python setup/import_callrail_all_accounts.py --dry-run
  python setup/import_callrail_all_accounts.py
"""

import sys
import os
import argparse
import time
from pathlib import Path
from datetime import datetime, timezone

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CALLRAIL_API_KEY = os.getenv("CALLRAIL_API_KEY")

CALLRAIL_BASE_URL = "https://api.callrail.com/v3"

# Anstel test line
EXCLUDED_NUMBERS = {"3032204242"}

# Accounts to import (excluding Colorado which is already imported)
ACCOUNTS = [
    ("ACCb1f04de7a28941f4827eb25f18d5e810", "TheHomeMag Utah"),
    ("ACC60a4cf8cf0514a45acfde9c07fa1275b", "TheHomeMag Austin & San Antonio"),
]

# Date ranges to pull (chunked to avoid API issues)
DATE_RANGES = [
    ("2024-06-01", "2024-09-30"),
    ("2024-10-01", "2024-12-31"),
    ("2025-01-01", "2025-03-31"),
    ("2025-04-01", "2025-06-30"),
    ("2025-07-01", "2025-09-30"),
    ("2025-10-01", "2025-12-31"),
    ("2026-01-01", "2026-04-09"),
]

EXTRA_FIELDS = "company_id,company_name,campaign,call_summary,recording,first_call"
PER_PAGE = 250


def callrail_headers():
    return {"Authorization": f"Token token=\"{CALLRAIL_API_KEY}\""}


def strip_phone(number):
    if not number:
        return ""
    return "".join(c for c in number if c.isdigit())


def fetch_calls(account_id, start_date, end_date):
    """Fetch all calls for an account in a date range."""
    next_url = f"{CALLRAIL_BASE_URL}/a/{account_id}/calls.json"
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "per_page": PER_PAGE,
        "fields": EXTRA_FIELDS,
        "relative_pagination": "true",
    }

    all_calls = []
    while next_url:
        resp = requests.get(next_url, headers=callrail_headers(), params=params)

        if resp.status_code == 429:
            print("    Rate limited — waiting 10s...")
            time.sleep(10)
            continue

        resp.raise_for_status()
        data = resp.json()

        calls = data.get("calls", [])
        if not calls:
            break

        all_calls.extend(calls)

        if not data.get("has_next_page", False):
            break

        next_url = data.get("next_page")
        params = None

    return all_calls


def transform_call(call, company_map):
    """Transform a CallRail call into a Supabase row."""
    caller_number = strip_phone(call.get("customer_phone_number", ""))
    if caller_number in EXCLUDED_NUMBERS:
        return None

    callrail_id = str(call.get("id", ""))
    if not callrail_id:
        return None

    duration = call.get("duration", 0) or 0
    answered = call.get("answered", False)
    company_id = str(call.get("company_id", "")) if call.get("company_id") else None

    client_id = company_map.get(company_id) if company_id else None

    row = {
        "callrail_id": callrail_id,
        "callrail_company_id": company_id,
        "client_id": client_id,
        "call_time": call.get("start_time"),
        "duration_seconds": duration,
        "is_missed": not answered,
        "is_first_time": call.get("first_call", False) or False,
        "caller_number": call.get("customer_phone_number"),
        "caller_name": call.get("customer_name"),
        "caller_city": call.get("customer_city"),
        "caller_state": call.get("customer_state"),
        "tracking_number": call.get("tracking_phone_number"),
        "source": call.get("source"),
        "campaign": call.get("campaign"),
        "voicemail": call.get("voicemail", False) or False,
        "recording_url": call.get("recording"),
    }

    summary = call.get("call_summary")
    if summary:
        row["has_transcript"] = True
        row["transcript_summary"] = summary
    else:
        row["has_transcript"] = False

    return row


def run(dry_run=False):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Build company -> client mapping from platform IDs
    print("Loading company-to-client mapping...")
    result = (
        sb.table("client_platform_ids")
        .select("client_id,external_id")
        .eq("platform", "callrail")
        .execute()
    )
    company_map = {row["external_id"]: row["client_id"] for row in result.data}
    print(f"  {len(company_map)} CallRail companies mapped")

    grand_total = 0
    grand_unmatched = 0

    for account_id, account_name in ACCOUNTS:
        print(f"\n{'='*50}")
        print(f"  {account_name} ({account_id})")
        print(f"{'='*50}")

        account_total = 0
        account_unmatched = 0

        for start, end in DATE_RANGES:
            print(f"\n  Fetching {start} to {end}...")
            raw_calls = fetch_calls(account_id, start, end)
            print(f"    {len(raw_calls)} calls from API")

            rows = []
            skipped = 0
            unmatched = 0
            for call in raw_calls:
                row = transform_call(call, company_map)
                if row is None:
                    skipped += 1
                    continue
                if row["client_id"] is None:
                    unmatched += 1
                rows.append(row)

            print(f"    {len(rows)} to upsert, {skipped} excluded, {unmatched} unmatched")

            if dry_run:
                print("    DRY RUN — skipping upsert")
            elif rows:
                BATCH_SIZE = 100
                for i in range(0, len(rows), BATCH_SIZE):
                    batch = rows[i:i + BATCH_SIZE]
                    sb.table("calls").upsert(batch, on_conflict="callrail_id").execute()
                print(f"    Upserted {len(rows)} calls")

            account_total += len(rows)
            account_unmatched += unmatched

        print(f"\n  {account_name} total: {account_total} calls ({account_unmatched} unmatched)")
        grand_total += account_total
        grand_unmatched += account_unmatched

    print(f"\n{'='*50}")
    print(f"  ALL ACCOUNTS COMPLETE")
    print(f"  Total calls imported: {grand_total}")
    print(f"  Unmatched to client:  {grand_unmatched}")
    print(f"{'='*50}\n")


def main():
    parser = argparse.ArgumentParser(description="Import CallRail calls from all accounts")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not all([SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY]):
        print("ERROR: Missing env vars (SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY)")
        sys.exit(1)

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
