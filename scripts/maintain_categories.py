"""
Weekly maintenance: classify any new clients that don't have category tags yet.

Reuses scripts/auto_classify_clients.py — running it WITHOUT --reclassify means
it skips clients with manual tags AND clients already classified by LLM.
Result: only NEW clients get classified each week.

Also re-runs the seed (idempotent) so any new aliases or categories added by
hand to the seed file get applied.

Usage (run weekly via Task Scheduler):
  python scripts/maintain_categories.py

Optional flags:
  --skip-classify    Just run the seed, don't classify
  --dry-run          Preview the count of new clients only
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def count_unclassified(sb) -> int:
    """Count real clients with at least one signal but no client_categories row."""
    page = 0
    real_ids = set()
    while True:
        chunk = (sb.table("clients")
                 .select("id,call_tracking_notes,category")
                 .eq("is_mapping_stub", False)
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for r in chunk:
            has_signal = bool((r.get("call_tracking_notes") or "").strip()) or bool((r.get("category") or "").strip())
            if has_signal:
                real_ids.add(r["id"])
        if len(chunk) < 1000:
            break
        page += 1

    classified = set()
    page = 0
    while True:
        chunk = (sb.table("client_categories").select("client_id")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for r in chunk:
            classified.add(r["client_id"])
        if len(chunk) < 1000:
            break
        page += 1
    return len(real_ids - classified)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-classify", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Step 1: Re-run seed (idempotent — adds new categories/aliases if any)
    print("Step 1: Refreshing category tree + aliases (idempotent)...")
    result = subprocess.run(
        [sys.executable, str(REPO / "setup" / "seed_categories.py")],
        capture_output=True, text=True, cwd=REPO,
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print("seed_categories.py failed:", result.stderr)
        sys.exit(1)

    # Step 2: How many unclassified clients exist?
    n = count_unclassified(sb)
    print(f"\nStep 2: {n} unclassified real clients with at least one signal")

    if n == 0:
        print("Nothing to classify. Done.")
        return

    if args.dry_run:
        print("--dry-run set; not invoking classifier")
        return

    if args.skip_classify:
        print("--skip-classify set; not invoking classifier")
        return

    # Step 3: Run classifier (without --reclassify, so only NEW clients are processed)
    print("\nStep 3: Classifying new clients...")
    result = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "auto_classify_clients.py")],
        cwd=REPO,
    )
    if result.returncode != 0:
        print("auto_classify_clients.py failed")
        sys.exit(1)

    print("\nMaintenance complete.")


if __name__ == "__main__":
    main()
