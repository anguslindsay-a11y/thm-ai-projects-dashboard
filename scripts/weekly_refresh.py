"""
Weekly Supabase Data Refresh

Runs all import scripts in sequence to refresh the data hub.
Drop updated export files into the data/ folder, then run this script.

Usage:
  python scripts/weekly_refresh.py                  # Run all imports
  python scripts/weekly_refresh.py --dry-run        # Preview only (no writes)
  python scripts/weekly_refresh.py --skip calls     # Skip CallRail ETL
  python scripts/weekly_refresh.py --only orders    # Run only orders import

Steps (in order):
  1. CallRail calls + tags (API, last 14 days)
  2. Orders (Waterfall spreadsheet)
  3. QR Scans (Uniqode spreadsheet)
  4. Email Campaigns (Inbox Advantage spreadsheet)
  5. Ad Placements (CO + UT spreadsheets)
"""

import sys
import subprocess
import argparse
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"

# Use venv python if available, otherwise system python
PYTHON = str(VENV_PYTHON) if VENV_PYTHON.exists() else sys.executable

STEPS = [
    {
        "name": "calls",
        "label": "CallRail Calls + Tags",
        "script": "etl/etl_callrail.py",
        "args": ["--days", "14"],
        "dry_run_arg": "--dry-run",
    },
    {
        "name": "orders",
        "label": "MagManager Orders (Waterfall)",
        "script": "setup/import_orders.py",
        "args": [],
        "dry_run_arg": "--dry-run",
    },
    {
        "name": "qr",
        "label": "Uniqode QR Scans",
        "script": "setup/import_uniqode_csv.py",
        "args": [],
        "dry_run_arg": "--dry-run",
    },
    {
        "name": "email",
        "label": "Inbox Advantage Email Campaigns",
        "script": "setup/import_inbox_advantage.py",
        "args": [],
        "dry_run_arg": "--dry-run",
    },
    {
        "name": "ads",
        "label": "Ad Placements (CO + UT)",
        "script": "setup/import_ad_placements.py",
        "args": [],
        "dry_run_arg": "--dry-run",
    },
    {
        "name": "runsheets",
        "label": "Monday Runsheets",
        "script": "setup/import_runsheets.py",
        "args": [],
        "dry_run_arg": "--dry-run",
    },
]


def run_step(step, dry_run=False):
    """Run a single import step. Returns True on success."""
    cmd = [PYTHON, str(PROJECT_ROOT / step["script"])] + step["args"]
    if dry_run:
        cmd.append(step["dry_run_arg"])

    print(f"\n{'='*60}")
    print(f"  STEP: {step['label']}")
    print(f"  Command: {' '.join(cmd)}")
    print(f"{'='*60}\n")

    start = time.time()
    result = subprocess.run(cmd, cwd=str(PROJECT_ROOT))
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  -> {step['label']} completed in {elapsed:.1f}s")
        return True
    else:
        print(f"\n  -> {step['label']} FAILED (exit code {result.returncode}) after {elapsed:.1f}s")
        return False


def main():
    parser = argparse.ArgumentParser(description="Weekly Supabase data refresh")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    parser.add_argument("--skip", nargs="+", choices=[s["name"] for s in STEPS],
                        help="Steps to skip (e.g., --skip calls ads)")
    parser.add_argument("--only", nargs="+", choices=[s["name"] for s in STEPS],
                        help="Run only these steps (e.g., --only orders qr)")
    args = parser.parse_args()

    skip = set(args.skip or [])
    only = set(args.only or [])

    steps_to_run = []
    for step in STEPS:
        if only and step["name"] not in only:
            continue
        if step["name"] in skip:
            continue
        steps_to_run.append(step)

    if not steps_to_run:
        print("No steps to run!")
        return

    mode = "DRY RUN" if args.dry_run else "LIVE"
    print(f"\n{'#'*60}")
    print(f"  THM Data Hub — Weekly Refresh ({mode})")
    print(f"  Steps: {', '.join(s['label'] for s in steps_to_run)}")
    print(f"{'#'*60}")

    results = {}
    start_total = time.time()

    for step in steps_to_run:
        success = run_step(step, dry_run=args.dry_run)
        results[step["label"]] = success
        if not success:
            print(f"\n  WARNING: {step['label']} failed. Continuing with remaining steps...")

    elapsed_total = time.time() - start_total

    print(f"\n{'#'*60}")
    print(f"  REFRESH COMPLETE — {elapsed_total:.1f}s total")
    print(f"{'#'*60}")
    for label, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  [{status:6s}] {label}")
    print(f"{'#'*60}\n")


if __name__ == "__main__":
    main()
