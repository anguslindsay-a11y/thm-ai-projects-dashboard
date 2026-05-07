"""
Ad Vision Pilot — extract offers/CTAs/phone/etc from 20 sample ads via Haiku 4.5.

Outputs a single JSON file with one entry per ad so we can review schema/quality
before scaling to all 1,877 ads.

Requires ANTHROPIC_API_KEY in .env.
"""

import os
import re
import sys
import json
import base64
import time
from pathlib import Path
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
    print("Add this line to .env:  ANTHROPIC_API_KEY=sk-ant-...")
    sys.exit(1)

MODEL = "claude-haiku-4-5-20251001"

ADS_ROOT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\THM Ads")
OUTPUT = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\output\ad_vision_pilot.json")

# Pilot sample — varied sizes, zones, categories, all from April 2026 for freshness
SAMPLE_FILES = [
    "THM Colorado 2026-04/A2Z Builders-THMCO-F-EPC-2604.jpg",
    "THM Colorado 2026-04/ApexCleanAir-THMCO-F-NCO-2604.jpg",
    "THM Colorado 2026-04/Affordable Plumbing Heating Electric-THMCO-F-EPC-2604.jpg",
    "THM Colorado 2026-04/All Seasons Flooring-THMCO-F-EPC-2604.jpg",
    "THM Colorado 2026-04/AroundtheHouse-EclipseAwnings-THMCO-F-EPC-2604.jpg",
    "THM Colorado 2026-04/5 Star Roofing-THMCO-H-NCO-2604.jpg",
    "THM Colorado 2026-04/A Better Edge-Curbing-THMCO-H-EPC-2604.jpg",
    "THM Colorado 2026-04/AboveParr-THMCO-H-NDN-2604.jpg",
    "THM Colorado 2026-04/AccessGarageDoors-THMCO-H-NCO-2604.jpg",
    "THM Colorado 2026-04/All American Tree Plus-THMCO-H-NDN-2604.jpg",
    "THM Colorado 2026-04/AspenSprinklers-THMCO-H-NCO-2604.jpg",
    "THM Colorado 2026-04/BasementFinishers-THMCO-H-SDN-2604.jpg",
    "THM Colorado 2026-04/BlindMan-THMCO-H-EPC-2604.jpg",
    "THM Colorado 2026-04/All Concrete Works-THMCO-Q-SDN-2604.jpg",
    "THM Colorado 2026-04/Baluster Company-THMCO-Q-NDN-2604.jpg",
    "THM Colorado 2026-04/ABD Associates in Building-THMCO-Fb-NCO-2604.jpg",
    "THM Colorado 2026-04/AMC Painting-THMCO-Fb-NCO-2604.jpg",
    "THM Colorado 2026-04/AdvancedCurbDesign-THMCO-Fb-NCO-2604.jpg",
    "THM Colorado 2026-04/Bath Landscape-THMCO-Fb-NCO-2604.jpg",
    "THM Colorado 2026-04/AnywhereRooter-ActionHVAC-THMCO-D-SDN-2604.jpg",
]

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
  "disclaimers": "fine print/disclaimers if readable",
  "visual_style_notes": "brief description of dominant colors and layout style"
}

If a field isn't present or readable, use null (for strings) or [] (for arrays).
Return ONLY the JSON object, no prose before or after."""


def parse_filename(filename: str) -> dict:
    """Parse {Client}-THMCO-{Size}-{Zone}-{Issue}.jpg"""
    base = Path(filename).stem
    # Handle XBO cross-book variants too
    m = re.match(r"^(.+?)-THMCO-([A-Za-z]+)-([A-Z]+)(?:-[A-Za-z]*)?-(\d{4}s?)$", base)
    if m:
        return {"client_raw": m.group(1), "size_code": m.group(2), "zone_code": m.group(3), "issue_code": m.group(4)}
    return {"client_raw": base, "size_code": None, "zone_code": None, "issue_code": None}


def encode_image(path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type)."""
    ext = path.suffix.lower()
    media = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}.get(ext.lstrip("."), "image/jpeg")
    with open(path, "rb") as f:
        data = base64.standard_b64encode(f.read()).decode()
    return data, media


def extract_ad(client: Anthropic, image_path: Path) -> dict:
    data, media = encode_image(image_path)
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
    # Strip markdown code fences if present
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


def main():
    client = Anthropic(api_key=API_KEY)
    results = []
    total_in = total_out = 0
    start = time.time()

    for idx, rel in enumerate(SAMPLE_FILES, 1):
        path = ADS_ROOT / rel
        if not path.exists():
            print(f"  [{idx}/{len(SAMPLE_FILES)}] MISSING: {rel}")
            continue
        meta = parse_filename(path.name)
        print(f"  [{idx}/{len(SAMPLE_FILES)}] {meta['client_raw'][:40]:40s} {meta.get('size_code'):3s} {meta.get('zone_code'):3s}", end=" ... ", flush=True)
        t0 = time.time()
        try:
            result = extract_ad(client, path)
            total_in += result["input_tokens"]
            total_out += result["output_tokens"]
            print(f"{time.time()-t0:.1f}s  in={result['input_tokens']} out={result['output_tokens']}")
            results.append({
                "filename": path.name,
                "meta": meta,
                **result,
            })
        except Exception as e:
            print(f"ERROR: {e}")
            results.append({"filename": path.name, "meta": meta, "error": str(e)})

    OUTPUT.parent.mkdir(exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump({
            "model": MODEL,
            "total_ads": len(results),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            # Haiku 4.5 pricing: $1/M input, $5/M output
            "estimated_cost_usd": round(total_in / 1e6 * 1.0 + total_out / 1e6 * 5.0, 4),
            "elapsed_seconds": round(time.time() - start, 1),
            "results": results,
        }, f, indent=2)

    print(f"\nSaved: {OUTPUT}")
    print(f"Total in={total_in} out={total_out}  est cost ${total_in/1e6*1.0 + total_out/1e6*5.0:.4f}")


if __name__ == "__main__":
    main()
