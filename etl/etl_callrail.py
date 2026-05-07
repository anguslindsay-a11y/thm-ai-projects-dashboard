"""
CallRail ETL — Pull call data from CallRail API into Supabase.

Fetches calls for all companies in the account, matches them to clients
via client_platform_ids, and upserts into the calls table.

Usage:
  python etl/etl_callrail.py                     # Last 30 days (default)
  python etl/etl_callrail.py --days 7             # Last 7 days
  python etl/etl_callrail.py --start 2026-01-01 --end 2026-01-31  # Date range
  python etl/etl_callrail.py --dry-run            # Preview only
"""

import sys
import os
import time
import argparse
import logging
from pathlib import Path
from datetime import datetime, timedelta, timezone

import requests

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv()

from supabase import create_client

# --- Configuration ---

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
CALLRAIL_API_KEY = os.getenv("CALLRAIL_API_KEY")
CALLRAIL_ACCOUNT_ID = os.getenv("CALLRAIL_ACCOUNT_ID")  # Legacy — kept for backwards compat

CALLRAIL_BASE_URL = "https://api.callrail.com/v3"

# All CallRail accounts to pull from
CALLRAIL_ACCOUNTS = [
    ("ACCe42c98d3446c4dc898467150060f870c", "Colorado"),
    ("ACCb1f04de7a28941f4827eb25f18d5e810", "Utah"),
    ("ACC60a4cf8cf0514a45acfde9c07fa1275b", "Austin & San Antonio"),
]

# Test lines — ingested as normal calls, then flagged via calls_enriched.is_test_call
# (which checks both caller_number and tag-based test markers). Filter at query time
# with `WHERE NOT is_test_call`. Hard-skipping at ingest loses data we may want later.
KNOWN_TEST_NUMBERS = {"3032204242"}  # Anstel verification line — kept here for reference

# Qualified call threshold (seconds)
QUALIFIED_THRESHOLD = 60

# Extra fields to request from CallRail API
# Note: CallRail renamed tracker_name -> source_name and call_summary -> lead_explanation (circa early 2026)
EXTRA_FIELDS = "company_id,company_name,campaign,lead_explanation,recording,first_call,tags,source_name"

# Max calls per API page
PER_PAGE = 250

# --- Logging ---

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "etl_callrail.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def callrail_headers():
    return {"Authorization": f"Token token=\"{CALLRAIL_API_KEY}\""}


def request_with_retry(url, *, headers=None, params=None, max_attempts=4, timeout=30):
    """GET with exponential backoff for transient connection errors. CallRail SSL
    occasionally drops mid-pagination; without retries, a single blip kills the ETL."""
    last_err = None
    for attempt in range(max_attempts):
        try:
            return requests.get(url, headers=headers, params=params, timeout=timeout)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_err = e
            if attempt == max_attempts - 1:
                break
            wait = 2 ** attempt  # 1s, 2s, 4s
            log.warning(f"  HTTP error (attempt {attempt + 1}/{max_attempts}): {str(e)[:80]} — retrying in {wait}s")
            time.sleep(wait)
    raise last_err


def strip_phone(number: str) -> str:
    """Strip a phone number to digits only."""
    if not number:
        return ""
    return "".join(c for c in number if c.isdigit())


# Tracker name patterns -> zone abbreviation
# e.g., "TheHomeMag - NoCo" -> NOCO, "TheHomeMag - EPC" -> EPC
TRACKER_ZONE_MAP = {
    "noco": "NOCO",
    "northern co": "NOCO",
    "north denver": "ND",
    "ndn": "ND",
    "south denver": "SD",
    "sdn": "SD",
    "epc": "EPC",
    "co springs": "EPC",
    "colorado springs": "EPC",
    "nw": "NW",
    "north wasatch": "NW",
    "cw": "CW",
    "central wasatch": "CW",
    "sw": "SW",
    "south wasatch": "SW",
    "slc": "CW",
    "au north": "AN",
    "austin north": "AN",
    "austin n": "AN",
    "au south": "AS",
    "austin south": "AS",
    "austin s": "AS",
    "sa east": "SAE",
    "san antonio east": "SAE",
    "san antonio e": "SAE",
    "sa west": "SAW",
    "san antonio west": "SAW",
    "san antonio w": "SAW",
    # Market-level fallbacks — used when a TX client shares one CallRail across both markets
    # without per-zone breakdown. Routing keys reuse the market code.
    "austin": "AU",
    "san antonio": "SA",
}


def parse_zone_from_tracker_name(tracker_name: str) -> str | None:
    """Parse zone abbreviation from a tracker name like 'TheHomeMag - NoCo'."""
    if not tracker_name:
        return None
    name_lower = tracker_name.lower().strip()
    # Check each pattern, longest match first to avoid false positives
    for pattern, zone in sorted(TRACKER_ZONE_MAP.items(), key=lambda x: -len(x[0])):
        if pattern in name_lower:
            return zone
    return None


def fetch_calls(start_date: str, end_date: str, account_id: str = None):
    """
    Fetch all calls from CallRail between start_date and end_date.
    Uses offset-based pagination. Yields call dicts.
    """
    acct = account_id or CALLRAIL_ACCOUNT_ID
    next_url = f"{CALLRAIL_BASE_URL}/a/{acct}/calls.json"
    params = {
        "start_date": start_date,
        "end_date": end_date,
        "per_page": PER_PAGE,
        "fields": EXTRA_FIELDS,
        "relative_pagination": "true",
    }

    while next_url:
        resp = request_with_retry(next_url, headers=callrail_headers(), params=params)

        if resp.status_code == 429:
            log.warning("Rate limited by CallRail. Stopping pagination.")
            break

        resp.raise_for_status()
        data = resp.json()

        calls = data.get("calls", [])
        if not calls:
            break

        yield from calls

        if not data.get("has_next_page", False):
            break

        # Follow the next_page URL directly (it includes all params)
        next_url = data.get("next_page")
        params = None  # next_page URL already has params baked in


def build_company_to_client_map(sb):
    """
    Build a mapping of CallRail company_id -> Supabase client_id
    using the client_platform_ids table.

    CallRail external_ids are stored as COM{company_guid}.

    NOTE: Supabase REST silently caps responses at 1,000 rows. We paginate
    explicitly here — without this, mappings beyond row 1000 silently disappear
    from company_map and calls for those companies land as orphans.
    """
    mapping = {}
    PAGE = 1000
    page = 0
    while True:
        result = (
            sb.table("client_platform_ids")
            .select("client_id,external_id")
            .eq("platform", "callrail")
            .range(page * PAGE, page * PAGE + PAGE - 1)
            .execute()
        )
        rows = result.data
        if not rows:
            break
        for row in rows:
            mapping[row["external_id"]] = row["client_id"]
        if len(rows) < PAGE:
            break
        page += 1

    return mapping


def _strip_tracker_suffix(name: str) -> str | None:
    """Reduce a CallRail tracker name to its base client name.
    e.g. 'Greenwood Air Duct Cleaning' -> 'Greenwood Air Duct Cleaning'
         'Royal Turf Irrigation - NOCO' -> 'Royal Turf Irrigation'
         'Castle Kitchen and Bath - South' -> 'Castle Kitchen and Bath'
    """
    if not name:
        return None
    import re as _re
    s = name.strip()
    # Strip common THM zone/placement suffixes after a dash
    s = _re.sub(
        r'\s*-\s*(South Denver|North Denver|North Bay|Cedar Park|Park City|Keas popout|Lawn Care|'
        r'Bookmark|Bookmarks|In Book Ad|In Book|PopOut|Pop-Out|popout|OPP|IA|Email|Promo|'
        r'Contact|Website|Homepage|Mkt|NoCo|NOCO|EPC|North|South|Central|East|West|Denver|'
        r'CO|UT|AU|SA|SLC|NW|CW|SW|AN|AS|SAE|SAW|ND|SD|new|\(new\))(\s+(IA|OPP|PopOut|Email|Promo))?\s*$',
        '', s, flags=_re.IGNORECASE
    )
    # Drop trailing parenthetical hints
    s = _re.sub(r'\s*\([^)]*\)\s*$', '', s)
    s = _re.sub(r'\s+', ' ', s).strip(' -')
    return s if s else None


def auto_map_by_tracking_number(sb, company_map: dict) -> tuple[int, int, int]:
    """Deterministic mapping pass using `client_phone_numbers`.

    For every CallRail company that has calls in our DB, look up its tracking
    numbers in `client_phone_numbers` (role='tracking', is_historical=false).
    If a real client owns those numbers, map the company to that client.

    This runs BEFORE the fuzzy-name auto-matcher because phone-number matching
    is deterministic — it can't produce false positives like name fuzzing can.

    Self-healing: if a company is currently mapped to a [THM] house client but
    the phone lookup identifies a real owner, the mapping is corrected and any
    misattributed calls are reattached. This prevents the mis-routing class of
    bug where real-client trackers with generic THM tracker names ('TheHomeMag
    - North') were swept into the house bucket.

    Returns (new_mappings, corrected_mappings, calls_reattached).
    """
    house_clients = {row["id"]: row["name"] for row in
                     sb.table("clients").select("id,name").in_(
                         "name", ["[THM] - CO", "[THM] - UT", "[THM] - TX"]
                     ).execute().data}

    # Build phone (last 10 digits) -> real_client_id from client_phone_numbers
    PAGE = 1000
    page = 0
    phone_to_owner: dict[str, str] = {}
    while True:
        rows = (sb.table("client_phone_numbers")
                  .select("phone_number,client_id,role,is_historical")
                  .eq("role", "tracking").eq("is_historical", False)
                  .range(page * PAGE, page * PAGE + PAGE - 1).execute().data)
        if not rows:
            break
        for r in rows:
            cid = r["client_id"]
            if cid in house_clients:
                continue
            digits = "".join(c for c in (r.get("phone_number") or "") if c.isdigit())
            if len(digits) >= 10:
                phone_to_owner[digits[-10:]] = cid
        if len(rows) < PAGE:
            break
        page += 1

    if not phone_to_owner:
        return 0, 0, 0

    # Pull every (company_id, tracking_number) pair we have calls for
    page = 0
    company_trackers: dict[str, set[str]] = {}  # company_id -> set of last-10-digit tracking numbers
    while True:
        rows = (sb.table("calls")
                  .select("callrail_company_id,tracking_number")
                  .range(page * PAGE, page * PAGE + PAGE - 1).execute().data)
        if not rows:
            break
        for r in rows:
            cid = r.get("callrail_company_id")
            tn = r.get("tracking_number")
            if not cid or not tn:
                continue
            digits = "".join(c for c in tn if c.isdigit())
            if len(digits) >= 10:
                company_trackers.setdefault(cid, set()).add(digits[-10:])
        if len(rows) < PAGE:
            break
        page += 1

    # For each company, see whose phone number(s) those trackers belong to
    new_mappings = 0
    corrected_mappings = 0
    company_to_real_owner: dict[str, str] = {}
    for company_id, tracker_digits in company_trackers.items():
        owners = {phone_to_owner[d] for d in tracker_digits if d in phone_to_owner}
        if len(owners) != 1:
            # 0 = no real owner found, > 1 = multi-tenant company we can't auto-resolve
            continue
        real_owner_id = next(iter(owners))
        current_mapping = company_map.get(company_id)

        if current_mapping == real_owner_id:
            continue  # already correct
        elif current_mapping is None:
            # No mapping yet — insert
            try:
                sb.table("client_platform_ids").insert({
                    "client_id": real_owner_id,
                    "platform": "callrail",
                    "external_id": company_id,
                }).execute()
                company_map[company_id] = real_owner_id
                company_to_real_owner[company_id] = real_owner_id
                new_mappings += 1
            except Exception as e:
                log.warning(f"  insert failed for company {company_id}: {str(e)[:100]}")
        elif current_mapping in house_clients:
            # Mapped to a [THM] house client but phone says real client — correct it
            try:
                sb.table("client_platform_ids").update({"client_id": real_owner_id}).eq(
                    "platform", "callrail").eq("external_id", company_id).execute()
                log.warning(f"  CORRECTED: company {company_id} was mapped to "
                            f"{house_clients[current_mapping]}, real owner is client {real_owner_id}")
                company_map[company_id] = real_owner_id
                company_to_real_owner[company_id] = real_owner_id
                corrected_mappings += 1
            except Exception as e:
                log.warning(f"  correction failed for company {company_id}: {str(e)[:100]}")
        # If currently mapped to a different real client, leave it alone — manual mapping wins

    # Reattach any calls that were sitting on the corrected companies
    calls_reattached = 0
    if company_to_real_owner:
        for company_id, real_owner_id in company_to_real_owner.items():
            try:
                # Pull calls currently misattributed (client_id is a house client) for this company
                house_ids = list(house_clients.keys())
                if not house_ids:
                    continue
                # Update only calls currently on a house client. Need raw SQL via supabase
                # equivalent — use .in_() filter
                sb.table("calls").update({"client_id": real_owner_id}).eq(
                    "callrail_company_id", company_id).in_("client_id", house_ids).execute()
                # Also pick up unmapped calls (client_id IS NULL)
                sb.table("calls").update({"client_id": real_owner_id}).eq(
                    "callrail_company_id", company_id).is_("client_id", "null").execute()
                calls_reattached += 1
            except Exception as e:
                log.warning(f"  reattach failed for company {company_id}: {str(e)[:100]}")

    return new_mappings, corrected_mappings, calls_reattached


def auto_map_unmapped_companies(sb, company_map: dict) -> int:
    """For each CallRail company that has calls in our DB but no client mapping,
    fuzzy-match its dominant tracker name against the clients table. If a
    confident match exists, insert the mapping. Returns count of new mappings.

    Idempotent. Skips matches against [THM] house clients (those are explicit
    catch-all buckets — only manual mapping should touch them) and skips short
    candidate names (< 5 chars) to avoid false positives.
    """
    # 1. Find unmapped companies with calls + their dominant tracker names
    PAGE = 1000
    page = 0
    company_to_name = {}  # company_id -> dominant tracker name
    seen_company_ids = set()
    while True:
        result = (
            sb.table("calls")
            .select("callrail_company_id,tracking_number_name,call_time")
            .order("call_time", desc=True)
            .range(page * PAGE, page * PAGE + PAGE - 1)
            .execute()
        )
        rows = result.data
        if not rows:
            break
        for row in rows:
            cid = row.get("callrail_company_id")
            name = row.get("tracking_number_name")
            if not cid or cid in company_map or cid in seen_company_ids:
                continue
            if name and cid not in company_to_name:
                # First (most recent) non-null name wins
                company_to_name[cid] = name
                seen_company_ids.add(cid)
        if len(rows) < PAGE:
            break
        page += 1

    if not company_to_name:
        return 0

    # 2. Load all client names (excluding [THM] house clients and prospects).
    # Prospects are speculative records (often imported from a mapping spreadsheet)
    # and matching them produces too many false positives. Active/expired/cancelled/
    # dormant are real businesses that have placed orders.
    clients_by_name = {}
    page = 0
    while True:
        result = (
            sb.table("clients")
            .select("id,name,status")
            .range(page * PAGE, page * PAGE + PAGE - 1)
            .execute()
        )
        rows = result.data
        if not rows:
            break
        for row in rows:
            name = row["name"]
            if name.startswith("[THM]") or row.get("status") == "prospect":
                continue
            # Prefer active over inactive when names collide
            existing = clients_by_name.get(name.lower())
            if existing is None or (row["status"] == "active" and existing["status"] != "active"):
                clients_by_name[name.lower()] = {"id": row["id"], "status": row["status"], "name": name}
        if len(rows) < PAGE:
            break
        page += 1

    # 3. Match each unmapped company to a client
    OUT_OF_NETWORK_MARKETS = {
        'boise', 'orlando', 'jacksonville', 'columbus', 'fort collins', 'minneapolis',
        'tampa', 'miami', 'kansas city', 'oklahoma', 'seattle', 'portland', 'phoenix',
        'sacramento', 'san diego', 'norcal', 'socal', 'cape fear', 'palm beach',
        'pittsburgh', 'raleigh', 'richmond', 'sarasota', 'st louis', 'treasure coast',
        'washington dc', 'des moines', 'detroit', 'omaha', 'fort worth', 'dallas',
        'cleveland', 'cincinnati', 'indianapolis', 'nashville', 'new jersey', 'houston',
        'greenville', 'hampton roads', 'charlotte', 'broward', 'atlanta', 'daytona',
        'port charlotte', 'sw florida', 'fort myers',
    }

    new_mappings = []
    for cid, raw_name in company_to_name.items():
        # Skip CallRail tracker names referencing markets we don't operate in
        if any(m in raw_name.lower() for m in OUT_OF_NETWORK_MARKETS):
            continue
        candidate = _strip_tracker_suffix(raw_name)
        if not candidate or len(candidate) < 5:
            continue
        # Skip generic THM tracker names — these belong to [THM] house clients
        # and should be mapped manually, not auto-matched
        if candidate.lower() in {'thehomemag', 'the home mag', 'thehomemagslc',
                                  'thm', 'thm branch', 'home mag'}:
            continue
        cand_lower = candidate.lower()
        match = None

        # Exact match
        if cand_lower in clients_by_name:
            match = clients_by_name[cand_lower]
        else:
            # Word-set match: count meaningful word overlap. Catches "Greenwood Air
            # Duct Cleaning" -> "Greenwood Duct Cleaning" and "Pioneer Landscape
            # Centers" -> "Pioneer Landscape Centers (GWA Inc)" cases.
            STOPWORDS = {'the', 'and', 'of', 'inc', 'llc', 'co', 'company', 'a', '&'}
            def _words(s: str) -> set:
                import re as _re
                return {w for w in _re.split(r'[\s\-,.()]+', s.lower()) if w and w not in STOPWORDS and len(w) > 1}
            cand_words = _words(candidate)
            if len(cand_words) < 2:
                continue  # too short to safely match
            best = None
            best_score = 0
            for nl, info in clients_by_name.items():
                cli_words = _words(info["name"])
                if not cli_words:
                    continue
                overlap = cand_words & cli_words
                # Score = fraction of candidate words that appear in client name,
                # weighted by symmetric overlap (Jaccard-ish).
                if not overlap:
                    continue
                score = len(overlap) / max(len(cand_words), len(cli_words))
                # Require >=2 word overlap AND >=0.6 score AND >=60% of candidate
                # words appear in client name. Three-way guardrail prevents
                # "Air + Drain Works" matching "Air Doctor".
                if (len(overlap) >= 2 and score >= 0.6
                    and len(overlap) / len(cand_words) >= 0.6
                    and score > best_score):
                    best_score = score
                    best = info
            match = best

        if match:
            new_mappings.append({
                "client_id": match["id"],
                "platform": "callrail",
                "external_id": cid,
            })
            log.info(f"  auto-match: '{raw_name}' -> '{match['name']}' ({match['status']})")
            # Update local company_map so reattach in the same run sees it
            company_map[cid] = match["id"]

    if new_mappings:
        # Insert in chunks (Supabase REST has payload limits)
        CHUNK = 100
        for i in range(0, len(new_mappings), CHUNK):
            sb.table("client_platform_ids").insert(new_mappings[i:i + CHUNK]).execute()

    return len(new_mappings)


def build_zonal_sibling_map(sb, company_map):
    """
    For each CallRail-mapped client, find zonal sibling clients (same base name
    plus a zone suffix like " - NoCO", " - N Denver"). Returns:
        { master_client_id: { zone_abbrev: sibling_client_id } }

    Supports shared-CallRail / per-zone-MagManager setups (e.g., Home Improvement
    Express) where one CallRail account carries numbers for multiple zone-specific
    client records. Routes calls to the sibling whose suffix matches the call's
    parsed zone.
    """
    # Patterns that map a client-name suffix to a zone abbreviation.
    # Keep aligned with TRACKER_ZONE_MAP / setup/backfill_tracker_names.py.
    # Each suffix maps to a list of routing-key zones. A market-level suffix
    # ("Austin", "San Antonio") covers its zones AND the market fallback, so a
    # call tagged AN, AS, or AU all route to the "- Austin" sibling.
    suffix_to_zones = {
        "noco": ["NOCO"], "northern co": ["NOCO"],
        "n denver": ["ND"], "north denver": ["ND"], "nd": ["ND"],
        "s denver": ["SD"], "south denver": ["SD"], "sd": ["SD"],
        "epc": ["EPC"], "co springs": ["EPC"], "colorado springs": ["EPC"],
        "nw": ["NW"], "north wasatch": ["NW"], "ogden": ["NW"],
        "cw": ["CW"], "central wasatch": ["CW"], "slc": ["CW"], "salt lake": ["CW"],
        "sw": ["SW"], "south wasatch": ["SW"],
        "an": ["AN"], "austin n": ["AN"], "austin north": ["AN"], "au north": ["AN"],
        "as": ["AS"], "austin s": ["AS"], "austin south": ["AS"], "au south": ["AS"],
        "sae": ["SAE"], "sa east": ["SAE"], "san antonio e": ["SAE"],
        "saw": ["SAW"], "sa west": ["SAW"], "san antonio w": ["SAW"],
        # Market-level siblings absorb all zones in the market + market fallback
        "austin": ["AN", "AS", "AU"], "au": ["AN", "AS", "AU"],
        "san antonio": ["SAE", "SAW", "SA"], "sa": ["SAE", "SAW", "SA"],
    }

    master_ids = set(company_map.values())
    if not master_ids:
        return {}

    # Fetch master client names
    masters = {}
    for i in range(0, len(master_ids), 100):
        batch = list(master_ids)[i:i + 100]
        result = sb.table("clients").select("id,name").in_("id", batch).execute()
        for row in result.data:
            masters[row["id"]] = row["name"]

    # OPTIMIZATION: instead of 2 API calls per master (~1,200 total), pull all
    # active clients ONCE and do prefix matching in Python. Cuts the step from
    # ~90 seconds to ~1 second.
    all_active = []
    page = 0
    while True:
        chunk = (sb.table("clients").select("id,name")
                 .eq("status", "active")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        all_active.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1

    # Build a lowercase-name index for fast prefix lookups
    by_lower_name: dict[str, list[dict]] = {}
    for c in all_active:
        first_word = c["name"].lower().split()[0] if c["name"] else ""
        by_lower_name.setdefault(first_word, []).append(c)

    sibling_map = {}
    for master_id, master_name in masters.items():
        candidates = []
        master_lower = master_name.lower()
        # Look at clients sharing the first word with the master (small subset)
        first_word = master_lower.split()[0] if master_lower else ""
        for c in by_lower_name.get(first_word, []):
            if c["id"] == master_id:
                continue
            cname_lower = c["name"].lower()
            for sep in (" - ", " "):
                prefix_lower = f"{master_lower}{sep}"
                if cname_lower.startswith(prefix_lower):
                    suffix = c["name"][len(prefix_lower):].strip().lower()
                    if suffix:
                        candidates.append((suffix, c["id"]))
                        break

        zone_to_sibling = {}
        for suffix, sibling_id in candidates:
            zones = suffix_to_zones.get(suffix)
            if zones:
                for z in zones:
                    if z not in zone_to_sibling:
                        zone_to_sibling[z] = sibling_id
        if zone_to_sibling:
            sibling_map[master_id] = zone_to_sibling
    return sibling_map


def build_callrail_tag_to_local_map(sb):
    """
    Build a mapping of CallRail tag id (int) -> Supabase tag uuid.
    Uses tag name normalization (case-insensitive) since we deduped tags by name.
    """
    # Local tags by lowercased name
    all_local = []
    offset = 0
    while True:
        batch = sb.table("tags").select("id,name").range(offset, offset + 999).execute()
        all_local.extend(batch.data)
        if len(batch.data) < 1000:
            break
        offset += 1000
    name_to_local = {t["name"].lower(): t["id"] for t in all_local}

    # Fetch all CallRail tag definitions from each account, build cr_id -> local
    cr_id_to_local = {}
    for acct_id, _ in CALLRAIL_ACCOUNTS:
        url = f"{CALLRAIL_BASE_URL}/a/{acct_id}/tags.json"
        page = 1
        while True:
            resp = request_with_retry(url, headers=callrail_headers(), params={"per_page": PER_PAGE, "page": page})
            if resp.status_code == 429:
                continue
            resp.raise_for_status()
            data = resp.json()
            for t in data.get("tags", []):
                name = (t.get("name") or "").strip().lower()
                local = name_to_local.get(name)
                if local:
                    cr_id_to_local[t["id"]] = local
            total_pages = data.get("total_pages", 1)
            if page >= total_pages:
                break
            page += 1
    return cr_id_to_local


def transform_call(call: dict, company_map: dict, zone_lookup: dict = None, sibling_map: dict = None) -> dict | None:
    """
    Transform a CallRail API call object into a Supabase calls row.
    Returns None if the call should be skipped.
    """
    caller_number = strip_phone(call.get("customer_phone_number", ""))

    callrail_id = str(call.get("id", ""))
    if not callrail_id:
        return None

    duration = call.get("duration", 0) or 0
    answered = call.get("answered", False)
    company_id = str(call.get("company_id", "")) if call.get("company_id") else None

    # Look up client from company mapping
    client_id = company_map.get(company_id) if company_id else None

    # Parse zone from tracker name
    tracker_name = call.get("source_name") or call.get("tracker_name")
    zone_abbrev = parse_zone_from_tracker_name(tracker_name)
    zone_id = zone_lookup.get(zone_abbrev) if zone_lookup and zone_abbrev else None

    # Zone-aware routing: if the master client has a zonal sibling matching
    # the call's zone, route the call to the sibling instead of the master.
    if client_id and zone_abbrev and sibling_map:
        sibling = sibling_map.get(client_id, {}).get(zone_abbrev)
        if sibling:
            client_id = sibling

    row = {
        "callrail_id": callrail_id,
        "callrail_company_id": company_id,
        "client_id": client_id,
        "call_time": call.get("start_time"),
        "duration_seconds": duration,
        "is_missed": not answered,
        "is_first_time": call.get("first_call", False) or False,
        "caller_number": call.get("customer_phone_number"),
        "caller_name": call.get("customer_name"),
        "caller_city": call.get("customer_city"),
        "caller_state": call.get("customer_state"),
        "tracking_number": call.get("tracking_phone_number"),
        "tracking_number_name": tracker_name,
        "source": call.get("source"),
        "campaign": call.get("campaign"),
        "voicemail": call.get("voicemail", False) or False,
        "recording_url": call.get("recording"),
        "zone_id": zone_id,
    }

    # Transcript/summary
    summary = call.get("lead_explanation") or call.get("call_summary")
    if summary:
        row["has_transcript"] = True
        row["transcript_summary"] = summary
    else:
        row["has_transcript"] = False

    return row


def reattach_orphan_calls(sb, company_map: dict, sibling_map: dict) -> int:
    """
    Find calls with client_id=NULL but a callrail_company_id that IS in the
    current mapping, and attach them to the correct client (respecting
    zonal sibling routing). Idempotent: if no orphans recoverable, no-op.

    Runs at the start of every ETL pass. Protects against the "mapping was
    added after the call came in" pattern, which is the cause of all 226
    orphans we backfilled on 2026-04-27.
    """
    if not company_map:
        return 0

    # Pull all NULL-client_id calls whose company_id is now mapped.
    # Chunk the company_id list to avoid URL-length limits — Supabase REST 414s
    # when passing 800+ IDs in a single .in_() filter.
    PAGE = 1000
    company_ids = list(company_map.keys())
    CHUNK = 100
    orphans = []
    for i in range(0, len(company_ids), CHUNK):
        batch_ids = company_ids[i:i + CHUNK]
        page = 0
        while True:
            chunk = (
                sb.table("calls")
                .select("id,callrail_company_id,zone_id")
                .is_("client_id", "null")
                .in_("callrail_company_id", batch_ids)
                .range(page * PAGE, page * PAGE + PAGE - 1)
                .execute()
                .data
            )
            if not chunk:
                break
            orphans.extend(chunk)
            if len(chunk) < PAGE:
                break
            page += 1

    if not orphans:
        return 0

    # zone_id -> abbreviation lookup (for sibling routing parity with transform_call)
    zones_result = sb.table("zones").select("id,abbreviation").execute()
    id_to_abbr = {z["id"]: z["abbreviation"] for z in zones_result.data}

    # Group updates by target client_id so we can do batch UPDATEs by id list.
    by_target = {}
    for o in orphans:
        cr_id = o["callrail_company_id"]
        client_id = company_map.get(cr_id)
        if not client_id:
            continue
        # Apply zonal sibling routing (mirrors transform_call logic)
        zone_abbr = id_to_abbr.get(o["zone_id"])
        if zone_abbr and sibling_map:
            sib = sibling_map.get(client_id, {}).get(zone_abbr)
            if sib:
                client_id = sib
        by_target.setdefault(client_id, []).append(o["id"])

    total = 0
    for client_id, call_ids in by_target.items():
        for i in range(0, len(call_ids), 500):
            batch = call_ids[i:i + 500]
            sb.table("calls").update({"client_id": client_id}).in_("id", batch).execute()
            total += len(batch)
    return total


def upsert_calls(sb, rows: list[dict]):
    """
    Upsert call rows into Supabase in batches.
    Uses callrail_id as the conflict target.
    """
    BATCH_SIZE = 100
    MAX_ATTEMPTS = 4
    total_upserted = 0

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        last_err = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                sb.table("calls").upsert(batch, on_conflict="callrail_id").execute()
                last_err = None
                break
            except Exception as e:
                last_err = e
                if attempt == MAX_ATTEMPTS - 1:
                    break
                wait = 2 ** attempt  # 1s, 2s, 4s
                log.warning(f"  upsert error (attempt {attempt + 1}/{MAX_ATTEMPTS}): {str(e)[:120]} — retrying in {wait}s")
                time.sleep(wait)
        if last_err is not None:
            raise last_err
        total_upserted += len(batch)
        if total_upserted % 500 == 0:
            log.info(f"  ... {total_upserted} calls upserted")

    return total_upserted


def sync_call_tags(sb, raw_calls, callrail_to_local_call_id, callrail_to_local_tag):
    """Per-call replace semantics: for each call we re-fetched, set its call_tags
    rows = exactly what CallRail returned. Inserts new pairs and deletes stale ones.
    Without this, tag corrections in CallRail (especially removals) would never
    propagate to Supabase. Returns (inserts_applied, deletes_applied)."""
    desired_per_call: dict[str, set] = {}
    for call in raw_calls:
        cr_id = str(call.get("id", ""))
        local_call_id = callrail_to_local_call_id.get(cr_id)
        if not local_call_id:
            continue
        desired = desired_per_call.setdefault(local_call_id, set())
        for t in (call.get("tags") or []):
            local_tag_id = callrail_to_local_tag.get(t.get("id"))
            if local_tag_id:
                desired.add(local_tag_id)

    if not desired_per_call:
        return 0, 0

    # Read current pairs for these calls
    current_per_call: dict[str, set] = {}
    call_ids = list(desired_per_call.keys())
    LOOKUP_BATCH = 200
    for i in range(0, len(call_ids), LOOKUP_BATCH):
        chunk = call_ids[i : i + LOOKUP_BATCH]
        result = sb.table("call_tags").select("call_id,tag_id").in_("call_id", chunk).execute()
        for r in result.data:
            current_per_call.setdefault(r["call_id"], set()).add(r["tag_id"])

    # Compute diff
    to_insert: list[dict] = []
    to_delete: dict[str, set] = {}
    for local_call_id, desired in desired_per_call.items():
        current = current_per_call.get(local_call_id, set())
        adds = desired - current
        removes = current - desired
        for tag_id in adds:
            to_insert.append({"call_id": local_call_id, "tag_id": tag_id})
        if removes:
            to_delete[local_call_id] = removes

    inserts_applied = 0
    if to_insert:
        BATCH = 500
        for i in range(0, len(to_insert), BATCH):
            batch = to_insert[i:i + BATCH]
            try:
                sb.table("call_tags").upsert(batch, on_conflict="call_id,tag_id").execute()
                inserts_applied += len(batch)
            except Exception as e:
                log.warning(f"  call_tags insert batch failed, retrying individually: {str(e)[:100]}")
                for row in batch:
                    try:
                        sb.table("call_tags").upsert(row, on_conflict="call_id,tag_id").execute()
                        inserts_applied += 1
                    except Exception:
                        pass

    deletes_applied = 0
    if to_delete:
        for call_id, tag_ids in to_delete.items():
            try:
                sb.table("call_tags").delete().eq("call_id", call_id).in_("tag_id", list(tag_ids)).execute()
                deletes_applied += len(tag_ids)
            except Exception as e:
                log.warning(f"  call_tags delete failed for call {call_id}: {str(e)[:100]}")

    return inserts_applied, deletes_applied


def upsert_call_tags(sb, raw_calls, callrail_to_local_call_id, callrail_to_local_tag):
    """Backwards-compatible shim. Calls sync_call_tags and returns total inserts
    (matches the old return shape)."""
    inserts, deletes = sync_call_tags(sb, raw_calls, callrail_to_local_call_id, callrail_to_local_tag)
    if deletes:
        log.info(f"  {deletes} stale call_tag pairs deleted (tags removed in CallRail)")
    return inserts


def run(start_date: str, end_date: str, dry_run: bool = False):
    log.info(f"CallRail ETL — {start_date} to {end_date}")

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Step 1: Build company -> client mapping
    log.info("Step 1: Building company-to-client mapping...")
    company_map = build_company_to_client_map(sb)
    log.info(f"  {len(company_map)} CallRail companies mapped to clients")

    # Step 1a: Deterministic mapping by tracking number. This is the strong signal —
    # if a CallRail company's tracking numbers match an entry in client_phone_numbers
    # (role='tracking', not historical) for a real client, that's the real owner.
    # Self-heals companies wrongly bucketed into [THM] - CO/UT/TX house clients.
    if not dry_run:
        log.info("Step 1a: Phone-number-based mapping (deterministic)...")
        new_phone, corrected, reattached = auto_map_by_tracking_number(sb, company_map)
        log.info(f"  {new_phone} new mappings, {corrected} corrected from house bucket, "
                 f"{reattached} companies had calls reattached")

    # Step 1b: Auto-link still-unmapped CallRail companies to clients by tracker name.
    # Fuzzy fallback for cases where client_phone_numbers doesn't have the tracker yet.
    if not dry_run:
        log.info("Step 1b: Auto-matching unmapped CallRail companies to clients...")
        new_links = auto_map_unmapped_companies(sb, company_map)
        log.info(f"  {new_links} new auto-mappings created")

    # Step 1c: Build zone abbreviation -> zone_id lookup
    zones_result = sb.table("zones").select("id,abbreviation").execute()
    zone_lookup = {z["abbreviation"]: z["id"] for z in zones_result.data if z.get("abbreviation")}
    log.info(f"  {len(zone_lookup)} zones loaded")

    # Step 1c.5: Build zonal-sibling routing map
    sibling_map = build_zonal_sibling_map(sb, company_map)
    sibling_total = sum(len(v) for v in sibling_map.values())
    log.info(f"  {len(sibling_map)} clients with zonal siblings ({sibling_total} total routes)")

    # Step 1d: Reattach historical orphans whose mapping now exists.
    # When a CallRail platform_id is added AFTER calls have already arrived
    # (e.g., a new client is mapped today), prior calls remain client_id=NULL.
    # Sweep them up at the start of every run so they appear in rep rundowns.
    if not dry_run:
        log.info("Step 1d: Reattaching orphan calls with newly-known mappings...")
        reattached = reattach_orphan_calls(sb, company_map, sibling_map)
        log.info(f"  reattached {reattached} previously-orphan calls")

    # Step 2: Build CallRail tag id -> local tag id mapping
    log.info("Step 2: Building tag mapping...")
    tag_map = build_callrail_tag_to_local_map(sb)
    log.info(f"  {len(tag_map)} CallRail tag ids mapped")

    grand_total = 0
    grand_skipped = 0
    grand_unmatched = 0
    grand_tag_pairs = 0

    for account_id, account_name in CALLRAIL_ACCOUNTS:
        log.info(f"\n--- {account_name} ({account_id}) ---")

        # Fetch calls from CallRail
        log.info("Fetching calls from CallRail API...")
        raw_calls = list(fetch_calls(start_date, end_date, account_id=account_id))
        log.info(f"  {len(raw_calls)} calls fetched from API")

        # Transform
        rows = []
        skipped = 0
        unmatched = 0
        for call in raw_calls:
            row = transform_call(call, company_map, zone_lookup, sibling_map)
            if row is None:
                skipped += 1
                continue
            if row["client_id"] is None:
                unmatched += 1
                # Diagnostic: are we losing a mapping here? If so, log loud.
                cid = row.get("callrail_company_id")
                if cid and cid in company_map:
                    log.warning(
                        f"  TRANSFORM_CALL BUG: call {row['callrail_id']} has company_id "
                        f"{cid} which IS in company_map -> {company_map[cid]} but client_id is None. "
                        f"call dict company_id={call.get('company_id')!r} type={type(call.get('company_id')).__name__}"
                    )
            rows.append(row)

        log.info(f"  {len(rows)} calls to upsert, {skipped} skipped, {unmatched} unmatched")

        if dry_run:
            log.info("DRY RUN — skipping upsert")
        elif rows:
            # Upsert calls
            total = upsert_calls(sb, rows)
            log.info(f"  {total} calls upserted")
            grand_total += total

            # Re-fetch the local call IDs for tag linking
            callrail_ids = [r["callrail_id"] for r in rows]
            cr_to_local = {}
            for i in range(0, len(callrail_ids), 100):
                batch = callrail_ids[i:i+100]
                result = sb.table("calls").select("id,callrail_id").in_("callrail_id", batch).execute()
                for r in result.data:
                    cr_to_local[r["callrail_id"]] = r["id"]

            # Insert call_tags
            tag_count = upsert_call_tags(sb, raw_calls, cr_to_local, tag_map)
            log.info(f"  {tag_count} call_tag pairs upserted")
            grand_tag_pairs += tag_count

        grand_skipped += skipped
        grand_unmatched += unmatched

    # Final reattach pass: catch any orphans created during this run.
    # transform_call sometimes inserts client_id=NULL even when the company is in
    # client_platform_ids (root cause unclear — possibly intermittent CallRail API
    # field-naming quirks). Self-heal by re-running the lookup at the end.
    if not dry_run and grand_total > 0:
        log.info("\nFinal sweep: reattaching any orphans created during this run...")
        post_reattached = reattach_orphan_calls(sb, company_map, sibling_map)
        log.info(f"  post-upsert reattached {post_reattached} calls")
        if post_reattached > 0:
            log.warning(
                f"  NOTE: {post_reattached} calls were inserted with NULL client_id "
                "despite valid company mapping — investigate transform_call."
            )

    log.info(f"\nETL COMPLETE — {grand_total} calls, {grand_tag_pairs} call_tags, {grand_skipped} excluded, {grand_unmatched} unmatched")


def main():
    parser = argparse.ArgumentParser(description="CallRail ETL — pull calls into Supabase")
    parser.add_argument("--days", type=int, default=30, help="Pull calls from last N days (default: 30)")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD), overrides --days")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no writes")
    args = parser.parse_args()

    # Validate credentials
    missing = []
    if not SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not SUPABASE_KEY:
        missing.append("SUPABASE_KEY")
    if not CALLRAIL_API_KEY:
        missing.append("CALLRAIL_API_KEY")
    if not CALLRAIL_ACCOUNT_ID:
        missing.append("CALLRAIL_ACCOUNT_ID")

    if missing:
        log.error(f"Missing required env vars: {', '.join(missing)}")
        log.error("Add them to your .env file and try again.")
        sys.exit(1)

    # Determine date range
    now = datetime.now(timezone.utc)
    if args.start:
        start_date = args.start
    else:
        start_date = (now - timedelta(days=args.days)).strftime("%Y-%m-%d")

    end_date = args.end or now.strftime("%Y-%m-%d")

    run(start_date, end_date, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
