"""Probe the MagManager API — read-only, low-volume.

Phase 1 of the MagManager API integration. Goals:
  1. Confirm API key has access to all expected databases (CO, UT, SA)
  2. Confirm Proposals endpoint surfaces both pre-orders AND converted orders
  3. Sample raw JSON to data/mm_api_probes/ for schema design
  4. Reconcile GlobalIDs with existing clients table

Outputs:
  - data/mm_api_probes/<endpoint>_sample.json (5 rows each)
  - data/mm_api_probes/probe_report.md (human-readable findings)

Usage:
  python scripts/probe_mm_api.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from etl.magmanager_client import MagManagerClient

load_dotenv()

OUT_DIR = Path(__file__).resolve().parent.parent / "data" / "mm_api_probes"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def write_sample(name: str, payload) -> None:
    path = OUT_DIR / f"{name}.json"
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"  wrote {path.relative_to(OUT_DIR.parent.parent)}")


def main():
    print("=" * 70)
    print("MAGMANAGER API PROBE")
    print(f"Started: {datetime.now().isoformat(timespec='seconds')}")
    print("=" * 70)

    mm = MagManagerClient()
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

    findings: list[str] = []
    findings.append(f"# MagManager API Probe Report")
    findings.append(f"_Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n")

    # ------------------------------------------------------------------
    # 1. Contacts — what tenants are accessible? what volume per tenant?
    # ------------------------------------------------------------------
    # IMPORTANT: API quirk — "DatabaseName empty = all" doesn't work for this
    # key. It silently returns only the base-URL tenant (thehomemagcolorado).
    # Workaround: iterate per database explicitly.
    DATABASES = ["thehomemagcolorado", "thehomemagutah", "thehomemagsanantonio"]
    print("\n[1/4] Probing api_ContactsGetTHM (per-tenant)...")
    total_contacts = Counter()
    all_mm_contacts = []
    sample_per_db = {}
    for db in DATABASES:
        print(f"  -- {db} --")
        page = 1
        while True:
            body = mm.get_contacts_page(page=page, database_name=db)
            rows = body.get("Data") or []
            if page == 1 and rows:
                sample_per_db[db] = rows[:3]
            for r in rows:
                # Ensure DatabaseName is populated (some endpoints may omit it
                # when scoped to a single DB)
                r.setdefault("DatabaseName", db)
                total_contacts[db] += 1
                all_mm_contacts.append(r)
            print(f"    page {page}: {len(rows)} rows")
            if len(rows) < 10000:
                break
            page += 1
            if page > 10:
                print("    WARN: bailing pagination at page 10")
                break

    write_sample("contacts_per_db_samples", sample_per_db)

    findings.append("## Contacts (api_ContactsGetTHM)\n")
    findings.append(f"- Total accessible contacts: **{sum(total_contacts.values()):,}**")
    for db, n in total_contacts.most_common():
        findings.append(f"  - `{db}`: {n:,}")
    findings.append("- API quirk: omitting `DatabaseName` returns ONLY the base-URL tenant "
                    "(thehomemagcolorado), not all accessible tenants. ETL must iterate per-tenant.")
    findings.append("")

    # ------------------------------------------------------------------
    # 2. GlobalID reconciliation with existing clients
    # ------------------------------------------------------------------
    print("\n[2/4] Reconciling GlobalIDs against existing clients table...")
    print(f"  MM contacts (all 3 tenants): {len(all_mm_contacts):,}")

    # Existing client_platform_ids for MM
    existing_mm = sb.table("client_platform_ids").select(
        "client_id,platform,external_id"
    ).eq("platform", "magazine_manager").execute().data
    print(f"  existing client_platform_ids (MM): {len(existing_mm):,}")

    # Build lookup: GlobalID format is "{tenant_id}-{customerID}"
    # Existing MM IDs look like "MM-CO-7457" — totally different format
    # We need to match on (database_name, CustomerID) -> our existing MM-{zone}-{id}
    # But our format uses ZONE not market. Audit how many we can bridge.

    # Sample existing MM IDs
    existing_sample = [e["external_id"] for e in existing_mm[:10]]
    findings.append("## GlobalID Reconciliation\n")
    findings.append(f"- MM contacts pulled (all tenants): **{len(all_mm_contacts):,}**")
    findings.append(f"- Existing `client_platform_ids` (platform='magazine_manager'): **{len(existing_mm):,}**")
    findings.append(f"- Sample existing MM IDs: `{existing_sample}`")

    # Bridge: legacy format MM-{zone}-{customerID}
    # MM API: per-tenant CustomerID + DatabaseName
    # Most precise match is (database, customerID) pair → bridge via market mapping
    # Legacy uses zone codes (CO/UT/SA) directly in MM-{zone}-{id}.
    DB_TO_LEGACY_PREFIX = {
        "thehomemagcolorado": ["MM-CO"],
        "thehomemagutah": ["MM-UT"],
        "thehomemagsanantonio": ["MM-SA", "MM-AU"],  # AU/SA share one DB
    }
    legacy_keys = set()  # (database_name_inferred, customer_id) tuples
    for e in existing_mm:
        pid = e["external_id"] or ""
        parts = pid.split("-")
        if len(parts) >= 3 and parts[-1].isdigit():
            zone = parts[1]
            cid = int(parts[-1])
            # Infer the DB
            if zone == "CO":
                legacy_keys.add(("thehomemagcolorado", cid))
            elif zone == "UT":
                legacy_keys.add(("thehomemagutah", cid))
            elif zone in ("SA", "AU"):
                legacy_keys.add(("thehomemagsanantonio", cid))

    mm_keys = {
        (c.get("DatabaseName"), int(c["CustomerID"]))
        for c in all_mm_contacts if c.get("CustomerID")
    }

    overlap = legacy_keys & mm_keys
    only_in_legacy = legacy_keys - mm_keys
    only_in_mm = mm_keys - legacy_keys

    findings.append(f"- (Database, CustomerID) pairs in MM API: **{len(mm_keys):,}**")
    findings.append(f"- (Database, CustomerID) pairs in our DB: **{len(legacy_keys):,}**")
    findings.append(f"- Overlap (already mapped): **{len(overlap):,}**")
    findings.append(f"- Only in our DB (in legacy, gone from MM): **{len(only_in_legacy):,}** — likely soft-deleted in MM")
    findings.append(f"- Only in MM API (NEW to us): **{len(only_in_mm):,}** — the contact/prospect influx")

    # Break down "only in MM" by tenant
    only_in_mm_by_db = Counter(t[0] for t in only_in_mm)
    for db, n in sorted(only_in_mm_by_db.items()):
        findings.append(f"  - new in `{db}`: **{n:,}**")
    findings.append("")

    # ------------------------------------------------------------------
    # 3. Proposals — confirm orders flow through here, sample per tenant
    # ------------------------------------------------------------------
    print("\n[3/4] Probing api_ProposalsGetTHM (per tenant, page 1 each)...")
    all_prop_sample = []
    prop_samples_by_db = {}
    for db in DATABASES:
        body = mm.get_proposals_page(page=1, database_name=db)
        rows = body.get("Data", [])
        for r in rows:
            r.setdefault("DatabaseName", db)
        all_prop_sample.extend(rows)
        if rows:
            prop_samples_by_db[db] = rows[:3]
        print(f"  {db}: page 1 = {len(rows)} rows")

    write_sample("proposals_per_db_samples", prop_samples_by_db)

    converted_count = sum(1 for r in all_prop_sample if r.get("ConvertedToContract"))
    has_order_id = sum(1 for r in all_prop_sample if r.get("OrderID") is not None)
    by_status = Counter(r.get("ApprovalStatus") for r in all_prop_sample)
    by_db = Counter(r.get("DatabaseName") for r in all_prop_sample)

    findings.append("## Proposals (api_ProposalsGetTHM) — page 1 per tenant\n")
    findings.append(f"- Total rows sampled: **{len(all_prop_sample):,}** (max 1,000/page × 3 tenants)")
    findings.append(f"- ConvertedToContract=true (these ARE booked orders): **{converted_count}** / {len(all_prop_sample)} = {(converted_count*100//max(1,len(all_prop_sample)))}%")
    findings.append(f"- OrderID populated: **{has_order_id}**")
    findings.append(f"- ApprovalStatus distribution: `{dict(by_status)}` (0=Draft, 1=Sent, 2=Approved)")
    findings.append(f"- Per-tenant page 1 counts: `{dict(by_db)}`")
    findings.append("")

    # Calibrate active-pipeline volume (unconverted + unvoided) per tenant
    print("\n  Estimating active proposal pipeline volume per tenant...")
    active_volumes = {}
    for db in DATABASES:
        body = mm.get_proposals_page(page=1, is_active="1", database_name=db)
        rows = body.get("Data", [])
        active_volumes[db] = len(rows)
        print(f"  {db} IsActive=1 page 1: {len(rows)}")
    findings.append(f"- `IsActive=1` page 1 (pre-order pipeline): `{active_volumes}`")
    findings.append("")

    # ------------------------------------------------------------------
    # 4. Opportunities — small sample per tenant
    # ------------------------------------------------------------------
    print("\n[4/4] Probing api_OpportunityGetTHM and api_ContactActivityGetTHM...")
    all_opp_sample = []
    opp_samples_by_db = {}
    for db in DATABASES:
        body = mm.get_opportunities_page(page=1, database_name=db)
        rows = body.get("Data", [])
        for r in rows:
            r.setdefault("DatabaseName", db)
        all_opp_sample.extend(rows)
        if rows:
            opp_samples_by_db[db] = rows[:3]
        print(f"  {db} opportunities page 1: {len(rows)}")
    write_sample("opportunities_per_db_samples", opp_samples_by_db)

    # Open only
    open_by_db = {}
    for db in DATABASES:
        body = mm.get_opportunities_page(page=1, status="Open", database_name=db)
        open_by_db[db] = len(body.get("Data") or [])

    findings.append("## Opportunities (api_OpportunityGetTHM)\n")
    findings.append(f"- Total page-1 rows across tenants: **{len(all_opp_sample):,}**")
    by_db_opp = Counter(r.get("DatabaseName") for r in all_opp_sample)
    by_status_opp = Counter(r.get("Status") for r in all_opp_sample)
    findings.append(f"- Status distribution: `{dict(by_status_opp)}`")
    findings.append(f"- Per-tenant page 1: `{dict(by_db_opp)}`")
    findings.append(f"- Open-only page 1 per tenant: `{open_by_db}`")
    findings.append("")

    # Activities — last 30 days only, per tenant (calibrate volume)
    from datetime import timedelta
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    all_act_sample = []
    act_samples_by_db = {}
    for db in DATABASES:
        body = mm.get_activities_page(page=1, from_date=thirty_days_ago, database_name=db)
        rows = body.get("Data", [])
        for r in rows:
            r.setdefault("DatabaseName", db)
        all_act_sample.extend(rows)
        if rows:
            act_samples_by_db[db] = rows[:3]
        print(f"  {db} activities (last 30d) page 1: {len(rows)}")
    write_sample("activities_last30d_per_db_samples", act_samples_by_db)

    by_db_act = Counter(r.get("DatabaseName") for r in all_act_sample)
    by_type = Counter(r.get("ActivityType") for r in all_act_sample)
    is_system = sum(1 for r in all_act_sample if r.get("IsSystem"))

    findings.append("## Activities (api_ContactActivityGetTHM) — last 30 days\n")
    findings.append(f"- Total page-1 rows across tenants: **{len(all_act_sample):,}**")
    findings.append(f"- IsSystem=true (auto-generated, filter at ETL): **{is_system}**")
    findings.append(f"- ActivityType distribution: `{dict(by_type)}`")
    findings.append(f"- Per-tenant page 1: `{dict(by_db_act)}`")
    full_pages = {db: n for db, n in by_db_act.items() if n == 1000}
    if full_pages:
        findings.append(f"- ⚠️  Page-1 was FULL (1000 rows) for: {list(full_pages)} → last 30 days alone needs multi-page pagination")
    findings.append("")

    # ------------------------------------------------------------------
    # 5. Targeted lookup: confirm Proposals=Orders for a known active client
    # Try Woodley's (CO CustomerID=1618 from doc example), fall back to first
    # client in our DB that has an MM external_id
    # ------------------------------------------------------------------
    print("\n[5/5] Targeted lookup: confirm Proposals=Orders link...")
    target_client = None
    target_cid = None
    target_db = None
    target_local_id = None

    # Try Woodley's first
    wd = mm.get_contacts_page(customer_id="1618", database_name="thehomemagcolorado").get("Data", [])
    if wd and "Woodley" in (wd[0].get("Customer") or ""):
        target_client = wd[0]
        target_cid = "1618"
        target_db = "thehomemagcolorado"
        wd_client = sb.table("clients").select("id,name").ilike("name", "%Woodley%").execute().data
        if wd_client:
            target_local_id = wd_client[0]["id"]
            target_local_name = wd_client[0]["name"]
        else:
            target_local_name = None

    if target_client:
        w_props = mm.get_proposals_page(
            customer_id=target_cid, database_name=target_db, page=1
        ).get("Data", [])
        w_props_converted = [p for p in w_props if p.get("ConvertedToContract")]
        w_opps = mm.get_opportunities_page(
            customer_id=target_cid, database_name=target_db
        ).get("Data", [])

        write_sample("client_bundle_woodleys", {
            "contact": target_client,
            "proposals_first10": w_props[:10],
            "proposals_count_page1": len(w_props),
            "proposals_converted_to_contract": len(w_props_converted),
            "opportunities": w_opps,
        })

        findings.append("## Cross-check: Woodley's Fine Furniture (CO CustomerID=1618)\n")
        findings.append(f"- MM contact: **{target_client.get('Customer')}** "
                        f"(Priority=`{target_client.get('Priority')}`, "
                        f"GlobalID=`{target_client.get('GlobalID')}`)")
        findings.append(f"- MM proposals page 1: **{len(w_props)}** rows")
        findings.append(f"  - ConvertedToContract=true: **{len(w_props_converted)}**")
        findings.append(f"  - ConvertedToContract=false (pre-order): **{len(w_props) - len(w_props_converted)}**")
        findings.append(f"- MM opportunities: **{len(w_opps)}**")
        if target_local_id:
            our_orders = sb.table("orders").select(
                "id", count="exact"
            ).eq("client_id", target_local_id).execute()
            findings.append(f"- Our local `clients` row: **{target_local_name}** "
                            f"(id={target_local_id})")
            findings.append(f"- Our `orders.count` for that client: **{our_orders.count}**")
            findings.append("- **Proposals=Orders theory:** if MM's `ConvertedToContract=true` count "
                            f"matches our orders count, theory is **confirmed**.")
        else:
            findings.append("- ⚠️  No local `clients` row matching 'Woodley%' — would need to add via initial sync")
        findings.append("")

    # ------------------------------------------------------------------
    # Write report
    # ------------------------------------------------------------------
    findings.append("## Files Generated\n")
    for f in sorted(OUT_DIR.glob("*.json")):
        findings.append(f"- `data/mm_api_probes/{f.name}`")

    report_path = OUT_DIR / "probe_report.md"
    report_path.write_text("\n".join(findings), encoding="utf-8")
    print(f"\n{'=' * 70}")
    print(f"PROBE COMPLETE")
    print(f"Report: {report_path.relative_to(OUT_DIR.parent.parent)}")
    print(f"Samples: {OUT_DIR.relative_to(OUT_DIR.parent.parent)}/")
    print("=" * 70)


if __name__ == "__main__":
    main()
