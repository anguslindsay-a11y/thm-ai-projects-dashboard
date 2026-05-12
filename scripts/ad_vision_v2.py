"""Ad vision extraction v2 — cloud-native, expanded prompt.

Reads ads from Supabase Storage (bucket: client_ads), runs Haiku 4.5 vision,
writes the extraction back to client_ads.extraction. Concurrent workers.

What's new vs v1 (scripts/ad_vision_batch.py):
  - Reads from Supabase Storage instead of local THM Ads/ folder
  - Writes directly to client_ads.extraction (no jsonl loader step)
  - Expanded prompt with 4 new fields:
      industry_categories  — high-level WHAT the company does (taxonomy)
      services_offered     — granular services within categories
      brand_partners       — manufacturer dealerships
      service_areas        — geographic mentions
  - Strengthened offers extraction (multiple offers always captured)
  - Schema version tag (_version: 2) on every extraction so future runs
    can detect v1 leftovers

Selection: targets client_ads by issue_code pattern (default: 2026 = '26%').
By default skips ads that already have v2 extraction (resumable). With
--reprocess-existing, re-extracts everything matching the pattern.

Audit: appends one JSONL row per ad to output/ad_vision_v2_run.jsonl.
DB is canonical; jsonl is for debugging/re-load.

Usage:
  python scripts/ad_vision_v2.py --issue-pattern '26%'              # default
  python scripts/ad_vision_v2.py --issue-pattern '26%' --reprocess-existing
  python scripts/ad_vision_v2.py --limit 10 --workers 3            # smoke test
  python scripts/ad_vision_v2.py --dry-run --limit 5               # no DB writes
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(override=True)

try:
    from anthropic import Anthropic
except ImportError:
    print("ERROR: anthropic not installed. Run: pip install anthropic")
    sys.exit(1)

from supabase import create_client

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

if not (SUPABASE_URL and SUPABASE_KEY and ANTHROPIC_API_KEY):
    print("ERROR: missing SUPABASE_URL / SUPABASE_KEY / ANTHROPIC_API_KEY in .env")
    sys.exit(1)

MODEL = "claude-haiku-4-5-20251001"
STORAGE_BUCKET = "client_ads"
EXTRACTION_VERSION = 2

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
JSONL_PATH = OUTPUT_DIR / "ad_vision_v2_run.jsonl"

# Haiku 4.5 pricing per million tokens (rough; vision images are billed as input tokens)
INPUT_COST_PER_M = 1.0
OUTPUT_COST_PER_M = 5.0


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
EXTRACTION_PROMPT = """You are reading a print magazine advertisement for a home-services company. Extract the following into a single JSON object with EXACTLY these keys. Return ONLY the JSON object — no prose, no markdown fences.

{
  "headline": "the main attention-grabbing headline/tagline, if any",
  "company_name_shown": "company name as it appears in the ad",
  "tagline": "sub-headline or positioning statement",
  "primary_offer": "the most prominent promotional offer, e.g. 'Save $500 on a new roof'",
  "secondary_offers": ["EVERY additional offer, even small ones — discount amounts, free add-ons, bundles. Include amount + what it applies to."],
  "financing_offer": "any financing terms mentioned, e.g. '0% for 60 months'",
  "cta": "the call-to-action text, e.g. 'Call for FREE estimate'",
  "phone_numbers": ["list of phone numbers shown"],
  "website": "website URL if shown",
  "industry_categories": ["1-3 high-level industries this company is in. Use canonical terms from this list when applicable: Roofing, Siding & Gutters, Windows, Doors, Garages, Painting, Decks & Outdoor Living, Awnings & Patio Covers, Landscaping, Tree Services, Concrete Pavers & Driveways, Fences & Gates, Pools & Spas, Home Remodeling, Flooring, HVAC & Plumbing, Electrical & Lighting, Solar & Energy, Cleaning Services, Restoration & Junk Removal, Handyman Services, Pest & Wildlife, Construction & Design, Appliances, Furniture, Foundation Repair. If none fit, invent a clear short term."],
  "services_offered": ["granular services/products within those categories — e.g. 'Roof Replacement', 'Gutter Installation', 'Smart Home Automation'. Different from feature bullets — these are WHAT they sell."],
  "services_listed": ["bulleted/listed feature text or product callouts AS WRITTEN in the ad — kept for backward compatibility"],
  "brand_partners": ["manufacturer dealerships or authorized installer mentions — e.g. 'Andersen Windows', 'GAF Master Elite', 'Trex Pro'"],
  "service_areas": ["geographic mentions of where they serve — e.g. 'Denver metro', 'Northern Colorado', 'Boulder County', 'Austin & San Antonio'"],
  "urgency_markers": ["phrases creating urgency, e.g. 'Limited time', 'This month only'"],
  "years_in_business": "if stated, e.g. 'Since 1985' or '30 years of experience'",
  "guarantees": ["warranties/guarantees mentioned"],
  "credentials": ["BBB ratings, Google stars, certifications, awards — keep brief"],
  "disclaimers": "fine print/disclaimers if readable",
  "visual_style_notes": "brief description of dominant colors and layout style"
}

Rules:
- If a field isn't present or readable: use null for strings, [] for arrays.
- For multi-business clients (e.g. a company doing both windows AND patio covers), list BOTH in industry_categories and BOTH families in services_offered.
- secondary_offers is a HARD ASK: if you see two or more distinct offers in the ad, ALL of them must appear (the primary one in primary_offer, the rest in secondary_offers).
- industry_categories must be 1-3 entries. If you can only confidently identify one industry, just one. Don't pad."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def encode_image_bytes(data: bytes, media_type: str) -> str:
    return base64.standard_b64encode(data).decode()


def media_type_for(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")


def call_haiku(client: Anthropic, image_bytes: bytes, media_type: str,
               max_retries: int = 3) -> dict:
    data_b64 = encode_image_bytes(image_bytes, media_type)
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64",
                                                       "media_type": media_type,
                                                       "data": data_b64}},
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }],
            )
            text = resp.content[0].text.strip()
            # Strip code fences if model added them despite instructions
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = {"_raw_response": text, "_parse_error": True}
            return {
                "parsed": parsed,
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }
        except Exception as e:
            last_err = e
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    raise last_err


def download_from_storage(sb, storage_path: str) -> bytes:
    """Download a file from the client_ads bucket."""
    return sb.storage.from_(STORAGE_BUCKET).download(storage_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--issue-pattern", default="26%",
                    help="SQL LIKE pattern on client_ads.issue_code (default '26%%' = all 2026)")
    ap.add_argument("--reprocess-existing", action="store_true",
                    help="Re-extract ads that already have v2 extraction")
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap rows for testing")
    ap.add_argument("--dry-run", action="store_true",
                    help="Run extraction but skip DB write")
    args = ap.parse_args()

    print("=" * 72)
    print("AD VISION v2 — cloud-native extraction")
    print(f"Model:             {MODEL}")
    print(f"Issue pattern:     {args.issue_pattern}")
    print(f"Reprocess existing: {args.reprocess_existing}")
    print(f"Workers:           {args.workers}")
    print(f"Mode:              {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print("=" * 72)

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    anthropic_client = Anthropic(api_key=ANTHROPIC_API_KEY)

    # -----------------------------------------------------------------
    # Discover ads to process
    # -----------------------------------------------------------------
    print("\nLoading client_ads rows...")
    rows = []
    offset = 0
    while True:
        batch = (
            sb.table("client_ads")
            .select("id, filename_original, storage_path, issue_code, extraction")
            .like("issue_code", args.issue_pattern)
            .range(offset, offset + 999)
            .execute()
            .data
        )
        rows.extend(batch)
        if len(batch) < 1000:
            break
        offset += 1000

    total_matching_pattern = len(rows)

    # Filter: skip ads that already have v2 extraction (unless --reprocess-existing)
    if not args.reprocess_existing:
        before = len(rows)
        rows = [
            r for r in rows
            if not r.get("extraction")
            or r["extraction"].get("_version") != EXTRACTION_VERSION
        ]
        print(f"  matching issue_pattern: {before:,}")
        print(f"  skipping (already v2):  {before - len(rows):,}")

    if args.limit:
        rows = rows[: args.limit]

    print(f"  to process:             {len(rows):,}")
    if not rows:
        print("Nothing to do.")
        return

    # -----------------------------------------------------------------
    # Process
    # -----------------------------------------------------------------
    started = time.time()
    write_lock = Lock()
    counters = {"ok": 0, "err": 0, "in_tok": 0, "out_tok": 0}

    def process_one(row: dict) -> dict:
        ad_id = row["id"]
        storage_path = row.get("storage_path")
        if not storage_path:
            return {"ad_id": ad_id, "error": "no storage_path", "filename": row.get("filename_original")}
        try:
            img_bytes = download_from_storage(sb, storage_path)
        except Exception as e:
            return {"ad_id": ad_id, "error": f"storage_download: {e}",
                    "filename": row.get("filename_original")}

        try:
            result = call_haiku(anthropic_client, img_bytes,
                                 media_type_for(row.get("filename_original") or ""))
        except Exception as e:
            return {"ad_id": ad_id, "error": f"haiku_call: {e}",
                    "filename": row.get("filename_original")}

        extraction = result["parsed"]
        # Stamp version + timestamp
        extraction["_version"] = EXTRACTION_VERSION
        extraction["_extracted_at"] = datetime.now(timezone.utc).isoformat()
        extraction["_model"] = MODEL

        # Write to DB (unless dry-run)
        if not args.dry_run:
            try:
                sb.table("client_ads").update({"extraction": extraction}).eq("id", ad_id).execute()
            except Exception as e:
                return {"ad_id": ad_id, "error": f"db_update: {e}",
                        "filename": row.get("filename_original"),
                        "parsed": extraction}

        return {
            "ad_id": ad_id,
            "filename": row.get("filename_original"),
            "issue_code": row.get("issue_code"),
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "extraction": extraction,
        }

    with open(JSONL_PATH, "a", encoding="utf-8") as jsonl_f:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_one, r): r for r in rows}
            for i, fut in enumerate(as_completed(futures), start=1):
                result = fut.result()
                with write_lock:
                    jsonl_f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
                    jsonl_f.flush()
                    if "error" in result:
                        counters["err"] += 1
                        status = "ERR"
                    else:
                        counters["ok"] += 1
                        counters["in_tok"] += result.get("input_tokens", 0)
                        counters["out_tok"] += result.get("output_tokens", 0)
                        status = "OK "

                if i % 25 == 0 or i == len(rows):
                    elapsed = time.time() - started
                    rate = i / elapsed if elapsed > 0 else 0
                    eta = (len(rows) - i) / rate if rate > 0 else 0
                    cost = (counters["in_tok"] / 1e6 * INPUT_COST_PER_M
                             + counters["out_tok"] / 1e6 * OUTPUT_COST_PER_M)
                    print(f"  [{i:5}/{len(rows)}] {status} ok={counters['ok']} err={counters['err']} "
                          f"rate={rate:.1f}/s eta={eta/60:.1f}min cost=${cost:.2f}",
                          flush=True)

    elapsed = time.time() - started
    cost = (counters["in_tok"] / 1e6 * INPUT_COST_PER_M
             + counters["out_tok"] / 1e6 * OUTPUT_COST_PER_M)

    print()
    print("=" * 72)
    print(f"Processed:    {counters['ok']:,}")
    print(f"Errors:       {counters['err']:,}")
    print(f"Input tokens: {counters['in_tok']:,}")
    print(f"Output tokens:{counters['out_tok']:,}")
    print(f"Total cost:   ${cost:.4f}")
    print(f"Elapsed:      {elapsed/60:.1f} min")
    print(f"JSONL log:    {JSONL_PATH}")
    if args.dry_run:
        print("DRY-RUN — no DB writes")
    print("=" * 72)


if __name__ == "__main__":
    main()
