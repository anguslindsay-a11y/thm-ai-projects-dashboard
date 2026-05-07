"""
Phase 3 — Multi-signal LLM classification of clients into the canonical category tree.

Builds an evidence bundle per client (name + ads + CT notes + orders + legacy text),
sends it to Haiku 4.5 with the full taxonomy in a cached system prompt, and writes
the structured response to client_categories (source='llm_auto') + classification_log.

Idempotent / resumable:
  - Skips clients with any source='manual' tag (user already reviewed)
  - Skips clients already classified with source='llm_auto' unless --reclassify

Usage:
  python scripts/auto_classify_clients.py --dry-run     # 5-client preview
  python scripts/auto_classify_clients.py               # full run
  python scripts/auto_classify_clients.py --limit 100   # cap to 100
  python scripts/auto_classify_clients.py --reclassify  # re-run even on already-classified
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import local
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv(override=True)

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("ERROR: anthropic not installed. Run: pip install anthropic")

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY")
if not ANTHROPIC_KEY:
    sys.exit("ERROR: ANTHROPIC_API_KEY not set in .env")

MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 1500
WORKERS = 8

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)
JSONL_PATH = OUTPUT_DIR / "classification_results.jsonl"

# ---------- Per-thread Supabase clients ----------
_thread_local = local()

def _sb():
    if not hasattr(_thread_local, "client"):
        _thread_local.client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _thread_local.client

def _ant():
    if not hasattr(_thread_local, "anth"):
        _thread_local.anth = Anthropic(api_key=ANTHROPIC_KEY)
    return _thread_local.anth


# ---------- Build the taxonomy block for the system prompt ----------
def build_taxonomy_text(sb) -> str:
    """Build a flat 2-tier taxonomy listing for the prompt: top-level + subcategories."""
    rows = sb.table("categories").select("id,name,slug,level,parent_id,sort_order").execute().data
    children: dict[str, list[dict]] = {}
    for r in rows:
        children.setdefault(r["parent_id"] or "ROOT", []).append(r)
    for k in children:
        children[k].sort(key=lambda x: (x["sort_order"], x["name"]))

    lines = []
    for cat in children.get("ROOT", []):
        sub_pairs = [f"{s['name']} (slug: {s['slug']})" for s in children.get(cat["id"], [])]
        lines.append(f"- TOP: {cat['name']}  (slug: {cat['slug']})")
        if sub_pairs:
            for s in sub_pairs:
                lines.append(f"    sub: {s}")
    return "\n".join(lines)


# ---------- Pull evidence per client ----------
def fetch_evidence(sb, client_ids: list[str]) -> dict[str, dict]:
    """Return {client_id: evidence_bundle}."""
    if not client_ids:
        return {}
    out: dict[str, dict] = {cid: {"client_id": cid} for cid in client_ids}

    # Clients (name + legacy + CT notes + status)
    page = 0
    BATCH = 200
    while page * BATCH < len(client_ids):
        ids = client_ids[page * BATCH:(page + 1) * BATCH]
        rows = sb.table("clients").select(
            "id,name,category,call_tracking_notes,status"
        ).in_("id", ids).execute().data
        for r in rows:
            ev = out[r["id"]]
            ev["name"] = r["name"]
            ev["legacy_category"] = r.get("category")
            ev["call_tracking_notes"] = (r.get("call_tracking_notes") or "")[:1500]
            ev["status"] = r.get("status")
        page += 1

    # Ads (extraction subset)
    page = 0
    while True:
        chunk = (sb.table("client_ads")
                 .select("client_id,headline,primary_offer,extraction")
                 .in_("client_id", client_ids)
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for ad in chunk:
            ext = ad.get("extraction") or {}
            ad_summary = {
                "headline": ad.get("headline") or ext.get("headline"),
                "services_listed": ext.get("services_listed"),
                "primary_offer": ad.get("primary_offer") or ext.get("primary_offer"),
                "tagline": ext.get("tagline"),
            }
            # Drop empty fields
            ad_summary = {k: v for k, v in ad_summary.items() if v}
            if ad_summary:
                out[ad["client_id"]].setdefault("ads", []).append(ad_summary)
        if len(chunk) < 1000:
            break
        page += 1

    # Cap ads per client at 5 to keep tokens reasonable
    for ev in out.values():
        if "ads" in ev and len(ev["ads"]) > 5:
            ev["ads"] = ev["ads"][:5]

    # CallRail labels
    plat = (sb.table("client_platform_ids").select("client_id,external_name")
            .eq("platform", "callrail").in_("client_id", client_ids).execute().data)
    for r in plat:
        out[r["client_id"]].setdefault("callrail_labels", []).append(r["external_name"])

    # Distinct order products
    page = 0
    products_by_client: dict[str, set] = {}
    while True:
        chunk = (sb.table("orders").select("client_id,product")
                 .in_("client_id", client_ids).range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for r in chunk:
            if r.get("product"):
                products_by_client.setdefault(r["client_id"], set()).add(r["product"])
        if len(chunk) < 1000:
            break
        page += 1
    for cid, prods in products_by_client.items():
        out[cid]["order_products_sample"] = sorted(prods)[:15]

    return out


# ---------- LLM call ----------
SYSTEM_TEMPLATE = """You are a categorization expert for THM Media, a home-improvement magazine ad agency. Your job is to classify clients into a canonical 2-tier category tree based on multi-signal evidence (their name, ads, call-tracking notes, order products, and legacy category text).

CANONICAL TAXONOMY (top-level categories with their subcategories — only return slugs from this list, never invent new ones):

{TAXONOMY}

INSTRUCTIONS:
1. The strongest signal is the ad's `services_listed` field — it literally lists what the company does.
2. The second-strongest signal is `call_tracking_notes`: parenthetical labels like "(Window Cleaning)", "(Lights)", "(Roofing)", "(Window Depot)" indicate the trade for that phone number. Section headers like "*WINDOWS*" or "*LIGHTS*" indicate a business line.
3. Legacy category text is unreliable — prior tagging was inconsistent. Treat it as a hint, not authority. If the ads/notes contradict the legacy text, trust the ads/notes.
4. **Always pick exactly one TOP-LEVEL category as the primary tag.** Top-level categories are level=1. Then optionally pick 1-3 subcategory tags (level=2) under it for finer detail.
5. Multi-trade specialists get multiple top-level tags. E.g., a company that does window cleaning AND lighting installation gets BOTH "Cleaning Services" (primary) AND "Electrical & Lighting" (secondary). Each top-level tag can also include relevant subcategory tags.
6. **DO NOT tag handyman / general contractor / design-build companies in every specialty their ad mentions.** If the company is primarily a handyman or GC, give them ONE top-level tag (Handyman Services or Construction & Design) and STOP. Do not add secondary tags for plumbing/electrical/painting/etc. just because the ad lists those services.
7. Set is_primary=true for ONLY ONE category — the dominant trade per evidence weight.
8. Confidence: 0.95 = ad+notes both clearly indicate, 0.80 = one strong signal, 0.60 = inferred from name/legacy only, 0.40 = guessing.

CRITICAL DISTINCTIONS:
- Window cleaning ≠ window installation. "Windows" is for installers/replacement. "Cleaning Services" with subcategory "Window Cleaning" is for cleaners. Ad headline "WE CLEAN WINDOWS!" → Cleaning Services.
- Garage Doors are under "Garages" (top-level), not under "Doors". Doors is for entry/patio/glass/interior doors.
- Concrete/Pavers/Driveways is its own top-level, NOT under Landscaping.
- HVAC, Plumbing, Water Heaters, Water Treatment all roll up to "HVAC & Plumbing" top-level.
- Electrical/Lighting is its own top-level, separate from HVAC & Plumbing.
- Window Wells are a subcategory under Windows (not a separate top-level).
- Foundation Repair is its own top-level, separate from Home Remodeling. Companies with "Foundation" / "Groundworks" / "GWRK" / "Ram Jack" in name are Foundation Repair.
- Kitchen & Bath, Basement Finishing, Whole-Home Remodel, Cabinetry are all subcategories under "Home Remodeling".

OUTPUT FORMAT (JSON only, no prose):
{{
  "tags": [
    {{"slug": "top-level-slug", "is_primary": true, "confidence": 0.95}},
    {{"slug": "subcategory-slug", "is_primary": false, "confidence": 0.90}}
  ],
  "reasoning": "1-2 sentences citing specific evidence from the bundle"
}}"""


def classify_client(evidence: dict, system_prompt: str) -> dict:
    """Send one client's bundle to Haiku, return parsed JSON."""
    user_msg = json.dumps(evidence, default=str)[:8000]  # safety cap
    last_err = None
    for attempt in range(3):
        try:
            resp = _ant().messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": user_msg}],
            )
            text = resp.content[0].text.strip()
            # Strip code fences if present
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            parsed = json.loads(text)
            return {
                "ok": True,
                "tags": parsed.get("tags", []),
                "reasoning": parsed.get("reasoning", ""),
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
                "raw_text": text,
            }
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    return {"ok": False, "error": last_err, "tags": [], "reasoning": ""}


# ---------- Persist results ----------
def write_classification(client_id: str, evidence: dict, result: dict, slug_to_id: dict[str, str]):
    """Replace legacy_text/llm_auto rows for this client with the new LLM result."""
    sb = _sb()

    # Delete existing legacy_text + llm_auto rows (preserve manual)
    sb.table("client_categories").delete().eq("client_id", client_id).in_("source", ["legacy_text", "llm_auto"]).execute()

    rows_to_insert = []
    primary_seen = False
    for tag in result["tags"]:
        slug = tag.get("slug")
        cat_id = slug_to_id.get(slug)
        if not cat_id:
            continue
        is_primary = bool(tag.get("is_primary"))
        if is_primary and primary_seen:
            is_primary = False  # enforce one-primary rule
        if is_primary:
            primary_seen = True
        rows_to_insert.append({
            "client_id": client_id,
            "category_id": cat_id,
            "is_primary": is_primary,
            "source": "llm_auto",
            "confidence": float(tag.get("confidence", 0)),
            "reasoning": result["reasoning"][:500],
        })

    if rows_to_insert and not primary_seen:
        rows_to_insert[0]["is_primary"] = True

    if rows_to_insert:
        sb.table("client_categories").upsert(rows_to_insert, on_conflict="client_id,category_id").execute()

    # Audit log
    sb.table("classification_log").insert({
        "client_id": client_id,
        "evidence_bundle": evidence,
        "llm_response": {"tags": result["tags"], "reasoning": result["reasoning"]},
        "model": MODEL,
        "input_tokens": result.get("input_tokens", 0),
        "output_tokens": result.get("output_tokens", 0),
    }).execute()


# ---------- Pick clients to process ----------
def pick_targets(sb, reclassify: bool, limit: int | None) -> list[str]:
    """Pick real clients with at least one usable signal."""
    # Pull all real clients
    page = 0
    real = []
    while True:
        chunk = (sb.table("clients")
                 .select("id,status,is_mapping_stub,call_tracking_notes,category")
                 .eq("is_mapping_stub", False)
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        real.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1

    real_ids = [r["id"] for r in real]

    # Find clients with at least one ad
    ad_clients = set()
    page = 0
    while True:
        chunk = (sb.table("client_ads").select("client_id")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for r in chunk:
            ad_clients.add(r["client_id"])
        if len(chunk) < 1000:
            break
        page += 1

    # Skip already-classified (unless reclassify) and clients with manual tags
    skip_ids = set()
    page = 0
    while True:
        chunk = (sb.table("client_categories").select("client_id,source")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for r in chunk:
            if r["source"] == "manual":
                skip_ids.add(r["client_id"])
            elif r["source"] == "llm_auto" and not reclassify:
                skip_ids.add(r["client_id"])
        if len(chunk) < 1000:
            break
        page += 1

    targets = []
    for r in real:
        cid = r["id"]
        if cid in skip_ids:
            continue
        has_ad = cid in ad_clients
        has_ct = bool((r.get("call_tracking_notes") or "").strip())
        has_legacy = bool((r.get("category") or "").strip())
        # Skip prospects with NO signals (per plan)
        if r["status"] == "prospect" and not (has_ad or has_ct or has_legacy):
            continue
        targets.append(cid)

    if limit:
        targets = targets[:limit]
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Process 5 clients, print results, no writes")
    parser.add_argument("--limit", type=int, help="Cap number of clients to process")
    parser.add_argument("--reclassify", action="store_true", help="Re-run on clients already classified")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Build the system prompt with the canonical taxonomy
    print("Loading taxonomy...")
    taxonomy_text = build_taxonomy_text(sb)
    system_prompt = SYSTEM_TEMPLATE.format(TAXONOMY=taxonomy_text)
    slug_to_id = {r["slug"]: r["id"] for r in sb.table("categories").select("id,slug").execute().data}
    print(f"  {len(slug_to_id)} category slugs in tree")

    # Pick targets
    print("Picking targets...")
    limit = 5 if args.dry_run else args.limit
    targets = pick_targets(sb, reclassify=args.reclassify, limit=limit)
    print(f"  {len(targets)} clients to classify")

    if not targets:
        print("Nothing to do.")
        return

    # Fetch evidence in chunks
    print("Fetching evidence bundles...")
    BATCH = 200
    evidence_map: dict[str, dict] = {}
    for i in range(0, len(targets), BATCH):
        chunk_ids = targets[i:i + BATCH]
        evidence_map.update(fetch_evidence(sb, chunk_ids))
    print(f"  built {len(evidence_map)} evidence bundles")

    # Classify
    print(f"\nClassifying with {MODEL} ({WORKERS} workers)...")
    success = 0
    failed = 0
    total_in = 0
    total_out = 0
    start = time.time()

    def _process(cid: str):
        ev = evidence_map[cid]
        result = classify_client(ev, system_prompt)
        if not result["ok"]:
            return cid, ev, result, False
        if not args.dry_run:
            try:
                write_classification(cid, ev, result, slug_to_id)
            except Exception as e:
                result["ok"] = False
                result["error"] = f"persist failed: {e}"
                return cid, ev, result, False
        return cid, ev, result, True

    with open(JSONL_PATH, "a", encoding="utf-8") as jf:
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futures = {ex.submit(_process, cid): cid for cid in targets}
            for fut in as_completed(futures):
                cid, ev, result, ok = fut.result()
                if ok:
                    success += 1
                    total_in += result.get("input_tokens", 0)
                    total_out += result.get("output_tokens", 0)
                else:
                    failed += 1
                jf.write(json.dumps({
                    "client_id": cid,
                    "name": ev.get("name"),
                    "ok": ok,
                    "tags": result.get("tags"),
                    "reasoning": result.get("reasoning"),
                    "error": result.get("error"),
                }) + "\n")
                if (success + failed) % 50 == 0:
                    elapsed = time.time() - start
                    rate = (success + failed) / max(elapsed, 1)
                    eta = (len(targets) - success - failed) / max(rate, 0.1)
                    print(f"  {success + failed}/{len(targets)}  ok={success}  fail={failed}  rate={rate:.1f}/s  ETA={eta:.0f}s")

    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.0f}s. ok={success} fail={failed}")
    # Haiku 4.5 pricing: $1/MTok input, $5/MTok output (rough)
    cost = total_in * 1.0 / 1_000_000 + total_out * 5.0 / 1_000_000
    print(f"Tokens: {total_in:,} in / {total_out:,} out  ~${cost:.2f}")
    print(f"JSONL: {JSONL_PATH}")

    if args.dry_run:
        print("\n--- DRY-RUN sample ---")
        with open(JSONL_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[-5:]:
            row = json.loads(line)
            print(f"\n{row['name']}:")
            print(f"  tags: {row.get('tags')}")
            print(f"  why: {row.get('reasoning')}")


if __name__ == "__main__":
    main()
