"""
Split multi-market clients into separate per-market client records.

For clients that have data spanning multiple markets but should be separate
businesses (e.g., Apex Clean Air CO vs Apex Clean Air UT), this script:
  1. Classifies each platform_id by its market (using ID prefixes, names, CallRail API)
  2. Creates a new client record for the secondary market(s)
  3. Reassigns platform_ids, calls, qr_scans, orders, and client_zones
  4. Leaves the original record holding only its primary market data

Usage:
  python setup/split_multi_market_clients.py --dry-run
  python setup/split_multi_market_clients.py
"""

import sys
import os
import re
import argparse
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CALLRAIL_API_KEY = os.getenv("CALLRAIL_API_KEY")

# Clients to split: (client_id, label, primary_market_to_keep, market_to_extract, [existing_target_id])
# The original record will keep `primary_market`. A new record is created for `extract_market`,
# UNLESS a 5th element is provided — then that existing client receives the extracted data.
CLIENTS_TO_SPLIT = [
    ("0460ad3c-73c0-4a34-88df-81807898825b", "Apex Clean Air", "CO", "UT", None),
    ("1b48db9e-2abb-48e6-aa90-dac45f2f9df9", "Handyman Hub", "CO", "UT", None),
    ("253d62b7-07e0-47f2-a247-731be37427c0", "Closet Factory", "CO", "UT", None),
    ("db290508-f8f3-4424-a09a-acfeedd5ea24", "3 Day Blinds c/o Incremental Media, Inc", "CO", "UT", None),
    ("02140bd6-8cdb-4be1-b931-27f6f03a0cfd", "Nationwide Expos", "CO", "UT", None),
    # Elkstone has a case-difference duplicate UT record - merge into it instead of creating new
    ("5ae4ec8c-f2fe-4715-9ecb-b26a7da18964", "Elkstone Basements", "CO", "UT", "0c449c7d-1852-4ba4-b211-a81b158fa00a"),
]

# CallRail account IDs by market
CALLRAIL_ACCOUNTS = {
    "CO": "ACCe42c98d3446c4dc898467150060f870c",
    "UT": "ACCb1f04de7a28941f4827eb25f18d5e810",
    # AU + SA share an account - not relevant for the CO/UT splits
}

# Uniqode name keywords -> market (matched as whole words via \b boundaries)
UNIQODE_KEYWORDS = {
    "CO": ["co", "noco", "epc", "denver", "colorado", "ndn", "sdn", "nco", "sco",
           "boulder", "littleton", "fort collins", "loveland", "greeley", "longmont",
           "castle rock", "co springs"],
    "UT": ["ut", "utah", "wasatch", "slc", "salt lake", "ogden", "provo", "sandy", "draper",
           "kaysville", "layton", "logan", "orem", "springville", "herriman", "cw", "nw", "sw"],
}


def name_matches_market(name, market):
    """Whole-word match for any keyword for the given market."""
    if not name:
        return False
    name_lower = name.lower()
    for kw in UNIQODE_KEYWORDS.get(market, []):
        if re.search(r'\b' + re.escape(kw) + r'\b', name_lower):
            return True
    return False


def infer_market_from_caller_states(sb, callrail_company_id):
    """For a callrail company that's not in the API anymore, infer market from caller states."""
    result = sb.table("calls").select("caller_state").eq("callrail_company_id", callrail_company_id).limit(500).execute()
    states = {}
    for r in result.data:
        s = (r.get("caller_state") or "").upper()
        if s in ("CO", "COLORADO"):
            states["CO"] = states.get("CO", 0) + 1
        elif s in ("UT", "UTAH"):
            states["UT"] = states.get("UT", 0) + 1
    if not states:
        return None
    # Return the dominant state
    co_count = states.get("CO", 0)
    ut_count = states.get("UT", 0)
    if co_count > ut_count * 2:
        return "CO"
    if ut_count > co_count * 2:
        return "UT"
    return None  # too close to call


def fetch_callrail_company_to_account():
    """Build a map of callrail company_id -> 'CO' or 'UT' by querying both accounts."""
    print("Fetching CallRail company lists from CO and UT accounts...")
    company_to_account = {}
    for market, acct_id in CALLRAIL_ACCOUNTS.items():
        url = f"https://api.callrail.com/v3/a/{acct_id}/companies.json"
        params = {"per_page": 250}
        while url:
            resp = requests.get(url, headers={"Authorization": f'Token token="{CALLRAIL_API_KEY}"'}, params=params)
            resp.raise_for_status()
            data = resp.json()
            for co in data.get("companies", []):
                company_to_account[co["id"]] = market
            if not data.get("has_next_page"):
                break
            url = data.get("next_page")
            params = None
    print(f"  {len(company_to_account)} CallRail companies mapped to accounts")
    return company_to_account


def classify_platform_id(sb, platform, external_id, external_name, callrail_map, primary, extract):
    """Return 'CO', 'UT', or None (None = leave on primary)."""
    if platform == "magazine_manager":
        if f"MM-{extract}-" in external_id:
            return extract
        if f"MM-{primary}-" in external_id:
            return primary
        return None

    if platform == "inbox_advantage":
        if f"IA-{extract}-" in external_id:
            return extract
        if f"IA-{primary}-" in external_id:
            return primary
        return None

    if platform == "uniqode":
        # Check extract market first (more specific clues like UT/Wasatch beat CO)
        if name_matches_market(external_name, extract):
            return extract
        if name_matches_market(external_name, primary):
            return primary
        return None  # ambiguous - leave on primary

    if platform == "callrail":
        # First try the API map
        market = callrail_map.get(external_id)
        if market:
            return market
        # Then try the external_name for market clues
        if name_matches_market(external_name, extract):
            return extract
        if name_matches_market(external_name, primary):
            return primary
        # Last resort: infer from caller states in our calls data
        return infer_market_from_caller_states(sb, external_id)

    return None


def run(dry_run=True):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Build CallRail company -> account map
    callrail_map = fetch_callrail_company_to_account()

    # Load markets
    markets = sb.table("markets").select("id,code").execute()
    market_code_to_id = {m["code"]: m["id"] for m in markets.data}

    print(f"\n{'='*70}")
    for client_id, client_name, primary_mkt, extract_mkt, target_existing_id in CLIENTS_TO_SPLIT:
        action = f"merge into existing {target_existing_id[:8]}..." if target_existing_id else f"create new {extract_mkt} client"
        print(f"\n{client_name} ({primary_mkt} -> keep, {extract_mkt} -> {action})")
        print(f"{'-'*70}")

        # Load platform_ids
        result = sb.table("client_platform_ids").select("*").eq("client_id", client_id).execute()
        platform_ids = result.data

        # Classify each
        to_extract = []
        to_keep = []
        ambiguous = []

        for pid in platform_ids:
            market = classify_platform_id(
                sb, pid["platform"], pid["external_id"], pid.get("external_name"),
                callrail_map, primary_mkt, extract_mkt
            )
            if market == extract_mkt:
                to_extract.append(pid)
            elif market == primary_mkt:
                to_keep.append(pid)
            else:
                ambiguous.append(pid)

        # Show classification
        print(f"  Platform IDs: {len(platform_ids)} total")
        print(f"    -> {extract_mkt} (extract): {len(to_extract)}")
        print(f"    -> {primary_mkt} (keep): {len(to_keep)}")
        print(f"    -> ambiguous (default to {primary_mkt}): {len(ambiguous)}")

        if to_extract:
            print(f"\n  Will move to new {extract_mkt} client:")
            for p in to_extract:
                print(f"    [{p['platform']:18s}] {p['external_id'][:40]:40s} {(p.get('external_name') or '')[:50]}")

        if ambiguous:
            print(f"\n  Ambiguous (will stay on {primary_mkt}):")
            for p in ambiguous:
                print(f"    [{p['platform']:18s}] {p['external_id'][:40]:40s} {(p.get('external_name') or '')[:50]}")

        # Count downstream impact
        extract_external_ids = [p["external_id"] for p in to_extract]
        callrail_company_ids = [p["external_id"] for p in to_extract if p["platform"] == "callrail"]
        uniqode_qr_ids = [p["external_id"].replace("UQ-XX-", "") for p in to_extract if p["platform"] == "uniqode"]

        # Calls to move
        calls_to_move = 0
        if callrail_company_ids:
            for batch_start in range(0, len(callrail_company_ids), 100):
                batch = callrail_company_ids[batch_start:batch_start+100]
                r = sb.table("calls").select("id", count="exact").eq("client_id", client_id).in_("callrail_company_id", batch).execute()
                calls_to_move += r.count

        # QR scans to move
        scans_to_move = 0
        if uniqode_qr_ids:
            for batch_start in range(0, len(uniqode_qr_ids), 100):
                batch = uniqode_qr_ids[batch_start:batch_start+100]
                r = sb.table("qr_scans").select("id", count="exact").eq("client_id", client_id).in_("qr_code_id", batch).execute()
                scans_to_move += r.count

        # Orders to move (by market_id)
        r = sb.table("orders").select("id", count="exact").eq("client_id", client_id).eq("market_id", market_code_to_id[extract_mkt]).execute()
        orders_to_move = r.count

        print(f"\n  Will move to new {extract_mkt} client:")
        print(f"    {len(to_extract)} platform_ids")
        print(f"    {calls_to_move} calls")
        print(f"    {scans_to_move} qr_scans")
        print(f"    {orders_to_move} orders")

        if dry_run:
            continue

        # Execute the split
        if target_existing_id:
            print(f"\n  Using existing {extract_mkt} client {target_existing_id}...")
            new_client_id = target_existing_id
            # Rename the existing target to match the canonical name (in case of case difference)
            orig = sb.table("clients").select("*").eq("id", client_id).single().execute().data
            sb.table("clients").update({"name": orig["name"]}).eq("id", target_existing_id).execute()
        else:
            print(f"\n  Creating new {extract_mkt} client...")
            orig = sb.table("clients").select("*").eq("id", client_id).single().execute().data
            new_client_data = {
                "name": orig["name"],
                "display_name": orig.get("display_name"),
                "category": orig.get("category"),
                "subcategory": orig.get("subcategory"),
                "status": orig.get("status", "active"),
                "primary_market_id": market_code_to_id[extract_mkt],
            }
            new_client_result = sb.table("clients").insert(new_client_data).execute()
            new_client_id = new_client_result.data[0]["id"]
            print(f"    Created client {new_client_id}")

        # Update primary client to ensure it has the right primary_market
        sb.table("clients").update({
            "primary_market_id": market_code_to_id[primary_mkt]
        }).eq("id", client_id).execute()

        # Move platform_ids
        for p in to_extract:
            sb.table("client_platform_ids").update({"client_id": new_client_id}).eq("id", p["id"]).execute()

        # Move calls (by callrail_company_id)
        if callrail_company_ids:
            for batch_start in range(0, len(callrail_company_ids), 100):
                batch = callrail_company_ids[batch_start:batch_start+100]
                sb.table("calls").update({"client_id": new_client_id}).eq("client_id", client_id).in_("callrail_company_id", batch).execute()

        # Move qr_scans (by qr_code_id)
        if uniqode_qr_ids:
            for batch_start in range(0, len(uniqode_qr_ids), 100):
                batch = uniqode_qr_ids[batch_start:batch_start+100]
                sb.table("qr_scans").update({"client_id": new_client_id}).eq("client_id", client_id).in_("qr_code_id", batch).execute()

        # Move orders (by market_id)
        sb.table("orders").update({"client_id": new_client_id}).eq("client_id", client_id).eq("market_id", market_code_to_id[extract_mkt]).execute()

        # Move client_zones for zones in the extract market
        zones_in_extract = sb.table("zones").select("id").eq("market_id", market_code_to_id[extract_mkt]).execute()
        zone_ids = [z["id"] for z in zones_in_extract.data]
        if zone_ids:
            sb.table("client_zones").update({"client_id": new_client_id}).eq("client_id", client_id).in_("zone_id", zone_ids).execute()

        print(f"  Split complete")

    print(f"\n{'='*70}")
    if dry_run:
        print("  DRY RUN — no changes made")
    else:
        print("  ALL SPLITS COMPLETE")
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Split multi-market clients")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not all([SUPABASE_URL, SUPABASE_KEY, CALLRAIL_API_KEY]):
        print("ERROR: Missing env vars")
        sys.exit(1)

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
