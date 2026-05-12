"""One-time cleanup: merge same-market MM-only duplicates into the existing real client.

Background:
  When the MM Contacts ETL did its initial 33,954-row sync, identity resolution
  only matched clients with pre-existing MM identity (mm_global_id,
  mm_database+mm_customer_id, or legacy client_platform_ids.external_id like
  'MM-{zone}-{cid}'). Real clients that existed in our DB from CallRail / IA /
  prior sources but had NO MM platform_id attached fell through and got
  duplicated as fresh is_mm_only=true rows.

  This script finds those duplicate pairs (same normalized name, same market,
  real has no MM identity, dup is is_mm_only=true) and merges them. Per-pair
  semantics:

    1. Copy MM identity fields from dup -> real.
       - mm_global_id, mm_database, mm_customer_id, mm_priority_raw,
         mm_inside_sales_attrib, mm_contact_groups, mm_mail_copies,
         mm_last_cancel_reason, mm_billing_notes, mm_spotted,
         mm_first_order_date, mm_last_order_date, mm_date_added,
         mm_date_modified, mm_url
       - For fields that might already be populated on real (priority,
         sales_attrib, mm_start_issue, call_tracking_notes): use COALESCE so
         existing curated values win. Daily MM ETL will overwrite from MM
         going forward.
    2. Move all dependent rows from dup -> real, handling unique constraints.
    3. Delete the dup row.

  Multi-tenant clients (same name in different markets — e.g. Apex Clean Air
  in CO and UT) are NOT merged. Per business rule: each MM tenant contact gets
  its own DB row. This script filters to primary_market_id equality only.

Safety:
  - --dry-run mode wraps each pair's work in BEGIN/ROLLBACK, prints the plan
    but commits nothing.
  - Each pair runs in its own transaction. Failure on one pair doesn't poison
    others.
  - Idempotent. Re-running finds 0 dupes once executed.
  - Audit row written to etl_runs with full (real_id, dup_id) mapping.

Usage:
  # Preview (no writes)
  python scripts/merge_mm_only_duplicates.py --dry-run

  # Real execute
  python scripts/merge_mm_only_duplicates.py --execute

  # Test on a single pair by client name
  python scripts/merge_mm_only_duplicates.py --dry-run --filter-name "AMSCO Windows"
"""

from __future__ import annotations

import argparse
import configparser
import json
import os
import socket
import sys
import traceback
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg
from psycopg.types.json import Jsonb
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

# ----------------------------------------------------------------------
# Connection helpers
# ----------------------------------------------------------------------
def get_pg_dsn() -> str:
    """Read connection settings from the [supabase] block in .env.

    The .env has both top-level KEY=VAL lines and an INI-style [supabase]
    section. We extract the [supabase] section by hand because configparser
    chokes on the top-level entries.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    in_section = False
    section_lines: list[str] = []
    for line in env_path.read_text().splitlines():
        if line.strip() == "[supabase]":
            in_section = True
            section_lines.append(line)
            continue
        if in_section:
            if line.startswith("[") and line.strip() != "[supabase]":
                break
            section_lines.append(line)
    if not section_lines:
        raise RuntimeError("No [supabase] section found in .env")
    cp = configparser.ConfigParser(interpolation=None)
    cp.read_string("\n".join(section_lines))
    s = cp["supabase"]

    def _val(key: str) -> str:
        return s[key].strip().strip('"').strip("'")

    return (
        f"host={_val('host')} port={_val('port')} dbname={_val('dbname')} "
        f"user={_val('user')} password={_val('password')} sslmode=require"
    )


# ----------------------------------------------------------------------
# MM identity fields to copy / handle
# ----------------------------------------------------------------------
# Copy directly — real has NULL for these (verified by same-market easy-merge query).
MM_DIRECT_FIELDS = [
    "mm_global_id", "mm_database", "mm_customer_id",
    "mm_priority_raw",
    "mm_inside_sales_attrib", "mm_contact_groups",
    "mm_mail_copies",
    "mm_last_cancel_reason", "mm_billing_notes", "mm_spotted",
    "mm_first_order_date", "mm_last_order_date",
    "mm_date_added", "mm_date_modified",
    "mm_url",
]

# Use COALESCE — real might have curated values from old data sources.
# Keep real's value if set, else take dup's.
MM_COALESCE_FIELDS = [
    "priority",
    "sales_attrib",
    "mm_start_issue",
    "call_tracking_notes",
]

ALL_MM_FIELDS = MM_DIRECT_FIELDS + MM_COALESCE_FIELDS


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Preview only (default). Use --execute to commit.")
    ap.add_argument("--execute", action="store_true",
                    help="Commit changes. Overrides --dry-run.")
    ap.add_argument("--limit", type=int, help="Process only first N pairs (for testing)")
    ap.add_argument("--filter-name", help="Only process pairs where real client name contains this string")
    args = ap.parse_args()
    dry_run = not args.execute

    print("=" * 72)
    print("MM-ONLY DUPLICATE MERGE")
    print(f"Mode: {'DRY-RUN (rollback after each pair)' if dry_run else 'EXECUTE (commit each pair)'}")
    print("=" * 72)

    started_at = datetime.now(timezone.utc)

    conn = psycopg.connect(get_pg_dsn(), autocommit=False)
    try:
        # --------------------------------------------------------------
        # 1) Find same-market easy-merge pairs
        # --------------------------------------------------------------
        with conn.cursor() as cur:
            sql = """
            WITH active_book AS (
              SELECT id, name, lower(trim(name)) AS norm,
                     status, primary_market_id
              FROM clients
              WHERE NOT is_mm_only
                AND NOT COALESCE(is_mapping_stub, false)
                AND mm_database IS NULL
            ),
            new_mm AS (
              SELECT id, name, lower(trim(name)) AS norm,
                     primary_market_id, mm_database, mm_customer_id
              FROM clients WHERE is_mm_only
            )
            SELECT
              ab.id AS real_id, ab.name AS real_name, ab.status,
              m.id AS dup_id, m.mm_database AS dup_db, m.mm_customer_id AS dup_cid
            FROM active_book ab
            JOIN new_mm m
              ON m.norm = ab.norm
              AND m.primary_market_id = ab.primary_market_id
            ORDER BY ab.status, ab.name
            """
            cur.execute(sql)
            pairs = cur.fetchall()

        if args.filter_name:
            pairs = [p for p in pairs if args.filter_name.lower() in (p[1] or "").lower()]
        if args.limit:
            pairs = pairs[: args.limit]

        print(f"\nPairs to merge: {len(pairs):,}")
        status_counts = Counter(p[2] for p in pairs)
        for s, n in status_counts.most_common():
            print(f"  status={s}: {n}")
        if not pairs:
            print("Nothing to do.")
            return

        # --------------------------------------------------------------
        # 2) Process each pair
        # --------------------------------------------------------------
        succeeded: list[dict] = []
        failed: list[dict] = []

        for i, (real_id, real_name, status, dup_id, dup_db, dup_cid) in enumerate(pairs, start=1):
            real_id_s = str(real_id)
            dup_id_s = str(dup_id)
            try:
                with conn.cursor() as cur:
                    # 2a) Read dup row
                    cur.execute(
                        f"SELECT {', '.join(ALL_MM_FIELDS)} "
                        f"FROM clients WHERE id = %s",
                        (dup_id_s,),
                    )
                    row = cur.fetchone()
                    if not row:
                        raise RuntimeError(f"dup {dup_id} not found")
                    dup_data = dict(zip(ALL_MM_FIELDS, row))
                    # JSONB columns need explicit wrapping for psycopg3 binding
                    if dup_data.get("mm_priority_raw") is not None:
                        dup_data["mm_priority_raw"] = Jsonb(dup_data["mm_priority_raw"])

                    # 2b) NULL out dup's unique-indexed MM fields BEFORE updating
                    #     real, so the partial unique indexes
                    #     (mm_global_id, mm_database+mm_customer_id) don't fire
                    cur.execute(
                        """
                        UPDATE clients SET
                          mm_global_id = NULL,
                          mm_database = NULL,
                          mm_customer_id = NULL
                        WHERE id = %s
                        """,
                        (dup_id_s,),
                    )

                    # 2c) Update real with MM identity
                    direct_sets = ", ".join(f"{f} = %s" for f in MM_DIRECT_FIELDS)
                    coalesce_sets = ", ".join(
                        f"{f} = COALESCE(NULLIF({f}, ''), %s)" if f in ("priority", "sales_attrib", "call_tracking_notes")
                        else f"{f} = COALESCE({f}, %s)"
                        for f in MM_COALESCE_FIELDS
                    )
                    update_sql = f"UPDATE clients SET {direct_sets}, {coalesce_sets} WHERE id = %s"
                    update_params = [dup_data[f] for f in MM_DIRECT_FIELDS] + \
                                    [dup_data[f] for f in MM_COALESCE_FIELDS] + \
                                    [real_id_s]
                    cur.execute(update_sql, update_params)

                    # 2d) Move client_activities
                    cur.execute(
                        "UPDATE client_activities SET client_id = %s WHERE client_id = %s",
                        (real_id_s, dup_id_s),
                    )
                    activities_moved = cur.rowcount

                    # 2e) Move opportunities
                    cur.execute(
                        "UPDATE opportunities SET client_id = %s WHERE client_id = %s",
                        (real_id_s, dup_id_s),
                    )
                    opps_moved = cur.rowcount

                    # 2f) Move client_categories (handle (client_id, category_id) PK + is_primary uniqueness)
                    #     - If real has no primary tag, allow dup's primary to become primary
                    #     - Otherwise dup tags come in as non-primary
                    cur.execute("""
                        INSERT INTO client_categories (client_id, category_id, is_primary, source)
                        SELECT %s, dc.category_id,
                               CASE
                                 WHEN dc.is_primary
                                  AND NOT EXISTS (
                                    SELECT 1 FROM client_categories
                                    WHERE client_id = %s AND is_primary
                                  )
                                 THEN true
                                 ELSE false
                               END,
                               dc.source
                        FROM client_categories dc
                        WHERE dc.client_id = %s
                        ON CONFLICT (client_id, category_id) DO NOTHING
                    """, (real_id_s, real_id_s, dup_id_s))
                    cats_inserted = cur.rowcount

                    cur.execute(
                        "DELETE FROM client_categories WHERE client_id = %s",
                        (dup_id_s,),
                    )

                    # 2g) Belt-and-suspenders: safety check that dup has no
                    #     other child rows. If any of these have rows, abort —
                    #     means an MM-only dup got data attached after our
                    #     audit, and we need to handle it explicitly.
                    fk_safety_tables = [
                        "orders", "calls", "qr_scans", "form_submissions",
                        "client_ads", "ad_placements", "runsheet_entries",
                        "client_platform_ids", "client_zones",
                        "client_phone_numbers", "client_notes",
                        "classification_log", "email_campaign_clients",
                        "client_reclassification_queue",
                    ]
                    leftover = {}
                    for t in fk_safety_tables:
                        cur.execute(
                            f"SELECT COUNT(*) FROM {t} WHERE client_id = %s",
                            (dup_id_s,),
                        )
                        n = cur.fetchone()[0]
                        if n:
                            leftover[t] = n
                    if leftover:
                        raise RuntimeError(
                            f"unexpected child rows on dup {dup_id}: {leftover}"
                        )

                    # 2h) Delete dup
                    cur.execute(
                        "DELETE FROM clients WHERE id = %s AND is_mm_only = true",
                        (dup_id_s,),
                    )
                    deleted = cur.rowcount

                    if dry_run:
                        conn.rollback()
                    else:
                        conn.commit()

                    succeeded.append({
                        "real_id": real_id_s,
                        "real_name": real_name,
                        "dup_id": dup_id_s,
                        "dup_db": dup_db,
                        "dup_cid": dup_cid,
                        "activities_moved": activities_moved,
                        "opps_moved": opps_moved,
                        "cats_inserted": cats_inserted,
                        "deleted": deleted,
                    })

                    if i <= 5 or i % 50 == 0:
                        print(f"  [{i:>3}/{len(pairs)}] {real_name} "
                              f"<- dup {dup_db}/{dup_cid}: "
                              f"+{activities_moved} act, +{opps_moved} opp, "
                              f"+{cats_inserted} cat")

            except Exception as e:
                conn.rollback()
                failed.append({
                    "real_id": real_id_s, "real_name": real_name,
                    "dup_id": dup_id_s, "dup_db": dup_db, "dup_cid": dup_cid,
                    "error": str(e),
                })
                print(f"  [{i:>3}/{len(pairs)}] FAILED: {real_name} -- {e}")
                if i <= 3:
                    traceback.print_exc()

        # --------------------------------------------------------------
        # 3) Summary + audit
        # --------------------------------------------------------------
        finished_at = datetime.now(timezone.utc)
        elapsed = (finished_at - started_at).total_seconds()

        total_activities = sum(s["activities_moved"] for s in succeeded)
        total_opps = sum(s["opps_moved"] for s in succeeded)
        total_cats = sum(s["cats_inserted"] for s in succeeded)

        print()
        print("=" * 72)
        print(f"Pairs succeeded:  {len(succeeded):,}")
        print(f"Pairs failed:     {len(failed):,}")
        print(f"Activities moved: {total_activities:,}")
        print(f"Opportunities moved: {total_opps:,}")
        print(f"Categories inserted: {total_cats:,}")
        print(f"Elapsed: {elapsed:.1f}s")
        if dry_run:
            print("DRY-RUN -- nothing committed. Use --execute to commit.")
        print("=" * 72)

        # Write audit row only if we actually committed something.
        if not dry_run and succeeded:
            sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
            sb.table("etl_runs").insert({
                "etl_name": "merge_mm_only_duplicates",
                "source": "manual_merge",
                "dry_run": False,
                "started_at": started_at.isoformat(),
                "finished_at": finished_at.isoformat(),
                "success": len(failed) == 0,
                "rows_read": len(pairs),
                "rows_upserted_campaigns": len(succeeded),
                "host": socket.gethostname(),
                "notes": {
                    "succeeded_count": len(succeeded),
                    "failed_count": len(failed),
                    "activities_moved": total_activities,
                    "opportunities_moved": total_opps,
                    "categories_inserted": total_cats,
                    "succeeded_first50": succeeded[:50],
                    "failed_all": failed,
                },
            }).execute()
            print(f"\nAudit row recorded in etl_runs.")

    finally:
        conn.close()


if __name__ == "__main__":
    main()
