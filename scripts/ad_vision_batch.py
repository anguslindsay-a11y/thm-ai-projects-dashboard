"""
Full-batch ad vision extraction — all JPGs in THM Ads folder via Haiku 4.5.

Writes one JSON line per ad to output/ad_extractions.jsonl so the run is resumable.
Re-running skips files already processed successfully.

Concurrent with threading — default 5 workers.
"""

import os
import re
import sys
import json
import base64
import time
import argparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

load_dotenv(override=True)

try:
    from anthropic import Anthropic
except ImportError:
    print("ERROR: anthropic not installed. Run: pip install anthropic")
    sys.exit(1)

API_KEY = os.getenv("ANTHROPIC_API_KEY")
if not API_KEY:
    print("ERROR: ANTHROPIC_API_KEY not set in .env")
    sys.exit(1)

MODEL = "claude-haiku-4-5-20251001"
ADS_ROOT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\THM Ads")
OUTPUT_JSONL = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\output\ad_extractions.jsonl")
OUTPUT_JSONL.parent.mkdir(exist_ok=True)

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}

EXTRACTION_PROMPT = """You are reading a print magazine advertisement. Extract the following into a JSON object with these exact keys:

{
  "headline": "the main attention-grabbing headline/tagline, if any",
  "company_name_shown": "company name as it appears in the ad",
  "tagline": "sub-headline or positioning statement",
  "primary_offer": "the main promotional offer, e.g. 'Save $500 on a new roof'",
  "secondary_offers": ["list of additional offers/promos"],
  "financing_offer": "any financing terms mentioned, e.g. '0% for 60 months'",
  "cta": "the call-to-action text, e.g. 'Call for FREE estimate'",
  "phone_numbers": ["list of phone numbers shown"],
  "website": "website URL if shown",
  "services_listed": ["bulleted/listed services or product categories"],
  "urgency_markers": ["phrases creating urgency, e.g. 'Limited time', 'This month only'"],
  "years_in_business": "if stated, e.g. 'Since 1985' or '30 years of experience'",
  "guarantees": ["warranties/guarantees mentioned"],
  "credentials": ["BBB ratings, Google stars, certifications, awards"],
  "disclaimers": "fine print/disclaimers if readable",
  "visual_style_notes": "brief description of dominant colors and layout style"
}

If a field isn't present or readable, use null (for strings) or [] (for arrays).
Return ONLY the JSON object, no prose before or after."""


def parse_filename(filename: str) -> dict:
    """Parse {Client}-THM{MK}-{Size}-{Zone}-{Issue}.jpg variants.
    MK = CO/UT/TX/SA/AU market prefix.
    Zone can contain & for combined zones (e.g. AUN&S, SAE&W).
    Size can be 1-3 chars (F, Fb, BC, BCB, etc.)."""
    base = Path(filename).stem
    # Primary pattern
    m = re.match(r"^(.+?)-THM([A-Z]{2})-([A-Za-z]+)[-\s]+([A-Z&]+)(?:-[A-Za-z0-9]+)?-(\d{4}s?)$", base)
    if m:
        return {"client_raw": m.group(1), "market": m.group(2), "size_code": m.group(3),
                "zone_code": m.group(4), "issue_code": m.group(5)}
    # Fallback: size might be missing entirely (seen in TX)
    m = re.match(r"^(.+?)-THM([A-Z]{2})-([A-Z&]+)-(\d{4}s?)$", base)
    if m:
        return {"client_raw": m.group(1), "market": m.group(2), "size_code": None,
                "zone_code": m.group(3), "issue_code": m.group(4)}
    return {"client_raw": base, "market": None, "size_code": None, "zone_code": None, "issue_code": None}


def encode_image(path: Path) -> tuple[str, str]:
    ext = path.suffix.lower()
    media = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}.get(ext, "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media


def extract_ad(client: Anthropic, image_path: Path, max_retries: int = 3) -> dict:
    data, media = encode_image(image_path)
    last_err = None
    for attempt in range(max_retries):
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=1500,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media, "data": data}},
                        {"type": "text", "text": EXTRACTION_PROMPT},
                    ],
                }],
            )
            text = resp.content[0].text.strip()
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
                wait = 2 ** attempt
                time.sleep(wait)
    raise last_err


def load_done_set() -> set[str]:
    """Return set of relative paths already processed (no error)."""
    done = set()
    if not OUTPUT_JSONL.exists():
        return done
    with open(OUTPUT_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
                if rec.get("relpath") and not rec.get("error"):
                    done.add(rec["relpath"])
            except json.JSONDecodeError:
                continue
    return done


def discover_ads() -> list[Path]:
    """All image files under ADS_ROOT, including subfolders."""
    return sorted(p for p in ADS_ROOT.rglob("*") if p.suffix.lower() in IMAGE_EXTS)


def process_one(client: Anthropic, path: Path) -> dict:
    relpath = str(path.relative_to(ADS_ROOT)).replace("\\", "/")
    meta = parse_filename(path.name)
    meta["relpath"] = relpath
    meta["folder"] = str(path.parent.relative_to(ADS_ROOT)).replace("\\", "/")
    try:
        result = extract_ad(client, path)
        return {
            "relpath": relpath,
            "filename": path.name,
            "meta": meta,
            "parsed": result["parsed"],
            "input_tokens": result["input_tokens"],
            "output_tokens": result["output_tokens"],
            "model": MODEL,
        }
    except Exception as e:
        return {"relpath": relpath, "filename": path.name, "meta": meta, "error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5, help="Concurrent workers (default 5)")
    ap.add_argument("--limit", type=int, default=None, help="Stop after N ads (for testing)")
    args = ap.parse_args()

    done = load_done_set()
    all_ads = discover_ads()
    todo = [p for p in all_ads if str(p.relative_to(ADS_ROOT)).replace("\\", "/") not in done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Total ads:    {len(all_ads)}")
    print(f"Already done: {len(done)}")
    print(f"To process:   {len(todo)}")
    print(f"Workers:      {args.workers}")
    print(f"Model:        {MODEL}")
    if not todo:
        print("Nothing to do.")
        return

    anthropic_client = Anthropic(api_key=API_KEY)
    start = time.time()
    processed = errors = 0
    total_in = total_out = 0

    # Append-only write
    with open(OUTPUT_JSONL, "a", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(process_one, anthropic_client, p): p for p in todo}
            for fut in as_completed(futures):
                result = fut.result()
                out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
                out_f.flush()
                processed += 1
                if "error" in result:
                    errors += 1
                    status = "ERR"
                else:
                    total_in += result.get("input_tokens", 0)
                    total_out += result.get("output_tokens", 0)
                    status = "OK "
                if processed % 25 == 0 or processed == len(todo):
                    elapsed = time.time() - start
                    rate = processed / elapsed if elapsed > 0 else 0
                    eta = (len(todo) - processed) / rate if rate > 0 else 0
                    cost = total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0
                    print(f"  [{processed:4}/{len(todo)}] {status} err={errors} rate={rate:.1f}/s eta={eta/60:.1f}min cost=${cost:.2f}")

    elapsed = time.time() - start
    cost = total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0
    print(f"\nDone in {elapsed/60:.1f} min. Processed {processed}, errors {errors}. Cost: ${cost:.4f}")
    print(f"Output: {OUTPUT_JSONL}")


if __name__ == "__main__":
    main()
