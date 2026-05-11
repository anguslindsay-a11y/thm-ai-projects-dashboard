"""
Load ad_extractions.jsonl into the client_ads Supabase table.

Joins extraction records with their Supabase Storage path, matches client names
to clients table, resolves zones, normalizes ad size vocabulary, and upserts
rows on storage_path conflict.

Safe to run multiple times — it upserts.

Client matching safety rules (added 2026-05-06 after a fuzzy-match audit caught
~120 ads silently mis-attributed to catch-all clients like "X-Siding" and
"Bell Plumbing"):

  1. Market scoping. The ad's market is derived from its zone (or folder hint);
     candidate clients must share that market or be cross-market (NULL primary).
  2. Confidence threshold. Token-overlap ≥2, OR substring match where one side
     has only 1 token. The old "first-word match" fallback is gone — it caused
     "Precision Closets ..." to land on "Precision Overhead Door of SA".
  3. Non-destructive normalization. Product-suffix stripping ("PLUMBING",
     "SIDING", etc.) is suppressed when it would reduce a client name below
     5 chars / 2 tokens. Without this guard, "Bell Plumbing" → "Bell" and
     "X-Siding" → "X" became substring-matchable inside many unrelated names.
  4. Existing client_id is preserved on re-runs when the new match is None,
     so manual mappings made directly in the DB survive future imports.
"""

import os
import re
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv(override=True)

from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BUCKET = "client_ads"
JSONL_PATH = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest\Supabase Data Hub\output\ad_extractions.jsonl")

ZONE_CODE_MAP = {
    # Colorado
    "NCO": "NOCO", "NOCO": "NOCO",
    "NDN": "ND",   "ND": "ND",
    "SDN": "SD",   "SD": "SD",
    "EPC": "EPC",
    # Utah
    "NW": "NW", "CW": "CW", "SW": "SW",
    # Texas
    "AUN": "AN",   # Austin North
    "AUS": "AS",   # Austin South
    "SAE": "SAE",  # SA East
    "SAW": "SAW",  # SA West
    "E": "SAE",    # short form for SA East (when prefix is THMSA)
    "W": "SAW",    # short form for SA West (when prefix is THMSA)
    # Combined / cross-zone — single zone_id can't represent these
    "AUN&S": None, "AUS&N": None, "SAE&W": None, "SE&W": None, "AUS&AUN": None,
    # Cross-book placeholder
    "XBO": None,
    "ALL": None,
}

SIZE_CODE_MAP = {
    "F": "Full Page",
    "Fb": "Full Page",       # Full bleed variant
    "FC": "Front Cover",
    "H": "1/2 Page",
    "Hb": "1/2 Page",        # Half bleed variant
    "Q": "1/4 Page",
    "Qb": "1/4 Page",
    "D": "Double Page",
    "Db": "Double Page",
    "BC": "Back Cover 2/3 Page",
    "BCB": "Back Cover Banner",
    "BB": "Back Cover Banner",
    "Bb": "Back Cover Banner",
    "PO": "OPP PopOut",
    "BM": "OPP Bookmark",
    "HV": "1/2 Page Vertical",
}


_PRODUCT_SUFFIXES = [
    "WINDOWS", "ROOFGUTTERSIDING", "ROOF", "GUTTERS", "SIDING", "LIGHTING",
    "KITCHBATH", "KITCHEN", "BATH", "PLUMBING", "HVAC", "PO", "Curbing",
    "DUCT", "Lighting", "Solar", "Sunesta", "Patio Covers", "WDKB",
    "PopOut", "Eclipse Awnings", "ElectricHVAC", "Holiday Light Co",
    "W Indow Cleaning", "Landscape",
]

def normalize_client_name(name: str) -> str:
    n = name.strip()
    # Strip numeric PopOut suffixes like "-01", "-02" at end
    n = re.sub(r"[-_\s]+\d{1,2}$", "", n)
    # Strip THMCO-SIZE-ZONE-ISSUE junk if leftover from a bad parse
    n = re.sub(r"-THM[A-Z]{2}-.+$", "", n)
    # Strip product-line suffixes after a hyphen, but only if the result still has
    # ≥5 chars and ≥2 tokens. Without this guard, "Bell Plumbing" → "Bell" and
    # "X-Siding" → "X", which then fuzzy-match many unrelated source names.
    for suf in sorted(_PRODUCT_SUFFIXES, key=len, reverse=True):
        candidate = re.sub(rf"[-\s]+{re.escape(suf)}$", "", n, flags=re.IGNORECASE)
        if candidate != n and len(candidate) >= 5 and len(candidate.split()) >= 2:
            n = candidate
            break
    # Insert spaces at CamelCase boundaries: "A2ZBuilders" -> "A2Z Builders"
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    n = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", n)
    n = re.sub(r"(?<=[a-zA-Z])(?=[0-9])", " ", n)
    n = re.sub(r"(?<=[0-9])(?=[A-Z])", " ", n)
    n = n.lower()
    n = re.sub(r"[,.\-/]+", " ", n)
    n = re.sub(r"\s+", " ", n)
    return n.strip()


def build_client_index(sb):
    print("Loading clients...")
    rows, off = [], 0
    while True:
        batch = sb.table("clients").select("id,name,status,primary_market_id").range(off, off + 999).execute().data
        rows.extend(batch)
        if len(batch) < 1000:
            break
        off += 1000
    idx_norm = {normalize_client_name(r["name"]): r for r in rows}
    idx_lc = {r["name"].lower(): r for r in rows}
    print(f"  {len(rows)} clients indexed")
    return rows, idx_norm, idx_lc


def _market_ok(client: dict, ad_market_id: str | None) -> bool:
    """Reject candidate when client's market clearly differs from the ad's market.
    Cross-market clients (primary_market_id IS NULL) are always allowed."""
    if ad_market_id is None:
        return True
    cm = client.get("primary_market_id")
    if cm is None:
        return True
    return cm == ad_market_id


_STOPWORDS = frozenset({
    "the", "and", "of", "for", "to", "at", "by", "co", "company", "llc", "inc",
    "home", "homes", "service", "services", "solutions", "group", "team", "works",
})

# Manual filename-to-client-name aliases discovered during cleanup passes.
# Keys are EXACT source_client_name strings as parsed from filenames; values are
# the canonical DB client name. Checked first in match_client so the matcher
# doesn't have to "guess" these via fuzzy logic on every run.
#
# Only add entries here when the source name is unambiguous (one DB target) —
# multi-target cases (e.g. "Rebath" splitting to Austin vs San Antonio variants)
# need zone-aware logic and are still handled by periodic post-import SQL fixes.
CLIENT_ALIASES = {
    # CO
    "J+KRoofing":                  "J & K Roofing",
    "J+KRoofing-Windows":          "J & K Roofing",   # windows division, same parent
    "DutchsHomeImprovement":       "Dutch's Home Improvement",
    "OkeefeBuilt":                 "O'Keefe Built",
    "ABD":                         "ABD (Associates in Building + Design, Ltd.)",
    "ABD Associates in Building":  "ABD (Associates in Building + Design, Ltd.)",
    # UT
    "S_SRoofing":                  "S&S Roofing",
    "S & S Roofing":               "S&S Roofing",
    # TX
    "Total Concrete":              "Total Concrete Solutions",
    "Rudys":                       "Rudy's Flooring & Remodeling",
    "Carlsons":                    "Carlson's Flooring",
    "Garcia Doors":                "Garcia Doors - Austin & SA",
    "Teagues":                     "Teague's Tree",
}


def match_client(raw_name: str, clients_list, idx_norm, idx_lc, ad_market_id: str | None = None) -> str | None:
    """Return client_id or None.
    Rejects matches that cross markets when ad_market_id is known (clients with NULL
    primary_market_id always allowed). Rejects unsafe substring/prefix matches that
    historically caused catch-all clients (X-Siding, Bell Plumbing) to absorb
    unrelated ads — see header comment."""
    if not raw_name:
        return None

    # Manual alias check — short-circuits the fuzzy logic for names that have
    # been validated to point at a specific DB client. Market scoping still
    # applies (an alias target won't be used for an ad in the wrong market).
    alias_target = CLIENT_ALIASES.get(raw_name)
    if alias_target:
        alias_hit = idx_lc.get(alias_target.lower())
        if alias_hit and _market_ok(alias_hit, ad_market_id):
            return alias_hit["id"]

    hit = idx_lc.get(raw_name.lower())
    if hit and _market_ok(hit, ad_market_id):
        return hit["id"]
    norm = normalize_client_name(raw_name)
    if len(norm) < 4:
        return None
    hit = idx_norm.get(norm)
    if hit and _market_ok(hit, ad_market_id):
        return hit["id"]

    raw_tokens = [t for t in norm.split() if len(t) > 1]
    if not raw_tokens:
        return None
    # Strip stopwords for overlap scoring so generic words like "home", "solutions"
    # don't outweigh a distinctive token like "bellwether".
    norm_tokens = [t for t in raw_tokens if t not in _STOPWORDS] or raw_tokens
    norm_token_set = set(norm_tokens)

    candidates = []
    for cnorm, c in idx_norm.items():
        if not cnorm or not _market_ok(c, ad_market_id):
            continue
        c_raw_tokens = [t for t in cnorm.split() if len(t) > 1]
        if not c_raw_tokens:
            continue
        c_tokens = [t for t in c_raw_tokens if t not in _STOPWORDS] or c_raw_tokens
        c_token_set = set(c_tokens)
        overlap = norm_token_set & c_token_set
        substring = norm in cnorm or cnorm in norm
        # Confident match: ≥2 token overlap, OR substring match where one side has only 1 token.
        if len(overlap) >= 2 or (substring and (len(c_tokens) == 1 or len(norm_tokens) == 1)):
            candidates.append((c, cnorm, len(overlap), substring))

    if candidates:
        first_word = norm_tokens[0]
        candidates.sort(key=lambda x: (
            -x[2],
            0 if x[3] else 1,
            0 if x[1].startswith(first_word) else 1,
            abs(len(x[1]) - len(norm)),
        ))
        return candidates[0][0]["id"]

    # Fallback A: no-space substring (handles "Timberworx" → "TimberWorx Tree & Landscaping")
    src_ns = norm.replace(" ", "")
    if len(src_ns) >= 6:
        ns_hits = []
        for cnorm, c in idx_norm.items():
            if not cnorm or not _market_ok(c, ad_market_id):
                continue
            ns = cnorm.replace(" ", "")
            if not ns:
                continue
            if (src_ns in ns or ns in src_ns) and min(len(src_ns), len(ns)) >= 6:
                ns_hits.append(c)
        if len(ns_hits) == 1:
            return ns_hits[0]["id"]

    # Fallback B: unique 8-char nospace prefix in same market (handles "BellwetherHomeSolutions"
    # → "Bellwether Windows, Siding & Doors" without re-introducing the unsafe first-word match).
    if len(src_ns) >= 8:
        prefix = src_ns[:8]
        prefix_hits = []
        for cnorm, c in idx_norm.items():
            if not cnorm or not _market_ok(c, ad_market_id):
                continue
            ns = cnorm.replace(" ", "")
            if ns.startswith(prefix):
                prefix_hits.append(c)
        if len(prefix_hits) == 1:
            return prefix_hits[0]["id"]

    return None


def build_zone_index(sb):
    rows = sb.table("zones").select("id,abbreviation,market_id").execute().data
    abbr_to_id = {r["abbreviation"]: r["id"] for r in rows}
    id_to_market = {r["id"]: r["market_id"] for r in rows}
    return abbr_to_id, id_to_market


def build_market_index(sb):
    rows = sb.table("markets").select("id,code").execute().data
    return {r["code"]: r["id"] for r in rows}


_FOLDER_MARKET_HINTS = [
    ("utah", "UT"), ("thmut", "UT"),
    ("colorado", "CO"), ("thmco", "CO"),
    ("san antonio", "SA"), ("thmsa", "SA"),
    ("austin", "AU"), ("thmau", "AU"),
]

# Filename patterns ordered most-specific → least-specific. First match wins.
# Filename example: "Texas Rolling Shutters-THMTX-Fb-SAE&W-2605.jpg"
_FILENAME_MARKET_PATTERNS = [
    (re.compile(r"[_=. -]THM[ ]?CO[ _=.-]", re.IGNORECASE), "CO"),
    (re.compile(r"[_=. -]THM[ ]?UT[ _=.-]", re.IGNORECASE), "UT"),
    (re.compile(r"[_=. -]THM[ ]?SA[ _=.-]", re.IGNORECASE), "SA"),
    (re.compile(r"[_=. -]THM[ ]?AU[ _=.-]", re.IGNORECASE), "AU"),
    # THMTX must look at zone tail to disambiguate AU vs SA
    (re.compile(r"[_=. -]THM[ ]?TX[-_=. ].*(?:AUN&S|AUS&N|AUN|AUS|AU)(?:[-_=. ]|$)", re.IGNORECASE), "AU"),
    (re.compile(r"[_=. -]THM[ ]?TX[-_=. ].*(?:SAE&W|SAW&E|SE&W|SAE|SAW|SA)(?:[-_=. ]|$)", re.IGNORECASE), "SA"),
]


def market_id_from_filename_hints(filename: str, folder: str, market_idx: dict) -> str | None:
    """Derive market_id from filename patterns first, then folder fallback.
    Returns None for ambiguous THM Texas folders (TX maps to AU OR SA — needs zone hint)."""
    if filename:
        for pat, code in _FILENAME_MARKET_PATTERNS:
            if pat.search(filename):
                return market_idx.get(code)
    if folder:
        f = folder.lower()
        # Only return non-ambiguous folder hints. "thm texas" alone doesn't pick AU vs SA.
        for hint, code in (("utah", "UT"), ("thmut", "UT"), ("colorado", "CO"), ("thmco", "CO"),
                           ("san antonio", "SA"), ("thmsa", "SA"),
                           ("austin", "AU"), ("thmau", "AU")):
            if hint in f:
                return market_idx.get(code)
    return None


# Backwards-compatible alias used by ad_register_metadata_only.py
def market_id_from_folder(folder: str, market_idx: dict) -> str | None:
    return market_id_from_filename_hints("", folder, market_idx)


def flatten_parsed(parsed: dict) -> dict:
    """Pull out the key flat fields from the Haiku JSON output."""
    if not isinstance(parsed, dict):
        return {}
    return {
        "headline": parsed.get("headline"),
        "company_name_shown": parsed.get("company_name_shown"),
        "primary_offer": parsed.get("primary_offer"),
        "financing_offer": parsed.get("financing_offer"),
        "cta": parsed.get("cta"),
        "website": parsed.get("website"),
        "years_in_business": parsed.get("years_in_business"),
    }


def fetch_existing_client_ids(sb, storage_paths: list[str]) -> dict[str, str]:
    """Map storage_path → existing client_id so we can preserve manual mappings
    when the matcher returns None on a re-run."""
    out: dict[str, str] = {}
    BATCH = 200
    for i in range(0, len(storage_paths), BATCH):
        chunk = storage_paths[i : i + BATCH]
        result = sb.table("client_ads").select("storage_path,client_id").in_("storage_path", chunk).execute()
        for r in result.data:
            if r.get("client_id"):
                out[r["storage_path"]] = r["client_id"]
    return out


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    zone_idx, zone_to_market = build_zone_index(sb)
    market_idx = build_market_index(sb)
    clients, idx_norm, idx_lc = build_client_index(sb)

    if not JSONL_PATH.exists():
        print(f"ERROR: {JSONL_PATH} not found.")
        sys.exit(1)

    rows = []
    skipped = 0
    unmatched = []
    cross_market_blocked = 0
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if rec.get("error"):
                skipped += 1
                continue
            meta = rec.get("meta", {})
            parsed = rec.get("parsed", {}) or {}

            raw_name = meta.get("client_raw", "")
            size_code = meta.get("size_code")
            zone_code_raw = meta.get("zone_code")
            issue_code = meta.get("issue_code") or ""
            relpath = rec.get("relpath") or meta.get("relpath") or ""
            folder = meta.get("folder") or ""

            is_cross_book = zone_code_raw == "XBO" or "XBO" in relpath
            is_supplement = issue_code.endswith("s")

            zone_abbr = ZONE_CODE_MAP.get(zone_code_raw) if zone_code_raw else None
            zone_id = zone_idx.get(zone_abbr) if zone_abbr else None

            ad_market_id = zone_to_market.get(zone_id) if zone_id else None
            if ad_market_id is None:
                ad_market_id = market_id_from_filename_hints(rec.get("filename") or "", folder, market_idx)

            client_id = match_client(raw_name, clients, idx_norm, idx_lc, ad_market_id)
            if not client_id:
                unmatched.append(raw_name)
                # Note: market filtering may also block matches; we lump those into
                # "unmatched" — the resync path will leave them NULL and they'll
                # surface in the manual-review queue.

            ad_size = SIZE_CODE_MAP.get(size_code) if size_code else None

            flat = flatten_parsed(parsed)
            rows.append({
                "client_id": client_id,
                "zone_id": zone_id,
                "market_id": ad_market_id,
                "issue_code": issue_code.rstrip("s") if is_supplement else issue_code,
                "ad_size": ad_size,
                "ad_size_code_raw": size_code,
                "is_cross_book": is_cross_book,
                "is_supplement": is_supplement,
                "storage_path": relpath,
                "filename_original": rec.get("filename"),
                "source_client_name": raw_name,
                "source_folder": folder,
                "headline": flat["headline"],
                "company_name_shown": flat["company_name_shown"],
                "primary_offer": flat["primary_offer"],
                "financing_offer": flat["financing_offer"],
                "cta": flat["cta"],
                "website": flat["website"],
                "years_in_business": flat["years_in_business"],
                "extraction": parsed,
                "extraction_model": rec.get("model"),
                "extraction_input_tokens": rec.get("input_tokens"),
                "extraction_output_tokens": rec.get("output_tokens"),
                "extracted_at": datetime.now(timezone.utc).isoformat(),
            })

    print(f"Parsed {len(rows)} rows. Skipped {skipped} (error/empty).")
    matched = sum(1 for r in rows if r["client_id"])
    print(f"Clients matched: {matched} / {len(rows)} ({100*matched/max(1,len(rows)):.1f}%)")
    print(f"Unmatched example names: {sorted(set(unmatched))[:15]}")

    # Preserve manual mappings: if a row's storage_path already exists with a
    # client_id and our new match is None, keep the existing mapping rather than
    # clobbering it. This protects fixes applied directly in the DB.
    storage_paths = [r["storage_path"] for r in rows if r.get("storage_path")]
    existing = fetch_existing_client_ids(sb, storage_paths) if storage_paths else {}
    preserved = 0
    for r in rows:
        if not r["client_id"] and r["storage_path"] in existing:
            r["client_id"] = existing[r["storage_path"]]
            preserved += 1
    if preserved:
        print(f"Preserved {preserved} existing client_id values where new match was None.")

    print("Upserting into client_ads...")
    total = 0
    for i in range(0, len(rows), 100):
        batch = rows[i:i + 100]
        sb.table("client_ads").upsert(batch, on_conflict="storage_path").execute()
        total += len(batch)
        print(f"  {total}/{len(rows)}")

    print(f"\nDone. Inserted/updated {total} rows.")


if __name__ == "__main__":
    main()
