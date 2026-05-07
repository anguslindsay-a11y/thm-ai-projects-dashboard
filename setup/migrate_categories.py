"""
Phase 2 — Migrate legacy clients.category text values to client_categories junction table.

Smart parsing: tries longest-match aliases FIRST so compound names like
"Concrete, Pavers & Driveways" are not naively split on the comma.

Idempotent — safe to re-run. Uses upsert semantics on (client_id, category_id).

Usage:
  python setup/migrate_categories.py
  python setup/migrate_categories.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def parse_legacy_value(value: str, alias_map: dict[str, str]) -> tuple[list[str], list[str]]:
    """
    Parse a legacy clients.category string into a list of canonical category_ids.
    Returns (matched_category_ids, unmatched_fragments).

    Strategy: longest-match-first against the alias map. This handles compound
    names like "Concrete, Pavers & Driveways" without false-splitting.
    """
    if not value or not value.strip():
        return [], []

    remaining = value.strip()
    matched_ids: list[str] = []
    unmatched: list[str] = []

    # Sort aliases by length descending — match the longest possible substring first.
    sorted_aliases = sorted(alias_map.keys(), key=len, reverse=True)

    while remaining:
        # Strip leading commas / whitespace
        remaining = remaining.lstrip(", ").strip()
        if not remaining:
            break

        # Try longest-prefix match
        matched = False
        for alias in sorted_aliases:
            if remaining.startswith(alias):
                # Make sure it's a clean boundary (next char is end-of-string or comma)
                tail = remaining[len(alias):].lstrip()
                if not tail or tail.startswith(","):
                    matched_ids.append(alias_map[alias])
                    remaining = tail
                    matched = True
                    break
        if matched:
            continue

        # Fall back: comma-split the rest, take first fragment as unmatched, recurse on tail
        if "," in remaining:
            head, _, tail = remaining.partition(",")
            head = head.strip()
            if head:
                unmatched.append(head)
            remaining = tail.strip()
        else:
            unmatched.append(remaining)
            remaining = ""

    # Dedupe while preserving order
    seen = set()
    deduped = []
    for cid in matched_ids:
        if cid not in seen:
            seen.add(cid)
            deduped.append(cid)
    return deduped, unmatched


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load alias map: legacy text -> category_id
    print("Loading alias map...")
    aliases = sb.table("category_aliases").select("alias,category_id").execute().data
    alias_map = {a["alias"]: a["category_id"] for a in aliases}
    print(f"  {len(alias_map)} aliases")

    # Load all clients with a non-empty legacy category (one page is enough; paginate just in case)
    print("Loading clients with legacy category...")
    clients = []
    page = 0
    while True:
        chunk = (sb.table("clients")
                 .select("id,name,category")
                 .not_.is_("category", "null")
                 .range(page * 1000, page * 1000 + 999)
                 .execute().data)
        if not chunk:
            break
        clients.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
    # Filter empty strings on Python side
    clients = [c for c in clients if c.get("category") and c["category"].strip()]
    print(f"  {len(clients)} clients with legacy category")

    # Process
    insert_rows = []
    unmatched_counter = Counter()
    fully_unmatched = []   # clients where NO fragment matched
    multi_tag_clients = 0

    for c in clients:
        matched_ids, unmatched_frags = parse_legacy_value(c["category"], alias_map)

        for u in unmatched_frags:
            unmatched_counter[u] += 1

        if not matched_ids:
            fully_unmatched.append(c)
            continue

        if len(matched_ids) > 1:
            multi_tag_clients += 1

        for idx, cat_id in enumerate(matched_ids):
            insert_rows.append({
                "client_id": c["id"],
                "category_id": cat_id,
                "is_primary": idx == 0,  # first matched alias becomes primary
                "source": "legacy_text",
            })

    print(f"\n  total junction rows to insert: {len(insert_rows)}")
    print(f"  multi-tag clients (>=2 categories): {multi_tag_clients}")
    print(f"  fully unmatched clients: {len(fully_unmatched)}")
    if unmatched_counter:
        print(f"\n  Unmatched fragments (top 20):")
        for frag, n in unmatched_counter.most_common(20):
            print(f"    {n:4d}  {frag!r}")

    if args.dry_run:
        print("\n--- DRY RUN: no writes ---")
        if fully_unmatched:
            print(f"\nFully unmatched clients (first 15):")
            for c in fully_unmatched[:15]:
                print(f"  {c['name']!r} | category={c['category']!r}")
        return

    # Insert in batches with upsert (idempotent)
    print("\nWriting client_categories...")
    BATCH = 500
    written = 0
    for i in range(0, len(insert_rows), BATCH):
        batch = insert_rows[i:i + BATCH]
        try:
            sb.table("client_categories").upsert(
                batch, on_conflict="client_id,category_id"
            ).execute()
            written += len(batch)
        except Exception as e:
            # If the partial unique on is_primary trips, fall back to individual inserts
            print(f"  batch {i} failed bulk, retrying individually: {str(e)[:100]}")
            for row in batch:
                try:
                    sb.table("client_categories").upsert(
                        row, on_conflict="client_id,category_id"
                    ).execute()
                    written += 1
                except Exception as e2:
                    print(f"    skip client {row['client_id']}: {str(e2)[:80]}")
        if written % 1000 == 0:
            print(f"  {written}/{len(insert_rows)}...")
    print(f"  Inserted/upserted {written} rows")

    print("\nDone.")


if __name__ == "__main__":
    main()
