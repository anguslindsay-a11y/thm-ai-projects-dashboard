"""
Import CallRail tags and link them to existing calls.

Steps:
  1. Fetch all tags from each CallRail account (CO, UT, TX)
  2. Dedupe by normalized name (case-insensitive, trimmed)
  3. Insert into `tags` table
  4. Re-fetch all calls in date chunks with the `tags` field included
  5. Create `call_tags` rows linking calls to tags

Usage:
  python setup/import_callrail_tags.py --dry-run
  python setup/import_callrail_tags.py
  python setup/import_callrail_tags.py --tags-only        # only refresh tag catalog
  python setup/import_callrail_tags.py --calls-only       # only relink calls (assume tags loaded)
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
    ("ACCe42c98d3446c4dc898467150060f870c", "Colorado"),
    ("ACCb1f04de7a28941f4827eb25f18d5e810", "Utah"),
    ("ACC60a4cf8cf0514a45acfde9c07fa1275b", "Austin & San Antonio"),
]

# Pull calls from these date ranges (matches our existing data start dates)
DATE_RANGES = [
    ("2024-06-01", "2024-12-31"),
    ("2025-01-01", "2025-06-30"),
    ("2025-07-01", "2025-12-31"),
    ("2026-01-01", "2026-04-09"),
]


def headers():
    return {"Authorization": f'Token token="{CALLRAIL_API_KEY}"'}


def normalize_tag_name(name):
    if not name:
        return None
    return name.strip()


def fetch_all_tags(account_id):
    """Fetch every tag in an account using page-based pagination."""
    tags = []
    url = f"{CALLRAIL_BASE_URL}/a/{account_id}/tags.json"
    page = 1
    while True:
        resp = requests.get(url, headers=headers(), params={"per_page": PER_PAGE, "page": page})
        if resp.status_code == 429:
            print("    rate limited, waiting 10s...")
            time.sleep(10)
            continue
        resp.raise_for_status()
        data = resp.json()
        tags.extend(data.get("tags", []))
        total_pages = data.get("total_pages", 1)
        if page >= total_pages:
            break
        page += 1
    return tags


def fetch_calls_with_tags(account_id, start_date, end_date):
    """Fetch calls in a date range, with tags field included."""
    calls = []
    url = f"{CALLRAIL_BASE_URL}/a/{account_id}/calls.json"
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "per_page": PER_PAGE,
        "fields": "tags",
        "relative_pagination": "true",
    }
    while url:
        resp = requests.get(url, headers=headers(), params=params)
        if resp.status_code == 429:
            print("    rate limited, waiting 10s...")
            time.sleep(10)
            continue
        resp.raise_for_status()
        data = resp.json()
        calls.extend(data.get("calls", []))
        if not data.get("has_next_page"):
            break
        url = data.get("next_page")
        params = None
    return calls


def import_tags(sb, dry_run):
    """Step 1: Fetch all tags from all accounts, dedupe by name, insert into tags table."""
    print("=" * 60)
    print("  STEP 1: Importing tag catalog")
    print("=" * 60)

    # Collect all tags from all accounts, indexed by normalized name
    name_to_tag = {}  # normalized_name -> {name, color, callrail_ids: [list]}

    for acct_id, acct_name in CALLRAIL_ACCOUNTS:
        print(f"\n  Fetching tags from {acct_name}...")
        tags = fetch_all_tags(acct_id)
        print(f"    {len(tags)} tags found")

        for t in tags:
            norm = normalize_tag_name(t.get("name"))
            if not norm:
                continue
            key = norm.lower()
            if key not in name_to_tag:
                name_to_tag[key] = {
                    "name": norm,
                    "color": t.get("background_color"),
                    "callrail_ids": [],
                }
            name_to_tag[key]["callrail_ids"].append(t["id"])

    print(f"\n  Total unique tag names: {len(name_to_tag)}")

    # Load existing tags from DB
    existing = sb.table("tags").select("id,name").execute()
    existing_by_name = {t["name"].lower(): t for t in existing.data}

    to_insert = []
    skipped_existing = 0
    for key, info in name_to_tag.items():
        if key in existing_by_name:
            skipped_existing += 1
            continue
        to_insert.append({"name": info["name"], "color": info["color"]})

    print(f"  Already in DB: {skipped_existing}")
    print(f"  To insert: {len(to_insert)}")

    if dry_run:
        print("  (dry-run, skipping insert)")
    elif to_insert:
        BATCH = 200
        for i in range(0, len(to_insert), BATCH):
            sb.table("tags").insert(to_insert[i:i+BATCH]).execute()
        print(f"  Inserted {len(to_insert)} tags")

    return name_to_tag


def build_callrail_tag_map(sb, name_to_tag):
    """Build a map: callrail_tag_id (int) -> our local tag uuid"""
    # Reload tags from DB to get UUIDs
    all_local_tags = []
    offset = 0
    while True:
        batch = sb.table("tags").select("id,name").range(offset, offset + 999).execute()
        all_local_tags.extend(batch.data)
        if len(batch.data) < 1000:
            break
        offset += 1000
    name_to_local_id = {t["name"].lower(): t["id"] for t in all_local_tags}

    callrail_to_local = {}
    for key, info in name_to_tag.items():
        local_id = name_to_local_id.get(key)
        if not local_id:
            continue
        for cr_id in info["callrail_ids"]:
            callrail_to_local[cr_id] = local_id
    return callrail_to_local


def import_call_tags(sb, callrail_to_local, dry_run):
    """Step 2: Fetch all calls with tags, create call_tags rows."""
    print("\n" + "=" * 60)
    print("  STEP 2: Linking tags to calls")
    print("=" * 60)

    # Load callrail_id -> local_call_id map
    print("\n  Loading existing calls map...")
    callrail_to_call_id = {}
    offset = 0
    while True:
        batch = sb.table("calls").select("id,callrail_id").range(offset, offset + 999).execute()
        for r in batch.data:
            if r.get("callrail_id"):
                callrail_to_call_id[r["callrail_id"]] = r["id"]
        if len(batch.data) < 1000:
            break
        offset += 1000
    print(f"  {len(callrail_to_call_id)} calls in DB")

    # Load existing call_tags to skip duplicates
    print("  Loading existing call_tags...")
    existing_pairs = set()
    offset = 0
    while True:
        batch = sb.table("call_tags").select("call_id,tag_id").range(offset, offset + 999).execute()
        for r in batch.data:
            existing_pairs.add((r["call_id"], r["tag_id"]))
        if len(batch.data) < 1000:
            break
        offset += 1000
    print(f"  {len(existing_pairs)} existing call_tag rows")

    grand_new = 0
    grand_skipped_no_call = 0
    grand_skipped_no_tag = 0

    for acct_id, acct_name in CALLRAIL_ACCOUNTS:
        print(f"\n  --- {acct_name} ---")
        for start, end in DATE_RANGES:
            print(f"  Fetching {start} to {end}...")
            calls = fetch_calls_with_tags(acct_id, start, end)
            print(f"    {len(calls)} calls returned")

            new_pairs = []
            skip_no_call = 0
            skip_no_tag = 0
            for call in calls:
                cr_id = call.get("id")
                local_call_id = callrail_to_call_id.get(cr_id)
                if not local_call_id:
                    skip_no_call += 1
                    continue
                tags = call.get("tags") or []
                for t in tags:
                    cr_tag_id = t.get("id")
                    local_tag_id = callrail_to_local.get(cr_tag_id)
                    if not local_tag_id:
                        skip_no_tag += 1
                        continue
                    pair = (local_call_id, local_tag_id)
                    if pair in existing_pairs:
                        continue
                    existing_pairs.add(pair)
                    new_pairs.append({
                        "call_id": local_call_id,
                        "tag_id": local_tag_id,
                        "callrail_tag_id": cr_tag_id,
                    })

            print(f"    new pairs: {len(new_pairs)}, skipped no_call: {skip_no_call}, skipped no_tag: {skip_no_tag}")
            grand_new += len(new_pairs)
            grand_skipped_no_call += skip_no_call
            grand_skipped_no_tag += skip_no_tag

            if dry_run:
                continue

            if new_pairs:
                BATCH = 500
                for i in range(0, len(new_pairs), BATCH):
                    sb.table("call_tags").insert(new_pairs[i:i+BATCH]).execute()

    print(f"\n  TOTAL new pairs: {grand_new}")
    print(f"  Skipped (call not in DB): {grand_skipped_no_call}")
    print(f"  Skipped (tag not in catalog): {grand_skipped_no_tag}")


def run(dry_run, tags_only, calls_only):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    name_to_tag = None
    if not calls_only:
        name_to_tag = import_tags(sb, dry_run)

    if tags_only:
        return

    if name_to_tag is None:
        # Calls-only mode: still need to fetch tag definitions to build the map
        print("Calls-only mode: re-fetching tag definitions for mapping...")
        name_to_tag = {}
        for acct_id, acct_name in CALLRAIL_ACCOUNTS:
            tags = fetch_all_tags(acct_id)
            for t in tags:
                norm = normalize_tag_name(t.get("name"))
                if not norm:
                    continue
                key = norm.lower()
                if key not in name_to_tag:
                    name_to_tag[key] = {"name": norm, "color": t.get("background_color"), "callrail_ids": []}
                name_to_tag[key]["callrail_ids"].append(t["id"])

    callrail_to_local = build_callrail_tag_map(sb, name_to_tag)
    print(f"\n  CallRail tag id -> local tag map: {len(callrail_to_local)} entries")

    import_call_tags(sb, callrail_to_local, dry_run)

    print("\n" + "=" * 60)
    if dry_run:
        print("  DRY RUN COMPLETE - no changes made")
    else:
        print("  IMPORT COMPLETE")
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--tags-only", action="store_true", help="Only refresh the tag catalog")
    parser.add_argument("--calls-only", action="store_true", help="Only relink calls (assumes tags exist)")
    args = parser.parse_args()

    if not all([SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY]):
        print("ERROR: Missing env vars")
        sys.exit(1)

    run(args.dry_run, args.tags_only, args.calls_only)


if __name__ == "__main__":
    main()
