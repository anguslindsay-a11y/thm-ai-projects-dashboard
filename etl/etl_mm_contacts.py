"""ETL: MagManager Contacts -> Supabase clients

Pulls api_ContactsGetTHM across all 3 tenants and reconciles into the local
clients table. Phase B of the MagManager API integration.

Identity resolution (in priority order):
  1. Match by clients.mm_global_id
  2. Match by (clients.mm_database, clients.mm_customer_id)
  3. Match by legacy client_platform_ids.external_id == 'MM-{zone}-{customer_id}'
  4. None match  -> create new client with is_mm_only=true

What this writes to existing columns (always overwrites — MM is source of truth):
  - clients.priority          <- MM Priority (extracted from JSON array)
  - clients.sales_attrib      <- MM SalesAttrib (custom field)
  - clients.mm_start_issue    <- MM StartIssue (parsed "11/2012" -> 2012-11-01)
  - clients.call_tracking_notes <- MM CallTrackNotes (with diff-alert logged)

What this writes to NEW columns (always overwrites):
  - All mm_* and is_mm_only columns from migration 012

What it does NOT touch on existing clients:
  - name, display_name (avoids breaking references)
  - status (still derived from orders by sync_client_statuses)
  - sales_rep_id (manual FK linkage)
  - has_call_tracking (managed by call_tracking ETL)
  - is_mapping_stub

Categories:
  - MM Category JSON array -> category_aliases lookup -> client_categories
  - ALL existing client_categories rows are preserved
  - New rows inserted with source='mm_api', is_primary=true ONLY if client has no primary tag

Usage:
  python etl/etl_mm_contacts.py [--dry-run] [--tenant CO|UT|SA] [--limit N] [--no-audit]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from etl.magmanager_client import MagManagerClient

load_dotenv()

# ------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------
DATABASES = [
    "thehomemagcolorado",
    "thehomemagutah",
    "thehomemagsanantonio",
]
DB_TO_MARKET_CODE = {
    "thehomemagcolorado": "CO",
    "thehomemagutah": "UT",
    # SA database splits into AU vs SA based on city
}
ZONE_TO_DB = {  # for bridging legacy MM-{zone}-{cid} -> DatabaseName
    "CO": "thehomemagcolorado",
    "UT": "thehomemagutah",
    "SA": "thehomemagsanantonio",
    "AU": "thehomemagsanantonio",
}

# Austin metro cities — anything else in TX defaults to SA market
AUSTIN_METRO_CITIES = {
    s.lower() for s in {
        "Austin", "Round Rock", "Cedar Park", "Pflugerville", "Leander",
        "Georgetown", "Bee Cave", "Lakeway", "Manor", "Hutto", "Buda",
        "Kyle", "Liberty Hill", "Dripping Springs", "West Lake Hills",
        "Sunset Valley", "Rollingwood", "Jonestown", "Lago Vista",
        "Wells Branch", "Volente", "Wimberley", "San Marcos", "Hudson Bend",
    }
}

UPSERT_BATCH_SIZE = 200

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def parse_json_array(json_str: str | None, key: str) -> list[str]:
    """MM custom-field arrays come as '[{"category":"Furniture"},...]'."""
    if not json_str or json_str.strip() in ("", "[]"):
        return []
    try:
        arr = json.loads(json_str)
        return [
            item.get(key)
            for item in arr
            if isinstance(item, dict) and item.get(key)
        ]
    except (json.JSONDecodeError, TypeError):
        return []


def parse_start_issue(s: str | None) -> str | None:
    """MM StartIssue is 'MM/YYYY' or sometimes 'M/YYYY'. Convert to first-of-month."""
    if not s or not s.strip():
        return None
    m = re.match(r"^\s*(\d{1,2})\s*/\s*(\d{4})\s*$", s.strip())
    if not m:
        return None
    month, year = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12 and 1900 <= year <= 2100):
        return None
    return f"{year}-{month:02d}-01"


def parse_iso_date(s: str | None) -> str | None:
    """ISO datetime -> YYYY-MM-DD, or None."""
    if not s:
        return None
    try:
        # MM dates are 'YYYY-MM-DDTHH:MM:SS.fffZ'
        return s[:10] if len(s) >= 10 else None
    except Exception:
        return None


def normalize_phone(s: str | None) -> str | None:
    if not s:
        return None
    s = s.strip()
    return s if s else None


def market_code_for_contact(contact: dict) -> str | None:
    """Decide which market this MM contact belongs to."""
    db = contact.get("DatabaseName")
    if db == "thehomemagcolorado":
        return "CO"
    if db == "thehomemagutah":
        return "UT"
    if db == "thehomemagsanantonio":
        state = (contact.get("State") or "").upper().strip()
        city = (contact.get("City") or "").lower().strip()
        # Normalize state: API returns both "TX" and "Texas"
        if state in ("TX", "TEXAS"):
            state = "TX"
        if state and state != "TX":
            return None  # legitimately out-of-state — skip market assignment
        if city in AUSTIN_METRO_CITIES:
            return "AU"
        return "SA"
    return None


# ------------------------------------------------------------------
# Main ETL
# ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Read+plan only, no writes")
    ap.add_argument("--tenant", choices=["CO", "UT", "SA"],
                    help="Run only one tenant (CO=thehomemagcolorado, etc.)")
    ap.add_argument("--limit", type=int, help="Cap rows per tenant for testing")
    ap.add_argument("--no-audit", action="store_true", help="Skip etl_runs row")
    args = ap.parse_args()

    print("=" * 70)
    print("MAGMANAGER CONTACTS ETL")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    if args.tenant:
        print(f"Tenant: {args.tenant} only")
    if args.limit:
        print(f"Limit: {args.limit} rows/tenant")
    print("=" * 70)

    mm = MagManagerClient()
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 0) Pre-load lookup tables
    # ------------------------------------------------------------------
    print("\n[0/5] Loading reference data...")

    markets = sb.table("markets").select("id,code").execute().data
    market_id_by_code = {m["code"]: m["id"] for m in markets}
    print(f"  markets: {market_id_by_code}")

    # Category aliases (alias_lower -> category_id)
    aliases = sb.table("category_aliases").select("alias,category_id").limit(10000).execute().data
    alias_to_category = {a["alias"].strip().lower(): a["category_id"] for a in aliases}
    print(f"  category aliases: {len(alias_to_category):,}")

    # Existing clients with MM identity (for fast match)
    # Need to paginate — supabase-py default limit is 1000
    existing_clients = []
    offset = 0
    while True:
        batch = (
            sb.table("clients")
            .select(
                "id,name,mm_global_id,mm_database,mm_customer_id,"
                "mm_date_modified,call_tracking_notes,is_mapping_stub,"
                "primary_market_id,priority"
            )
            .range(offset, offset + 999)
            .execute()
            .data
        )
        existing_clients.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  existing clients: {len(existing_clients):,}")

    by_mm_global_id = {
        c["mm_global_id"]: c for c in existing_clients if c.get("mm_global_id")
    }
    by_db_customer = {
        (c["mm_database"], c["mm_customer_id"]): c
        for c in existing_clients
        if c.get("mm_database") and c.get("mm_customer_id") is not None
    }

    # Legacy MM platform_ids
    legacy_lookup = {}
    offset = 0
    while True:
        batch = (
            sb.table("client_platform_ids")
            .select("client_id,external_id")
            .eq("platform", "magazine_manager")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for e in batch:
            pid = e.get("external_id") or ""
            parts = pid.split("-")
            if len(parts) >= 3 and parts[-1].isdigit():
                zone = parts[1]
                cid = int(parts[-1])
                db_name = ZONE_TO_DB.get(zone)
                if db_name:
                    legacy_lookup[(db_name, cid)] = e["client_id"]
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  legacy MM platform_ids: {len(legacy_lookup):,}")

    # Existing client_categories (for skip-if-already-set logic)
    cc_existing = set()
    cc_has_primary = set()
    offset = 0
    while True:
        batch = (
            sb.table("client_categories")
            .select("client_id,category_id,is_primary")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for c in batch:
            cc_existing.add((c["client_id"], c["category_id"]))
            if c["is_primary"]:
                cc_has_primary.add(c["client_id"])
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  existing client_categories: {len(cc_existing):,}")
    print(f"  clients with primary tag: {len(cc_has_primary):,}")

    # ------------------------------------------------------------------
    # 1) Pull MM contacts across tenants
    # ------------------------------------------------------------------
    print("\n[1/5] Pulling contacts from MagManager API...")
    tenants_to_run = [d for d in DATABASES if not args.tenant
                       or (args.tenant == "CO" and d == "thehomemagcolorado")
                       or (args.tenant == "UT" and d == "thehomemagutah")
                       or (args.tenant == "SA" and d == "thehomemagsanantonio")]

    all_contacts: list[dict] = []
    for db in tenants_to_run:
        per_db = []
        page = 1
        while True:
            body = mm.get_contacts_page(page=page, database_name=db)
            rows = body.get("Data") or []
            for r in rows:
                r.setdefault("DatabaseName", db)
            per_db.extend(rows)
            print(f"  {db} page {page}: {len(rows)} rows")
            if len(rows) < 10000:
                break
            page += 1
            if page > 10:
                break
            if args.limit and len(per_db) >= args.limit:
                break
        if args.limit:
            per_db = per_db[: args.limit]
        all_contacts.extend(per_db)
    print(f"  TOTAL: {len(all_contacts):,} contacts pulled")

    # Dedupe by GlobalID — MM occasionally returns the same contact twice (e.g.
    # 'Drain & Air Rescue - DUP'). Keep the first occurrence.
    seen_gids = set()
    seen_db_cid = set()
    deduped = []
    dup_count = 0
    for c in all_contacts:
        gid = c.get("GlobalID")
        key_cid = (c.get("DatabaseName"), c.get("CustomerID"))
        if gid and gid in seen_gids:
            dup_count += 1
            continue
        if key_cid in seen_db_cid:
            dup_count += 1
            continue
        if gid:
            seen_gids.add(gid)
        seen_db_cid.add(key_cid)
        deduped.append(c)
    if dup_count:
        print(f"  deduplicated {dup_count} duplicate contact(s)")
    all_contacts = deduped

    # ------------------------------------------------------------------
    # 2) Plan: classify each contact as UPDATE vs INSERT
    # ------------------------------------------------------------------
    print("\n[2/5] Classifying contacts (update vs insert)...")
    to_update: list[tuple[dict, dict]] = []  # (existing_client, payload)
    to_insert: list[dict] = []               # new client payloads
    new_platform_ids: list[dict] = []        # legacy bridge rows to create
    category_inserts: list[dict] = []        # client_categories rows
    ct_diffs: list[dict] = []                # call_tracking_notes diffs to log
    priority_diffs: list[dict] = []          # priority changes to log
    skipped_no_market: list[dict] = []

    unmapped_categories: Counter[str] = Counter()
    stats_by_db = defaultdict(lambda: Counter())

    for c in all_contacts:
        db = c["DatabaseName"]
        cid = int(c.get("CustomerID")) if c.get("CustomerID") is not None else None
        if cid is None:
            continue
        global_id = c.get("GlobalID") or None
        market_code = market_code_for_contact(c)
        market_id = market_id_by_code.get(market_code) if market_code else None

        # Resolve identity
        existing = None
        if global_id and global_id in by_mm_global_id:
            existing = by_mm_global_id[global_id]
        elif (db, cid) in by_db_customer:
            existing = by_db_customer[(db, cid)]
        elif (db, cid) in legacy_lookup:
            # Bridge: legacy client_platform_ids hit but no mm_global_id set yet
            cid_match = legacy_lookup[(db, cid)]
            # Find that client
            for ec in existing_clients:
                if ec["id"] == cid_match:
                    existing = ec
                    break

        # Build the MM-side fields (common to insert + update)
        priority_values = parse_json_array(c.get("Priority"), "priority")
        category_values = parse_json_array(c.get("Category"), "category")
        contact_groups = parse_json_array(c.get("ContactGroup"), "contactgroup")

        mm_fields = {
            "mm_global_id": global_id,
            "mm_database": db,
            "mm_customer_id": cid,
            "priority": priority_values[0] if priority_values else None,
            "mm_priority_raw": (json.loads(c["Priority"]) if c.get("Priority")
                                 and c.get("Priority").strip() not in ("", "[]") else None),
            "sales_attrib": c.get("SalesAttrib") or None,
            "mm_inside_sales_attrib": c.get("InsideSalesAttrib") or None,
            "mm_contact_groups": contact_groups or None,
            "mm_mail_copies": c.get("MailCopies") or None,
            "mm_last_cancel_reason": c.get("LastCancelReason") or None,
            "mm_billing_notes": c.get("BillingNotes") or None,
            "mm_spotted": c.get("Spotted") or None,
            "mm_start_issue": parse_start_issue(c.get("StartIssue")),
            "mm_first_order_date": parse_iso_date(c.get("FirstOrderDate")),
            "mm_last_order_date": parse_iso_date(c.get("LastOrderDate")),
            "mm_date_added": c.get("DateAdded") or None,
            "mm_date_modified": c.get("DateLastModified") or None,
            "mm_url": c.get("URL") or None,
            "call_tracking_notes": c.get("CallTrackNotes") or None,
        }

        if existing:
            # Skip if MM mm_date_modified is unchanged — nothing to update
            existing_modified = existing.get("mm_date_modified")
            incoming_modified = mm_fields.get("mm_date_modified")
            if (existing_modified and incoming_modified
                    and existing_modified[:19] == incoming_modified[:19]):
                stats_by_db[db]["skip_unchanged"] += 1
                continue
            stats_by_db[db]["update"] += 1
            # Don't overwrite is_mm_only on update (we don't downgrade)
            payload = dict(mm_fields)
            # Track call_tracking_notes diffs for review
            old_ct = (existing.get("call_tracking_notes") or "").strip()
            new_ct = (mm_fields.get("call_tracking_notes") or "").strip()
            if old_ct and new_ct and old_ct != new_ct:
                ct_diffs.append({
                    "client_id": existing["id"],
                    "client_name": existing.get("name"),
                    "mm_database": db,
                    "mm_customer_id": cid,
                    "old_chars": len(old_ct),
                    "new_chars": len(new_ct),
                })
            # Track priority changes — MM is source of truth, but we want a record
            # of every transition (e.g. "04 - Active" -> "08 - Cancelled", or
            # "01 - New Prospect" -> "04 - Active"). Captures churn + wins.
            old_pri = (existing.get("priority") or "").strip()
            new_pri = (mm_fields.get("priority") or "").strip()
            if old_pri != new_pri:
                priority_diffs.append({
                    "client_id": existing["id"],
                    "client_name": existing.get("name"),
                    "mm_database": db,
                    "mm_customer_id": cid,
                    "old": old_pri or None,
                    "new": new_pri or None,
                })
            to_update.append((existing, payload))

        else:
            # NEW client
            if not market_id:
                # Can't assign a market — skip insertion. Log for review.
                skipped_no_market.append({
                    "mm_database": db, "mm_customer_id": cid,
                    "city": c.get("City"), "state": c.get("State"),
                    "name": c.get("Customer"),
                })
                continue

            stats_by_db[db]["insert"] += 1
            insert_payload = dict(mm_fields)
            insert_payload.update({
                "name": c.get("Customer") or f"MM-{db}-{cid}",
                "contact_name": c.get("PrimaryContact") or c.get("BillingContact"),
                "contact_phone": normalize_phone(c.get("PrimaryPhone") or c.get("BillingPhone")),
                "contact_email": c.get("PrimaryEmail") or c.get("BillingEmail"),
                "website": c.get("URL") or None,
                "primary_market_id": market_id,
                "is_mm_only": True,
                "is_mapping_stub": False,
                "status": "prospect",  # no orders -> prospect (will be re-derived later)
            })
            to_insert.append(insert_payload)

            # Bridge legacy platform_ids zone-suffix style if we'd want to
            # (skipped — new clients only get mm_global_id; legacy format only matters
            # for backward lookups, no need to mint new MM-{zone}-{cid} rows here)

        # Process categories AFTER identity is resolved (deferred until after insert
        # for new clients — we need the client_id from the insert).
        # For now, just classify unmapped strings so we can warn.
        for catval in category_values:
            target = alias_to_category.get(catval.strip().lower())
            if not target:
                unmapped_categories[catval] += 1

    print(f"  to update: {sum(s.get('update',0) for s in stats_by_db.values()):,}")
    print(f"  to insert: {sum(s.get('insert',0) for s in stats_by_db.values()):,}")
    print(f"  skipped (no market resolution): {len(skipped_no_market):,}")
    print(f"  unmapped category strings: {len(unmapped_categories)}")
    if unmapped_categories:
        print(f"    (top 5: {unmapped_categories.most_common(5)})")
    print(f"  call_tracking_notes diffs flagged: {len(ct_diffs):,}")
    print(f"  priority changes flagged: {len(priority_diffs):,}")
    if priority_diffs:
        transitions = Counter(
            f"{d['old'] or '(empty)'} -> {d['new'] or '(empty)'}"
            for d in priority_diffs
        )
        for t, n in transitions.most_common(8):
            print(f"    {t}: {n}")

    # ------------------------------------------------------------------
    # 3) Execute writes
    # ------------------------------------------------------------------
    inserted_ids_by_db_cid: dict[tuple[str, int], str] = {}

    if args.dry_run:
        print("\n[3/5] DRY-RUN — skipping all writes")
    else:
        print("\n[3/5] Writing changes...")

        # 3a) INSERT new clients
        if to_insert:
            print(f"  inserting {len(to_insert):,} new clients in batches of {UPSERT_BATCH_SIZE}...")
            for i in range(0, len(to_insert), UPSERT_BATCH_SIZE):
                chunk = to_insert[i : i + UPSERT_BATCH_SIZE]
                resp = sb.table("clients").insert(chunk).execute()
                for row in resp.data:
                    key = (row["mm_database"], row["mm_customer_id"])
                    inserted_ids_by_db_cid[key] = row["id"]
                if (i // UPSERT_BATCH_SIZE) % 10 == 0:
                    print(f"    {i + len(chunk):,} / {len(to_insert):,}")
            print(f"  inserted {len(inserted_ids_by_db_cid):,} new clients")

        # 3b) UPDATE existing clients (batched per row — supabase doesn't bulk update;
        # but we can use upsert keyed by mm_database/mm_customer_id since rows have
        # been seeded with those fields. Safer: row-by-row update.)
        if to_update:
            print(f"  updating {len(to_update):,} existing clients...")
            for i, (existing, payload) in enumerate(to_update):
                sb.table("clients").update(payload).eq("id", existing["id"]).execute()
                if i and i % 500 == 0:
                    print(f"    {i:,} / {len(to_update):,}")
            print(f"  updated {len(to_update):,} clients")

    # ------------------------------------------------------------------
    # 4) Process categories junction (after inserts so we have client_ids)
    # ------------------------------------------------------------------
    print("\n[4/5] Processing categories junction...")
    cc_to_insert = []
    for c in all_contacts:
        db = c["DatabaseName"]
        cid = int(c.get("CustomerID")) if c.get("CustomerID") is not None else None
        if cid is None:
            continue
        global_id = c.get("GlobalID")
        # Resolve the local client id (post-insert)
        local_id = None
        if global_id and global_id in by_mm_global_id:
            local_id = by_mm_global_id[global_id]["id"]
        elif (db, cid) in by_db_customer:
            local_id = by_db_customer[(db, cid)]["id"]
        elif (db, cid) in legacy_lookup:
            local_id = legacy_lookup[(db, cid)]
        elif (db, cid) in inserted_ids_by_db_cid:
            local_id = inserted_ids_by_db_cid[(db, cid)]

        if not local_id:
            continue

        category_values = parse_json_array(c.get("Category"), "category")
        already_has_primary = local_id in cc_has_primary
        for idx, catval in enumerate(category_values):
            target_id = alias_to_category.get(catval.strip().lower())
            if not target_id:
                continue
            if (local_id, target_id) in cc_existing:
                continue
            # First category for client with no existing primary -> primary; else secondary
            is_primary = (not already_has_primary) and (idx == 0)
            if is_primary:
                already_has_primary = True
            cc_to_insert.append({
                "client_id": local_id,
                "category_id": target_id,
                "is_primary": is_primary,
                "source": "mm_api",
            })

    # Deduplicate within batch — multiple MM category synonyms can map to the
    # same target category_id for one client (e.g. "HVAC" + "AIR/HEAT/AC" both
    # -> hvac-plumbing). Keep first occurrence which carries the primary flag.
    seen_cc = set()
    cc_dedup = []
    for row in cc_to_insert:
        key = (row["client_id"], row["category_id"])
        if key in seen_cc:
            continue
        seen_cc.add(key)
        cc_dedup.append(row)
    if len(cc_dedup) != len(cc_to_insert):
        print(f"  deduplicated {len(cc_to_insert) - len(cc_dedup)} junction duplicates")
    cc_to_insert = cc_dedup

    print(f"  category junction rows to insert: {len(cc_to_insert):,}")

    if args.dry_run:
        print("  DRY-RUN — skipping")
    elif cc_to_insert:
        for i in range(0, len(cc_to_insert), UPSERT_BATCH_SIZE):
            chunk = cc_to_insert[i : i + UPSERT_BATCH_SIZE]
            sb.table("client_categories").upsert(
                chunk, on_conflict="client_id,category_id"
            ).execute()
        print(f"  inserted/upserted {len(cc_to_insert):,} category rows")

    # ------------------------------------------------------------------
    # 5) Audit log
    # ------------------------------------------------------------------
    finished_at = datetime.now(timezone.utc)
    elapsed = (finished_at - started_at).total_seconds()
    print(f"\n[5/5] Audit + summary")
    print(f"  Elapsed: {elapsed:.1f}s")

    summary = {
        "mode": "dry-run" if args.dry_run else "write",
        "tenants": tenants_to_run,
        "stats_by_db": {k: dict(v) for k, v in stats_by_db.items()},
        "total_pulled": len(all_contacts),
        "total_insert": sum(s.get("insert", 0) for s in stats_by_db.values()),
        "total_update": sum(s.get("update", 0) for s in stats_by_db.values()),
        "skipped_no_market_count": len(skipped_no_market),
        "skipped_no_market_first10": skipped_no_market[:10],
        "category_inserts": len(cc_to_insert),
        "unmapped_categories": dict(unmapped_categories.most_common(20)),
        "ct_notes_diffs_count": len(ct_diffs),
        "ct_notes_diffs_first10": ct_diffs[:10],
        "priority_diffs_count": len(priority_diffs),
        "priority_diffs_transitions": dict(Counter(
            f"{d['old'] or '(empty)'} -> {d['new'] or '(empty)'}"
            for d in priority_diffs
        ).most_common(20)),
        "priority_diffs_first20": priority_diffs[:20],
    }

    if not args.no_audit and not args.dry_run:
        sb.table("etl_runs").insert({
            "etl_name": "mm_contacts",
            "source": "magmanager_api",
            "dry_run": False,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "success": True,
            "rows_read": len(all_contacts),
            "rows_upserted_campaigns": (sum(s.get("insert", 0) for s in stats_by_db.values())
                                         + sum(s.get("update", 0) for s in stats_by_db.values())),
            "rows_upserted_links": len(cc_to_insert),
            "host": socket.gethostname(),
            "notes": summary,
        }).execute()
        print("  etl_runs row recorded")

    print("\nSummary:")
    print(json.dumps({k: v for k, v in summary.items() if "first10" not in k}, indent=2, default=str))


if __name__ == "__main__":
    main()
