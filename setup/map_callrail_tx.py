"""
Map CallRail TX companies to Supabase clients.

Pulls all companies from the Austin & San Antonio CallRail account,
matches them against existing clients by name, and creates
client_platform_ids entries for matches.

Usage:
  python setup/map_callrail_tx.py --dry-run   # Preview matches
  python setup/map_callrail_tx.py              # Create mappings
"""

import sys
import os
import argparse
from pathlib import Path
from difflib import SequenceMatcher

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CALLRAIL_API_KEY = os.getenv("CALLRAIL_API_KEY")

TX_ACCOUNT_ID = "ACC60a4cf8cf0514a45acfde9c07fa1275b"
UT_ACCOUNT_ID = "ACCb1f04de7a28941f4827eb25f18d5e810"

# Skip internal/THM companies
SKIP_NAMES = {
    "The HomeMag - Mkt AU",
    "The HomeMag - Mkt SA",
    "TheHomeMag - Measuring Tape",
    "TheHomeMag Austin & San Antonio",
}


def normalize(name):
    """Normalize a name for matching."""
    n = name.lower().strip()
    # Remove common suffixes/prefixes
    for remove in [", llc", ", inc", " llc", " inc", " co.", " co"]:
        n = n.replace(remove, "")
    return n.strip()


def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def fetch_callrail_companies(account_id):
    """Fetch all companies from a CallRail account."""
    companies = []
    url = f"https://api.callrail.com/v3/a/{account_id}/companies.json"
    params = {"per_page": 250}

    while url:
        resp = requests.get(url, headers={"Authorization": f'Token token="{CALLRAIL_API_KEY}"'}, params=params)
        resp.raise_for_status()
        data = resp.json()
        companies.extend(data.get("companies", []))
        if not data.get("has_next_page", False):
            break
        url = data.get("next_page")
        params = None

    return companies


def run(dry_run=True):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load existing CallRail mappings
    existing = sb.table("client_platform_ids").select("external_id").eq("platform", "callrail").execute()
    mapped_ids = set(row["external_id"] for row in existing.data)

    # Load all clients
    print("Loading clients...")
    all_clients = []
    offset = 0
    while True:
        batch = sb.table("clients").select("id,name,primary_market_id").range(offset, offset + 999).execute()
        all_clients.extend(batch.data)
        if len(batch.data) < 1000:
            break
        offset += 1000

    # Build lookup by normalized name
    client_by_name = {}
    for c in all_clients:
        key = normalize(c["name"])
        client_by_name[key] = c

    # Fetch CallRail companies for TX
    print("Fetching TX CallRail companies...")
    tx_companies = fetch_callrail_companies(TX_ACCOUNT_ID)
    print(f"  {len(tx_companies)} companies in TX account")

    # Also fetch UT companies to check for unmapped ones
    print("Fetching UT CallRail companies...")
    ut_companies = fetch_callrail_companies(UT_ACCOUNT_ID)
    print(f"  {len(ut_companies)} companies in UT account")

    all_cr_companies = [("TX", c) for c in tx_companies] + [("UT", c) for c in ut_companies]

    exact_matches = []
    fuzzy_matches = []
    unmatched = []
    already_mapped = []

    for acct_label, co in all_cr_companies:
        cr_id = co["id"]
        cr_name = co["name"]

        if cr_name in SKIP_NAMES:
            continue

        if cr_id in mapped_ids:
            already_mapped.append((acct_label, cr_name, cr_id))
            continue

        norm = normalize(cr_name)

        # Exact match
        if norm in client_by_name:
            exact_matches.append((acct_label, cr_name, cr_id, client_by_name[norm]))
            continue

        # Fuzzy match - find best
        best_score = 0
        best_client = None
        for key, client in client_by_name.items():
            score = similarity(cr_name, client["name"])
            if score > best_score:
                best_score = score
                best_client = client

        if best_score >= 0.90:
            fuzzy_matches.append((acct_label, cr_name, cr_id, best_client, best_score))
        else:
            unmatched.append((acct_label, cr_name, cr_id, best_client, best_score))

    # Report
    print(f"\n{'='*70}")
    print(f"  MATCHING RESULTS")
    print(f"{'='*70}")
    print(f"  Already mapped:  {len(already_mapped)}")
    print(f"  Exact matches:   {len(exact_matches)}")
    print(f"  Fuzzy matches:   {len(fuzzy_matches)} (>=80% similarity)")
    print(f"  Unmatched:       {len(unmatched)}")
    print(f"{'='*70}")

    if exact_matches:
        print(f"\n  EXACT MATCHES ({len(exact_matches)}):")
        for acct, cr_name, cr_id, client in sorted(exact_matches, key=lambda x: x[1]):
            print(f"    [{acct}] {cr_name:45s} -> {client['name']}")

    if fuzzy_matches:
        print(f"\n  FUZZY MATCHES ({len(fuzzy_matches)}):")
        for acct, cr_name, cr_id, client, score in sorted(fuzzy_matches, key=lambda x: -x[4]):
            print(f"    [{acct}] {cr_name:45s} -> {client['name']:45s} ({score:.0%})")

    if unmatched:
        print(f"\n  UNMATCHED ({len(unmatched)}):")
        for acct, cr_name, cr_id, best, score in sorted(unmatched, key=lambda x: x[1]):
            best_name = best['name'] if best else '?'
            print(f"    [{acct}] {cr_name:45s}  (best: {best_name[:35]:35s} {score:.0%})")

    if dry_run:
        print(f"\n  DRY RUN — no mappings created.")
        print(f"  Would create {len(exact_matches)} exact + {len(fuzzy_matches)} fuzzy = {len(exact_matches) + len(fuzzy_matches)} mappings")
        return

    # Insert exact matches
    created = 0
    for acct, cr_name, cr_id, client in exact_matches:
        sb.table("client_platform_ids").insert({
            "client_id": client["id"],
            "platform": "callrail",
            "external_id": cr_id,
            "external_name": cr_name,
        }).execute()
        created += 1

    # Insert fuzzy matches
    for acct, cr_name, cr_id, client, score in fuzzy_matches:
        sb.table("client_platform_ids").insert({
            "client_id": client["id"],
            "platform": "callrail",
            "external_id": cr_id,
            "external_name": cr_name,
        }).execute()
        created += 1

    print(f"\n  Created {created} new CallRail mappings")


def main():
    parser = argparse.ArgumentParser(description="Map CallRail TX companies to clients")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not all([SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY]):
        print("ERROR: Missing env vars")
        sys.exit(1)

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
