"""
Merge piped clients (Name | metadata) into their parent client.

Piped client names come from Uniqode tracking entries. The official name is
everything before the pipe. This script:
  1. Finds the real parent client by matching the name before |
  2. Uses market clues in the suffix to resolve multi-market parents
  3. Moves platform_ids, calls, orders from piped -> parent
  4. Deletes the piped client record

Usage:
  python setup/merge_piped_clients.py --dry-run   # Preview
  python setup/merge_piped_clients.py              # Run merge
"""

import sys
import os
import re
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Special cases where the parsed parent name doesn't exactly match the real client
PARENT_NAME_FIXES = {
    "Optimum Construction & Roofing Inc (s": "Optimum Construction & Roofing Inc (s)",
}

# Market clues in the suffix portion after the pipe
# Order matters — check specific zones before broad market codes
MARKET_CLUES = [
    # Colorado zones/keywords
    ("EPC", "CO"), ("NoCO", "CO"), ("NCO", "CO"), ("NDN", "CO"), ("SDN", "CO"),
    ("NOCO", "CO"), ("North Denver", "CO"), ("South Denver", "CO"),
    ("Denver", "CO"), ("Springs", "CO"), ("CO ", "CO"), ("CO\n", "CO"),
    # Utah zones/keywords
    ("CW", "UT"), ("NW", "UT"), ("SW", "UT"), ("SLC", "UT"),
    ("Wasatch", "UT"), ("UT ", "UT"), ("UT\n", "UT"), ("Utah", "UT"),
    ("Ogden", "UT"),
    # Austin
    ("Austin", "AU"), ("AU ", "AU"),
    # San Antonio
    ("SA ", "SA"), ("San Antonio", "SA"),
]


def detect_market_from_suffix(suffix):
    """Try to determine market code from the pipe suffix."""
    if not suffix:
        return None
    for clue, market in MARKET_CLUES:
        if clue in suffix:
            return market
    return None


def detect_market_from_full_name(full_name):
    """Fallback: check the full piped name for market clues."""
    return detect_market_from_suffix(full_name)


def run(dry_run=True):
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

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

    # Load markets
    markets = sb.table("markets").select("id,code").execute()
    market_id_to_code = {m["id"]: m["code"] for m in markets.data}
    market_code_to_id = {m["code"]: m["id"] for m in markets.data}

    # Separate piped and non-piped clients
    piped = []
    non_piped = {}  # name -> list of client records (multiple if multi-market)
    for c in all_clients:
        if "|" in c["name"]:
            piped.append(c)
        else:
            non_piped.setdefault(c["name"], []).append(c)

    # Also build case-insensitive lookup
    non_piped_lower = {}
    for name, records in non_piped.items():
        non_piped_lower.setdefault(name.lower().strip(), []).extend(records)

    print(f"  {len(piped)} piped clients to merge")
    print(f"  {len(non_piped)} unique non-piped client names")

    # Process each piped client
    merged = 0
    created_parents = 0
    skipped = []
    merge_plan = []  # (piped_id, piped_name, parent_id, parent_name, reason)

    for pc in piped:
        parts = pc["name"].split("|", 1)
        parent_name = parts[0].strip()
        suffix = parts[1].strip() if len(parts) > 1 else ""

        # Apply name fixes for known edge cases
        if parent_name in PARENT_NAME_FIXES:
            parent_name = PARENT_NAME_FIXES[parent_name]

        # Find parent candidates (case-insensitive)
        candidates = non_piped_lower.get(parent_name.lower().strip(), [])

        if len(candidates) == 0:
            # No parent exists — need to create one or skip
            # Detect market from suffix
            market_code = detect_market_from_suffix(suffix) or detect_market_from_full_name(pc["name"])
            market_id = market_code_to_id.get(market_code) if market_code else None

            if dry_run:
                print(f"  CREATE: '{parent_name}' (market={market_code or '?'}) for '{pc['name']}'")
                # Track for dry run reporting
                merge_plan.append((pc["id"], pc["name"], None, f"NEW: {parent_name}", f"market={market_code}"))
                created_parents += 1
                merged += 1
            else:
                insert_data = {"name": parent_name}
                if market_id:
                    insert_data["primary_market_id"] = market_id
                result = sb.table("clients").insert(insert_data).execute()
                new_parent = result.data[0]
                # Add to lookup so subsequent piped clients find it
                non_piped.setdefault(parent_name, []).append(new_parent)
                non_piped_lower.setdefault(parent_name.lower().strip(), []).append(new_parent)
                merge_plan.append((pc["id"], pc["name"], new_parent["id"], parent_name, "created"))
                created_parents += 1
                merged += 1

        elif len(candidates) == 1:
            # Single parent — straightforward merge
            parent = candidates[0]
            merge_plan.append((pc["id"], pc["name"], parent["id"], parent["name"], "exact"))
            merged += 1

        else:
            # Multiple candidates (same name, different markets)
            market_code = detect_market_from_suffix(suffix) or detect_market_from_full_name(pc["name"])
            if market_code:
                # Find the one matching the detected market
                match = None
                for cand in candidates:
                    cand_market = market_id_to_code.get(cand.get("primary_market_id"))
                    if cand_market == market_code:
                        match = cand
                        break
                if match:
                    merge_plan.append((pc["id"], pc["name"], match["id"], match["name"], f"market={market_code}"))
                    merged += 1
                else:
                    skipped.append((pc["name"], f"market {market_code} detected but no candidate matches"))
            else:
                skipped.append((pc["name"], f"{len(candidates)} candidates, can't determine market from suffix"))

    print(f"\n{'='*60}")
    print(f"  MERGE PLAN")
    print(f"{'='*60}")
    print(f"  Will merge:     {merged}")
    print(f"  Parents created: {created_parents}")
    print(f"  Skipped:         {len(skipped)}")
    print(f"{'='*60}")

    if skipped:
        print(f"\n  SKIPPED ({len(skipped)}):")
        for name, reason in skipped:
            print(f"    {name[:60]:60s} — {reason}")

    if dry_run:
        print(f"\n  DRY RUN — no changes made.")

        # Show summary of what would happen
        calls_to_move = 0
        pids_to_move = 0
        orders_to_move = 0
        piped_ids = [mp[0] for mp in merge_plan]

        # Count in batches
        for i in range(0, len(piped_ids), 50):
            batch_ids = piped_ids[i:i+50]
            r = sb.table("calls").select("id", count="exact").in_("client_id", batch_ids).execute()
            calls_to_move += r.count
            r = sb.table("client_platform_ids").select("id", count="exact").in_("client_id", batch_ids).execute()
            pids_to_move += r.count
            r = sb.table("orders").select("id", count="exact").in_("client_id", batch_ids).execute()
            orders_to_move += r.count

        print(f"\n  Would reassign:")
        print(f"    {calls_to_move} calls")
        print(f"    {pids_to_move} platform_ids")
        print(f"    {orders_to_move} orders")
        return

    # Execute merges
    print(f"\nExecuting merges...")
    for i, (piped_id, piped_name, parent_id, parent_name, reason) in enumerate(merge_plan):
        if parent_id is None:
            continue  # Should have been created above already

        # Move platform_ids (skip duplicates)
        try:
            sb.table("client_platform_ids").update(
                {"client_id": parent_id}
            ).eq("client_id", piped_id).execute()
        except Exception as e:
            if "duplicate" in str(e).lower() or "23505" in str(e):
                # Delete the duplicate piped ones instead
                sb.table("client_platform_ids").delete().eq("client_id", piped_id).execute()
            else:
                print(f"  WARNING platform_ids: {piped_name}: {str(e)[:80]}")

        # Move calls
        sb.table("calls").update({"client_id": parent_id}).eq("client_id", piped_id).execute()

        # Move orders
        sb.table("orders").update({"client_id": parent_id}).eq("client_id", piped_id).execute()

        # Delete client_zones for piped client
        sb.table("client_zones").delete().eq("client_id", piped_id).execute()

        # Delete client_notes for piped client
        sb.table("client_notes").delete().eq("client_id", piped_id).execute()

        # Delete the piped client
        sb.table("clients").delete().eq("id", piped_id).execute()

        if (i + 1) % 50 == 0:
            print(f"  ... {i + 1}/{len(merge_plan)} merged")

    print(f"\n{'='*60}")
    print(f"  MERGE COMPLETE")
    print(f"{'='*60}")
    print(f"  Merged:          {merged}")
    print(f"  Parents created: {created_parents}")
    print(f"  Skipped:         {len(skipped)}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="Merge piped clients into parent clients")
    parser.add_argument("--dry-run", action="store_true", help="Preview only")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: Missing env vars")
        sys.exit(1)

    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
