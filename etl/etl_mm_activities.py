"""ETL: MagManager Activities -> Supabase client_activities

Pulls api_ContactActivityGetTHM across all 3 tenants and upserts into
the client_activities table. Activities are immutable in MM (notes/calls
once logged don't change), so we just upsert by (mm_database, mm_activity_id).

Data shape (last 30 days sample):
  - call_note (62%): rep call summaries, "LM for X" / "texted Y"
  - email_thread_chrome (12%): full email threads, HTML-formatted
  - freeform_note (23%): short tags ("Leads List") or judgments
                          ("Bad Category. Could revisit...")
  - meeting_note (1.1%): "Met with X and Y, interested in exploring"
  - system_autogen (1.2%): MM workflow prompts (renewal, winback)
  - empty (<0.1%): only 2 in 6,403 — keep everything

Notes processing:
  - HTML stripped at ingest: <br> -> \n, remove other tags, decode entities
  - Preserves email-thread structure (Sent/To/From/Subject/body)
  - Stored CLEAN — raw is retrievable from MM by ActivityID if ever needed

Identity:
  - Unique key: (mm_database, mm_activity_id)
  - client_id resolved via clients lookup by (mm_database, mm_customer_id)
  - Activities without a matching local client get client_id=NULL

Usage:
  python etl/etl_mm_activities.py [--days 30] [--from-date YYYY-MM-DD] \
                                   [--dry-run] [--tenant CO|UT|SA] [--no-audit]
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import socket
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from supabase import create_client

from etl.magmanager_client import MagManagerClient

load_dotenv()

DATABASES = [
    "thehomemagcolorado",
    "thehomemagutah",
    "thehomemagsanantonio",
]
UPSERT_BATCH_SIZE = 200


# HTML stripping ------------------------------------------------------
BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")
MULTI_BLANK_RE = re.compile(r"\n[ \t]*\n[ \t]*\n+")


def clean_notes(s: str | None) -> str | None:
    """Strip HTML to readable text. Preserve line structure.

    Strategy:
      1. Decode HTML entities (&amp; -> &, &nbsp; -> space, etc.)
      2. <br> -> newline (preserves email thread structure)
      3. Strip remaining tags
      4. Collapse runs of 3+ blank lines to 2
      5. Trim trailing whitespace
    """
    if not s:
        return None
    s = html_lib.unescape(s)
    s = BR_RE.sub("\n", s)
    s = TAG_RE.sub("", s)
    s = MULTI_BLANK_RE.sub("\n\n", s)
    s = "\n".join(line.rstrip() for line in s.split("\n"))
    return s.strip() or None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30,
                    help="How many days back to pull (default 30)")
    ap.add_argument("--from-date", help="Override start date (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--tenant", choices=["CO", "UT", "SA"])
    ap.add_argument("--no-audit", action="store_true")
    args = ap.parse_args()

    if args.from_date:
        from_date = args.from_date
    else:
        from_date = (datetime.now() - timedelta(days=args.days)).strftime("%Y-%m-%d")

    print("=" * 70)
    print("MAGMANAGER ACTIVITIES ETL")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print(f"From date: {from_date}")
    print("=" * 70)

    mm = MagManagerClient()
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    started_at = datetime.now(timezone.utc)

    # ------------------------------------------------------------------
    # 0) Load client lookup
    # ------------------------------------------------------------------
    print("\n[0/4] Loading client lookup...")
    client_lookup = {}
    offset = 0
    while True:
        batch = (
            sb.table("clients")
            .select("id,mm_database,mm_customer_id")
            .not_.is_("mm_database", "null")
            .not_.is_("mm_customer_id", "null")
            .range(offset, offset + 999)
            .execute()
            .data
        )
        for c in batch:
            client_lookup[(c["mm_database"], c["mm_customer_id"])] = c["id"]
        if len(batch) < 1000:
            break
        offset += 1000
    print(f"  clients indexed: {len(client_lookup):,}")

    # ------------------------------------------------------------------
    # 1) Pull activities per tenant
    # ------------------------------------------------------------------
    print(f"\n[1/4] Pulling activities since {from_date}...")
    tenants_to_run = [d for d in DATABASES if not args.tenant
                       or (args.tenant == "CO" and d == "thehomemagcolorado")
                       or (args.tenant == "UT" and d == "thehomemagutah")
                       or (args.tenant == "SA" and d == "thehomemagsanantonio")]

    all_rows: list[dict] = []
    for db in tenants_to_run:
        page = 1
        while True:
            body = mm.get_activities_page(page=page, from_date=from_date, database_name=db)
            rows = body.get("Data") or []
            for r in rows:
                r.setdefault("DatabaseName", db)
            all_rows.extend(rows)
            print(f"  {db} page {page}: {len(rows)} rows")
            if len(rows) < 1000:
                break
            page += 1
            if page > 200:
                print("    safety stop")
                break
    print(f"  TOTAL pulled: {len(all_rows):,} activities")

    # ------------------------------------------------------------------
    # 2) Build payloads
    # ------------------------------------------------------------------
    print("\n[2/4] Building payloads...")
    payloads = []
    stats = defaultdict(Counter)
    notes_chars_before = 0
    notes_chars_after = 0
    blank_after_clean = 0
    no_client_match = 0

    seen_keys = set()
    duplicate_in_response = 0

    for a in all_rows:
        db = a["DatabaseName"]
        act_id = a.get("ActivityID")
        if act_id is None:
            stats[db]["no_activity_id"] += 1
            continue

        key = (db, act_id)
        if key in seen_keys:
            duplicate_in_response += 1
            continue
        seen_keys.add(key)

        customer_id = a.get("CustomerID")
        client_id = client_lookup.get((db, customer_id)) if customer_id is not None else None
        if customer_id is not None and client_id is None:
            no_client_match += 1

        raw_notes = a.get("Notes") or ""
        cleaned = clean_notes(raw_notes)
        notes_chars_before += len(raw_notes)
        notes_chars_after += len(cleaned or "")
        if raw_notes and not cleaned:
            blank_after_clean += 1

        payload = {
            "mm_database": db,
            "mm_activity_id": int(act_id),
            "client_id": client_id,
            "mm_customer_id": customer_id,
            "rep_id": a.get("RepID"),
            "rep_name": a.get("Rep"),
            "notes": cleaned,
            "activity_type": a.get("ActivityType"),
            "is_call": a.get("IsCall"),
            "is_email": a.get("IsEmail"),
            "is_letter": a.get("IsLetter"),
            "is_mass_email": a.get("IsMassEmail"),
            "is_system": a.get("IsSystem"),
            "date_added": a.get("DateAdded"),
            "date_completed": a.get("DateCompleted"),
            "callback_date": a.get("CallBack"),
            "meeting_date": a.get("Meeting"),
        }
        payloads.append(payload)
        stats[db]["upsert"] += 1

    print(f"  payloads to upsert: {len(payloads):,}")
    print(f"  duplicate keys in API response (deduped): {duplicate_in_response}")
    print(f"  no client match (will store with client_id=NULL): {no_client_match:,}")
    if notes_chars_before:
        savings = (notes_chars_before - notes_chars_after) * 100 // notes_chars_before
        print(f"  HTML strip: {notes_chars_before:,} -> {notes_chars_after:,} chars "
              f"({savings}% smaller)")

    # ------------------------------------------------------------------
    # 3) Upsert
    # ------------------------------------------------------------------
    if args.dry_run:
        print("\n[3/4] DRY-RUN — skipping writes")
    elif payloads:
        print(f"\n[3/4] Upserting {len(payloads):,} rows in batches of {UPSERT_BATCH_SIZE}...")
        for i in range(0, len(payloads), UPSERT_BATCH_SIZE):
            chunk = payloads[i : i + UPSERT_BATCH_SIZE]
            sb.table("client_activities").upsert(
                chunk, on_conflict="mm_database,mm_activity_id"
            ).execute()
            if (i // UPSERT_BATCH_SIZE) % 10 == 0:
                print(f"  {i + len(chunk):,} / {len(payloads):,}")
        print(f"  upserted {len(payloads):,} rows")

    # ------------------------------------------------------------------
    # 4) Audit
    # ------------------------------------------------------------------
    finished_at = datetime.now(timezone.utc)
    elapsed = (finished_at - started_at).total_seconds()
    print(f"\n[4/4] Elapsed: {elapsed:.1f}s")

    summary = {
        "mode": "dry-run" if args.dry_run else "write",
        "from_date": from_date,
        "tenants": tenants_to_run,
        "stats_by_db": {k: dict(v) for k, v in stats.items()},
        "total_pulled": len(all_rows),
        "total_upsert": len(payloads),
        "duplicate_in_response": duplicate_in_response,
        "no_client_match_count": no_client_match,
        "notes_chars_before": notes_chars_before,
        "notes_chars_after": notes_chars_after,
        "blank_after_clean": blank_after_clean,
    }

    if not args.no_audit and not args.dry_run:
        sb.table("etl_runs").insert({
            "etl_name": "mm_activities",
            "source": "magmanager_api",
            "dry_run": False,
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "success": True,
            "rows_read": len(all_rows),
            "rows_upserted_campaigns": len(payloads),
            "host": socket.gethostname(),
            "notes": summary,
        }).execute()
        print("  etl_runs row recorded")

    print("\nSummary:")
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
