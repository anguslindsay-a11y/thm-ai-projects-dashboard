"""
Parse clients.call_tracking_notes into the client_phone_numbers enrichment table.

This is ADDITIVE ONLY — it never touches clients.zone, client_zones, or
client_platform_ids. The output is a derived table joined when you want
phone-number / placement / business-line context.

Roles assigned per number:
  tracking    — the LHS of an "X > Y" forwarding line (CallRail tracking #)
  destination — the RHS of an "X > Y" forwarding line (real office #)
  in_ad       — published in the printed ad (no CT)
  unknown     — phone found in notes but couldn't classify

Placements detected:
  Bookmark, PopOut, OPP, IA (Inbox Advantage), In Book, Sweepstakes,
  Cross-Book, Double PopOut

Business lines detected from parenthetical / inline labels (Sales, Service,
Roofing, HVAC, IAQ, Window Depot, etc.)

Historical detection: lines containing 'canceled', 'cancelled', 'cxl',
'retired', 'no longer using', 'old:' or 'previous destination' get
is_historical=true.

Usage:
  python setup/parse_call_tracking_notes.py [--dry-run] [--reset]
"""

import os
import re
import sys
import argparse
from pathlib import Path
from collections import Counter

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# --- Zone label resolution ---
# Maps free-text zone labels in notes to a canonical zone abbreviation in DB.
# Multi-zone labels resolve to a list (we'll create one row per zone).
ZONE_LABEL_MAP = {
    # CO
    "north": ["ND"], "ndenver": ["ND"], "north denver": ["ND"], "n denver": ["ND"], "northdenver": ["ND"],
    "south": ["SD"], "sdenver": ["SD"], "south denver": ["SD"], "s denver": ["SD"], "southdenver": ["SD"],
    "metro": ["ND", "SD"], "met": ["ND", "SD"], "denver": ["ND", "SD"],
    "north/south": ["ND", "SD"], "n/s": ["ND", "SD"], "south/north": ["ND", "SD"],
    "noco": ["NOCO"], "nco": ["NOCO"], "northern co": ["NOCO"], "northern colorado": ["NOCO"],
    "epc": ["EPC"], "co springs": ["EPC"], "colo springs": ["EPC"], "colorado springs": ["EPC"],
    # UT
    "nw": ["NW"], "north wasatch": ["NW"], "northwasatch": ["NW"],
    "cw": ["CW"], "central": ["CW"], "central wasatch": ["CW"], "centralwasatch": ["CW"], "slc": ["CW"],
    "sw": ["SW"], "south wasatch": ["SW"], "southwasatch": ["SW"],
    # TX (rare in notes — they don't break out per zone often)
    "an": ["AN"], "austin north": ["AN"], "au north": ["AN"],
    "as": ["AS"], "austin south": ["AS"], "au south": ["AS"],
    "sae": ["SAE"], "san antonio east": ["SAE"], "sa east": ["SAE"],
    "saw": ["SAW"], "san antonio west": ["SAW"], "sa west": ["SAW"],
}

PLACEMENT_PATTERNS = [
    (r"\b(?:dbl|double)\s*pop\s*out\b|\bdbl\s*po\b", "Double PopOut"),
    (r"\bpop\s*out\b|\bpo\b(?!\w)", "PopOut"),
    (r"\bbook\s*mark\b|\bbmark\b|\bbm\b(?!\w)", "Bookmark"),
    (r"\bopp\b", "OPP"),
    (r"\bia\b", "IA"),
    (r"\bin\s*book\b|\binbook\b", "In Book"),
    (r"\bsweep(?:stakes)?\b", "Sweepstakes"),
    (r"\bxbook\b|\bx\s*book\b|\bcross[\s-]?book\b|\bxbo\b", "Cross-Book"),
    (r"\bxmkt\b|\bx\s*market\b|\bcross[\s-]?market\b|\bxmo\b", "Cross-Market"),
]

BUSINESS_LINE_PATTERNS = [
    (r"\bsales\b", "Sales"),
    (r"\bservice\b", "Service"),
    (r"\broof(?:ing)?\b", "Roofing"),
    (r"\bwindow(?:s)?\b(?!\s*(?:depot|expo|expr|expressions))", None),  # don't grab generic windows
    (r"\bwindow\s*depot\b", "Window Depot"),
    (r"\bhvac\b", "HVAC"),
    (r"\biaq\b", "IAQ"),
    (r"\belectric\b", "Electric"),
    (r"\bplumbing\b", "Plumbing"),
    (r"\bcurbing\b", "Curbing"),
    (r"\bdrgrout\b|\bgrout\b", "Grout"),
]

HISTORICAL_KEYWORDS = [
    "canceled", "cancelled", "cxl", "(retired)", " retired", "retired)",
    "no longer using", "no longer", "previous destination", "old:", "as of",
]

# Phone regex: matches (XXX) XXX-XXXX, XXX-XXX-XXXX, XXX.XXX.XXXX, XXXXXXXXXX
PHONE_RE = re.compile(r"\(?(\d{3})\)?[\s\-.]*(\d{3})[\s\-.]*(\d{4})")
# Forwarding pattern: phone > phone (with arbitrary whitespace/tabs)
ARROW_RE = re.compile(
    r"\(?(\d{3})\)?[\s\-.]*(\d{3})[\s\-.]*(\d{4})\s*>\s*\(?(\d{3})\)?[\s\-.]*(\d{3})[\s\-.]*(\d{4})"
)
# In-ad indicator
IN_AD_RE = re.compile(r"\bin\s*ad\b", re.IGNORECASE)


def normalize_phone(a: str, b: str = "", c: str = "") -> str:
    """Return digits-only 10-digit phone."""
    digits = re.sub(r"\D", "", f"{a}{b}{c}")
    return digits[-10:] if len(digits) >= 10 else digits


def detect_placement(text: str) -> str | None:
    t = text.lower()
    for pat, name in PLACEMENT_PATTERNS:
        if re.search(pat, t):
            return name
    return None


_BIZ_BLOCKLIST = {
    # Zone/placement words masquerading as business lines
    "metro", "north", "south", "central", "east", "west", "noco", "epc",
    "n/s", "north/south", "south/north", "ndenver", "sdenver",
    "popout", "pop out", "bookmark", "bmark", "opp", "ia", "in book",
    "in ad", "inbook", "inad", "sweepstakes", "xbook", "xbo", "xmkt",
    "retired", "cancelled", "canceled", "old", "previous",
    "n/s popout", "noco - popout", "metro - versacourts",
}

def detect_business_line(text: str, client_name: str = "") -> str | None:
    t = text.lower()
    cname = (client_name or "").lower()
    for pat, name in BUSINESS_LINE_PATTERNS:
        if name is None:
            continue
        if re.search(pat, t):
            # Don't echo back the client name's own category
            if name.lower() in cname:
                continue
            return name
    # Parenthetical fallback: "(Window Depot)" -> "Window Depot"
    paren = re.findall(r"\(([^)0-9]{3,30})\)", text)
    for p in paren:
        ps = p.strip()
        if not ps or ps.lower() in cname or ps.lower() in _BIZ_BLOCKLIST:
            continue
        # Must look like a label (Title Case, mostly letters)
        if re.match(r"^[A-Za-z][A-Za-z0-9 &/+\-]+$", ps) and len(ps.split()) <= 3:
            return ps.title()
    return None


def detect_zones(text: str) -> tuple[list[str], str | None]:
    """Return (list of zone abbrs, raw label that matched)."""
    t = text.lower()
    # Try multi-word labels first to avoid false positives ("south denver" before "south")
    sorted_labels = sorted(ZONE_LABEL_MAP.keys(), key=lambda x: -len(x))
    for label in sorted_labels:
        # Use word boundaries; allow / between tokens (n/s)
        pattern = r"(?<![a-z])" + re.escape(label) + r"(?![a-z])"
        if re.search(pattern, t):
            return ZONE_LABEL_MAP[label], label
    return [], None


def is_historical_line(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in HISTORICAL_KEYWORDS)


def parse_notes(notes: str, client_name: str = "") -> list[dict]:
    """Return a list of phone-number records extracted from notes."""
    if not notes:
        return []
    rows = []
    # Split into logical lines — handle both \n and ; separators
    raw_lines = re.split(r"[\n;]+", notes)
    for raw in raw_lines:
        line = raw.strip()
        if not line:
            continue
        line_lower = line.lower()
        historical = is_historical_line(line)
        placement = detect_placement(line)
        business = detect_business_line(line, client_name)
        zones, zone_raw = detect_zones(line)
        zone_list = zones if zones else [None]

        # 1) Arrow forwarding pattern (CT -> destination)
        for m in ARROW_RE.finditer(line):
            tracking = normalize_phone(m.group(1), m.group(2), m.group(3))
            destination = normalize_phone(m.group(4), m.group(5), m.group(6))
            for z in zone_list:
                rows.append({
                    "phone_number": tracking,
                    "phone_display": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                    "role": "tracking",
                    "zone_abbr": z,
                    "zone_label_raw": zone_raw,
                    "placement": placement,
                    "business_line": business,
                    "is_historical": historical,
                    "notes_excerpt": line[:500],
                })
                rows.append({
                    "phone_number": destination,
                    "phone_display": f"{m.group(4)}-{m.group(5)}-{m.group(6)}",
                    "role": "destination",
                    "zone_abbr": z,
                    "zone_label_raw": zone_raw,
                    "placement": placement,
                    "business_line": business,
                    "is_historical": historical,
                    "notes_excerpt": line[:500],
                })
            continue

        # 2) "In Ad" pattern — line lists a published number, no CT
        if IN_AD_RE.search(line):
            for m in PHONE_RE.finditer(line):
                phone = normalize_phone(m.group(1), m.group(2), m.group(3))
                for z in zone_list:
                    rows.append({
                        "phone_number": phone,
                        "phone_display": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                        "role": "in_ad",
                        "zone_abbr": z,
                        "zone_label_raw": zone_raw,
                        "placement": placement,
                        "business_line": business,
                        "is_historical": historical,
                        "notes_excerpt": line[:500],
                    })
            continue

        # 3) Bare phone(s) — TX often just lists numbers; classify by NCT marker
        if "nct" in line_lower:
            role = "in_ad"  # NCT = no CT, so the listed # is the in-ad number
        else:
            role = "unknown"
        for m in PHONE_RE.finditer(line):
            phone = normalize_phone(m.group(1), m.group(2), m.group(3))
            for z in zone_list:
                rows.append({
                    "phone_number": phone,
                    "phone_display": f"{m.group(1)}-{m.group(2)}-{m.group(3)}",
                    "role": role,
                    "zone_abbr": z,
                    "zone_label_raw": zone_raw,
                    "placement": placement,
                    "business_line": business,
                    "is_historical": historical,
                    "notes_excerpt": line[:500],
                })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset", action="store_true",
                        help="Clear existing ct_notes rows before re-parsing")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Load zones for FK resolution
    zones = sb.table("zones").select("id,abbreviation").execute().data
    zone_abbr_to_id = {z["abbreviation"]: z["id"] for z in zones}

    # Load clients with notes
    print("Loading clients with call_tracking_notes...")
    clients = []
    page = 0
    while True:
        chunk = (sb.table("clients")
                 .select("id,name,call_tracking_notes")
                 .not_.is_("call_tracking_notes", "null")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        clients.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
    print(f"  {len(clients)} clients have notes")

    # Parse
    all_records = []
    parsed_clients = 0
    role_counter = Counter()
    placement_counter = Counter()
    business_counter = Counter()
    for c in clients:
        records = parse_notes(c["call_tracking_notes"], c["name"])
        if not records:
            continue
        parsed_clients += 1
        for r in records:
            r["client_id"] = c["id"]
            r["zone_id"] = zone_abbr_to_id.get(r["zone_abbr"]) if r.get("zone_abbr") else None
            r.pop("zone_abbr", None)
            role_counter[r["role"]] += 1
            if r["placement"]:
                placement_counter[r["placement"]] += 1
            if r["business_line"]:
                business_counter[r["business_line"]] += 1
            all_records.append(r)

    # Dedupe: same client+phone+role+placement+business+zone+historical -> keep first
    seen = set()
    deduped = []
    for r in all_records:
        key = (r["client_id"], r["phone_number"], r["role"], r.get("placement"),
               r.get("business_line"), r.get("zone_id"), r["is_historical"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    dropped = len(all_records) - len(deduped)
    all_records = deduped

    # Drop "unknown" rows when an arrow-derived (tracking/destination) row already
    # exists for the same client+phone — the arrow row is more informative.
    arrow_phones = {(r["client_id"], r["phone_number"]) for r in all_records
                    if r["role"] in ("tracking", "destination")}
    before = len(all_records)
    all_records = [r for r in all_records
                   if not (r["role"] == "unknown"
                           and (r["client_id"], r["phone_number"]) in arrow_phones)]
    dropped_unknown = before - len(all_records)

    print(f"\nParsed records: {len(all_records)} from {parsed_clients} clients "
          f"(deduped {dropped}, dropped {dropped_unknown} redundant unknown)")
    print(f"  By role: {dict(Counter(r['role'] for r in all_records))}")
    print(f"  By placement (top 10): {dict(Counter(r['placement'] for r in all_records if r['placement']).most_common(10))}")
    print(f"  By business line (top 10): {dict(Counter(r['business_line'] for r in all_records if r['business_line']).most_common(10))}")

    if args.dry_run:
        print("\n--- DRY RUN: no writes ---")
        print("\nSample records:")
        for r in all_records[:10]:
            print(f"  {r['phone_display']} role={r['role']} placement={r['placement']} biz={r['business_line']} hist={r['is_historical']}")
        return

    if args.reset:
        print("\nResetting existing ct_notes rows...")
        sb.table("client_phone_numbers").delete().eq("source", "ct_notes").execute()

    # Insert in batches
    print("\nWriting client_phone_numbers...")
    batch_size = 500
    written = 0
    for i in range(0, len(all_records), batch_size):
        batch = all_records[i:i + batch_size]
        sb.table("client_phone_numbers").insert(batch).execute()
        written += len(batch)
        print(f"  {written}/{len(all_records)}...")
    print(f"  Inserted {written} rows")

    print("\nDone.")


if __name__ == "__main__":
    main()
