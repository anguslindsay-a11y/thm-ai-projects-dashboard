"""
Backfill tracking_number_name and zone_id on existing calls.

Pulls all trackers (tracking numbers) from each CallRail account,
builds a phone -> name mapping, then updates calls in Supabase.

Usage:
  python setup/backfill_tracker_names.py --dry-run
  python setup/backfill_tracker_names.py
"""

import sys
import os
import argparse
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CALLRAIL_API_KEY = os.getenv("CALLRAIL_API_KEY")

CALLRAIL_BASE_URL = "https://api.callrail.com/v3"
PER_PAGE = 250

CALLRAIL_ACCOUNTS = [
    ("ACCe42c98d3446c4dc898467150060f870c", "CO"),
    ("ACCb1f04de7a28941f4827eb25f18d5e810", "UT"),
    ("ACC60a4cf8cf0514a45acfde9c07fa1275b", "TX"),
]

# Zone parsing: account-aware since "North"/"South" means different things per market
# CO: North = ND, South = SD, NOCO, EPC
# UT: North = NW, South = SW, Central/SLC = CW
# TX: Austin = AN/AS, San Antonio = SAE/SAW
ZONE_PATTERNS_BY_ACCOUNT = {
    "CO": [
        ("noco", "NOCO"), ("northern co", "NOCO"),
        ("north denver", "ND"), ("ndn", "ND"), ("- nd ", "ND"),
        ("south denver", "SD"), ("sdn", "SD"), ("- sd ", "SD"),
        ("epc", "EPC"), ("co springs", "EPC"), ("colorado springs", "EPC"),
        ("- north", "ND"), ("- south", "SD"),  # CO default: North=ND, South=SD
    ],
    "UT": [
        ("- north", "NW"), ("north wasatch", "NW"), ("- nw", "NW"),
        ("weber", "NW"), ("davis", "NW"), ("ogden", "NW"),
        ("- south", "SW"), ("south wasatch", "SW"), ("- sw", "SW"),
        ("- central", "CW"), ("central wasatch", "CW"), ("- cw", "CW"),
        ("slc", "CW"), ("salt lake", "CW"),
    ],
    "TX": [
        ("au north", "AN"), ("austin n", "AN"),
        ("au south", "AS"), ("austin s", "AS"),
        ("austin", "AN"),  # default Austin = AN (most clients)
        ("sa east", "SAE"), ("san antonio e", "SAE"),
        ("sa west", "SAW"), ("san antonio w", "SAW"),
        ("san antonio", "SAE"),  # default SA = SAE
    ],
}


def headers():
    return {"Authorization": f'Token token="{CALLRAIL_API_KEY}"'}


def strip_phone(number):
    if not number:
        return ""
    return "".join(c for c in str(number) if c.isdigit())[-10:]  # last 10 digits


def parse_zone_for_account(tracker_name, account_code):
    """Parse zone from tracker name, using account-specific patterns."""
    if not tracker_name:
        return None
    name_lower = f" {tracker_name.lower().strip()} "  # pad for boundary matching
    patterns = ZONE_PATTERNS_BY_ACCOUNT.get(account_code, [])
    for pattern, zone in patterns:
        if pattern in name_lower:
            return zone
    return None


def fetch_all_trackers(account_id):
    """Fetch all tracking numbers from a CallRail account."""
    trackers = []
    page = 1
    while True:
        url = f"{CALLRAIL_BASE_URL}/a/{account_id}/trackers.json"
        resp = requests.get(url, headers=headers(), params={"per_page": PER_PAGE, "page": page, "status": "all"})
        if resp.status_code == 429:
            print("  Rate limited, waiting 10s...")
            time.sleep(10)
            continue
        resp.raise_for_status()
        data = resp.json()
        trackers.extend(data.get("trackers", []))
        total_pages = data.get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1
    return trackers


def run(dry_run=True):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load zone lookup
    zones_result = sb.table("zones").select("id,abbreviation").execute()
    zone_lookup = {z["abbreviation"]: z["id"] for z in zones_result.data if z.get("abbreviation")}
    print(f"Loaded {len(zone_lookup)} zones")

    # Pull all trackers and build phone -> (name, zone) mapping
    print("\nFetching trackers from CallRail...")
    phone_to_info = {}  # last 10 digits -> (name, zone_abbrev)

    for acct_id, acct_code in CALLRAIL_ACCOUNTS:
        print(f"\n  {acct_code} ({acct_id}):")
        trackers = fetch_all_trackers(acct_id)
        print(f"    {len(trackers)} trackers fetched")

        acct_mapped = 0
        for t in trackers:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            zone = parse_zone_for_account(name, acct_code)
            for num in t.get("tracking_numbers", []):
                phone = strip_phone(num)
                if phone:
                    phone_to_info[phone] = (name, zone)
                    acct_mapped += 1
        print(f"    {acct_mapped} phone numbers mapped")

    total_phones = len(phone_to_info)
    zoned = sum(1 for _, z in phone_to_info.values() if z)
    print(f"\nTotal: {total_phones} phone->name mappings, {zoned} with zone")

    # Zone distribution
    zone_counts = {}
    for _, (name, zone) in phone_to_info.items():
        if zone:
            zone_counts[zone] = zone_counts.get(zone, 0) + 1
    print("\nZone distribution:")
    for z in sorted(zone_counts):
        print(f"  {z}: {zone_counts[z]} numbers")

    if dry_run:
        print(f"\nSample mappings (first 20):")
        for phone, (name, zone) in list(phone_to_info.items())[:20]:
            print(f"  ...{phone[-4:]} -> '{name}' -> {zone or '(none)'}")
        print("\nDRY RUN - no data written")
        return

    # Update calls in batches by tracking number
    print("\nUpdating calls...")
    total_updated = 0
    total_zoned = 0
    processed = 0

    for phone, (name, zone_abbrev) in phone_to_info.items():
        zone_id = zone_lookup.get(zone_abbrev) if zone_abbrev else None

        update_data = {"tracking_number_name": name}
        if zone_id:
            update_data["zone_id"] = zone_id

        try:
            # Match by last 10 digits of tracking_number
            result = sb.table("calls").update(update_data).like(
                "tracking_number", f"%{phone}"
            ).execute()
            count = len(result.data)
            if count > 0:
                total_updated += count
                if zone_id:
                    total_zoned += count
        except Exception as e:
            if "0 rows" not in str(e):
                print(f"  Error on ...{phone[-4:]}: {str(e)[:80]}")

        processed += 1
        if processed % 100 == 0:
            print(f"  ... {processed}/{total_phones} numbers, {total_updated} calls updated, {total_zoned} zoned")

    print(f"\n{'='*60}")
    print(f"  BACKFILL COMPLETE")
    print(f"  Phone numbers processed: {processed}")
    print(f"  Calls updated with name: {total_updated}")
    print(f"  Calls assigned zone:     {total_zoned}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not all([SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY]):
        print("ERROR: Missing env vars")
        sys.exit(1)

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
