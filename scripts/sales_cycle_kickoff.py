"""Sales Cycle Kickoff package for Mandy — per-market draft generator.

Produces a Markdown email draft Masen reviews and sends to Mandy at the start
of every selling cycle. Five sections:

  1. Market Analysis xlsx reference (path to latest in output/)
  2. Top tier upgrade candidates (premium half-page rate + low call performance)
  3. Top 5 underperformers (lowest calls/$1k regardless of size)
  4. Seasonality trends (placeholder — Claude fills via WebSearch when running)
  5. Top performing categories + a success story

Usage:
    python -m scripts.sales_cycle_kickoff CO
    python -m scripts.sales_cycle_kickoff TX
    python -m scripts.sales_cycle_kickoff UT

Writes to: 02 Projects/Sales Cycle Kickoff/Drafts/
   [C] Sales Cycle Kickoff - {MK} M-D-YYYY.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

from scripts.analyze import query

WORKSPACE = Path(r"C:\Users\MasenSpring\OneDrive - TheHomeMagWest")
DRAFTS_DIR = WORKSPACE / "02 Projects" / "Sales Cycle Kickoff" / "Drafts"
OUTPUT_DIR = WORKSPACE / "Supabase Data Hub" / "output"

MARKETS: dict[str, dict] = {
    "CO": {"codes": ("CO",), "label": "Colorado",
           "ma_glob": "[[]C[]] CO Market Analysis *.xlsx"},
    "TX": {"codes": ("AU", "SA"), "label": "Texas (Austin + San Antonio)",
           "ma_glob": "[[]C[]] TX Market Analysis *.xlsx"},
    "UT": {"codes": ("UT",), "label": "Utah",
           "ma_glob": "[[]C[]] UT Market Analysis *.xlsx"},
}

# Brands where qualified-calls/$1k is the wrong performance metric — showroom or
# walk-in driven, foot traffic / events / digital are the real conversion paths.
# Match is case-insensitive substring on the brand display name.
UNDERPERF_EXCLUDE_PATTERNS: tuple[str, ...] = (
    "patio splash",   # showroom-driven, calls/$1k is wrong metric
    "j & k roofing",  # rep already met with them — no need to re-flag
    # Add more here as they come up.
)


def find_latest_market_analysis(mk: str) -> Path | None:
    candidates = list(OUTPUT_DIR.glob(MARKETS[mk]["ma_glob"]))
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


# ---------- Section 2: Upgrade candidates --------------------------------
UPGRADE_SQL = """
WITH dw_yr AS (SELECT (CURRENT_DATE - INTERVAL '12 months')::date AS d),
     dw_90 AS (SELECT (CURRENT_DATE - INTERVAL '90 days')::date AS d),
-- Tracked clients = have a CallRail platform_id link OR have calls with a
-- callrail_company_id in the last 12mo. This is the apples-to-apples population
-- for medians and averages — keeps untracked monsters (RBA, Liberty, etc.) and
-- mapping stubs out of the comparison baselines.
direct_cr AS (
  SELECT DISTINCT cpi.client_id
  FROM client_platform_ids cpi
  WHERE cpi.platform = 'callrail' AND cpi.external_id IS NOT NULL
),
calls_cr AS (
  SELECT DISTINCT c.client_id
  FROM calls c CROSS JOIN dw_yr
  WHERE c.callrail_company_id IS NOT NULL
    AND c.call_time >= dw_yr.d::timestamptz
),
tracked_clients AS (
  SELECT client_id FROM direct_cr
  UNION
  SELECT client_id FROM calls_cr
),
hp_12mo AS (
  SELECT o.client_id, o.zone_id, z.abbreviation AS zone, o.sales_rep,
         COUNT(*) AS hp_orders,
         SUM(o.gross) AS hp_spend_12mo,
         AVG(o.gross) AS avg_per_hp,
         MIN(o.issue_date_parsed) AS first_hp_issue
  FROM orders o
  JOIN zones z ON z.id = o.zone_id
  JOIN markets m ON m.id = o.market_id
  JOIN clients cl ON cl.id = o.client_id
  CROSS JOIN dw_yr
  WHERE m.code IN ({MK_CODES})
    AND o.size = '1/2 Page'
    AND NOT o.is_cross_book
    AND NOT o.is_deck_package
    AND o.issue_date_parsed BETWEEN dw_yr.d AND CURRENT_DATE
    AND cl.status = 'active'
    AND NOT cl.is_mapping_stub
  GROUP BY o.client_id, o.zone_id, z.abbreviation, o.sales_rep
  HAVING COUNT(*) >= 4
),
-- Median computed ONLY over tracked clients so the baseline is apples-to-apples
zone_median AS (
  SELECT hp.zone,
         PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hp.avg_per_hp) AS median_avg_hp
  FROM hp_12mo hp
  WHERE hp.client_id IN (SELECT client_id FROM tracked_clients)
  GROUP BY hp.zone
),
hp_90d AS (
  SELECT o.client_id, o.zone_id, SUM(o.gross) AS spend_90,
         COUNT(DISTINCT o.issue_date_parsed) AS issues_90
  FROM orders o
  JOIN markets m ON m.id = o.market_id
  CROSS JOIN dw_90
  WHERE m.code IN ({MK_CODES})
    AND o.size = '1/2 Page'
    AND NOT o.is_cross_book
    AND NOT o.is_deck_package
    AND o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE
  GROUP BY o.client_id, o.zone_id
),
-- Calls aggregated PER CLIENT across ALL zones (sibling routing + null zone_id mean
-- zone filtering throws away most of the data — see calibration query 2026-05-06).
calls_90d_client AS (
  SELECT c.client_id,
         COUNT(*) FILTER (WHERE c.is_qualified) AS qual_calls
  FROM calls c
  CROSS JOIN dw_90
  WHERE c.call_time >= dw_90.d::timestamptz
    AND c.call_time < (CURRENT_DATE + INTERVAL '1 day')::timestamptz
  GROUP BY c.client_id
),
-- All zones the client runs in this market (last 12mo, any size) — for the
-- "Also Runs In" column so Mandy can see multi-zone presence at a glance.
client_zones_in_market AS (
  SELECT o.client_id,
         STRING_AGG(DISTINCT z.abbreviation, ', ' ORDER BY z.abbreviation) AS all_zones
  FROM orders o
  JOIN zones z ON z.id = o.zone_id
  JOIN markets m ON m.id = o.market_id
  CROSS JOIN dw_yr
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed BETWEEN dw_yr.d AND CURRENT_DATE
  GROUP BY o.client_id
)
SELECT
  hp.zone, hp.sales_rep AS rep, cl.name AS client,
  -- "Also Runs In" = all zones in this market minus the half-page zone
  NULLIF(REGEXP_REPLACE(
    REGEXP_REPLACE(COALESCE(czm.all_zones, ''), '(^|, )' || hp.zone || '(, |$)', '\\1'),
    ', $', ''
  ), '') AS also_runs,
  hp.hp_orders,
  hp.hp_spend_12mo,
  hp.avg_per_hp,
  (hp.avg_per_hp - zm.median_avg_hp) AS over_median,
  COALESCE(c90.qual_calls, 0) AS qual_calls_90d,
  COALESCE(h90.spend_90, 0) AS hp_spend_90d,
  CASE WHEN COALESCE(h90.spend_90, 0) > 0
       THEN COALESCE(c90.qual_calls, 0) / (h90.spend_90 / 1000.0)
  END AS qual_calls_per_1k
FROM hp_12mo hp
JOIN clients cl ON cl.id = hp.client_id
JOIN zone_median zm ON zm.zone = hp.zone
LEFT JOIN client_zones cz ON cz.client_id = hp.client_id AND cz.zone_id = hp.zone_id
LEFT JOIN hp_90d h90 ON h90.client_id = hp.client_id AND h90.zone_id = hp.zone_id
LEFT JOIN calls_90d_client c90 ON c90.client_id = hp.client_id
LEFT JOIN client_zones_in_market czm ON czm.client_id = hp.client_id
WHERE hp.client_id IN (SELECT client_id FROM tracked_clients)  -- tracked-only candidates
  AND cl.has_call_tracking = TRUE
  AND COALESCE(cz.has_call_tracking, FALSE) = TRUE
  AND hp.avg_per_hp > zm.median_avg_hp + 50
  AND COALESCE(h90.spend_90, 0) > 0
  AND hp.first_hp_issue <= (CURRENT_DATE - INTERVAL '90 days')::date
  AND COALESCE(h90.issues_90, 0) >= 2
  AND (
    (COALESCE(c90.qual_calls, 0) / NULLIF(h90.spend_90 / 1000.0, 0)) < 2.5
    OR COALESCE(c90.qual_calls, 0) = 0
  )
ORDER BY qual_calls_per_1k ASC NULLS FIRST, over_median DESC
LIMIT 5
"""


# ---------- Section 3: Top 5 underperformers (overall) -------------------
UNDERPERF_SQL = """
WITH dw_yr AS (SELECT (CURRENT_DATE - INTERVAL '12 months')::date AS d),
     dw_90 AS (SELECT (CURRENT_DATE - INTERVAL '90 days')::date AS d),
-- Sibling group key for each client: the CallRail company_id they share, derived
-- from EITHER a direct platform_id link OR an actual call routing in the last 12mo.
-- This lets HIE's 5 client records collapse into one brand row.
direct_cr AS (
  SELECT DISTINCT cpi.client_id, cpi.external_id AS company_id
  FROM client_platform_ids cpi
  WHERE cpi.platform = 'callrail' AND cpi.external_id IS NOT NULL
),
calls_cr AS (
  SELECT DISTINCT c.client_id, c.callrail_company_id AS company_id
  FROM calls c
  CROSS JOIN dw_yr
  WHERE c.callrail_company_id IS NOT NULL
    AND c.call_time >= dw_yr.d::timestamptz
),
client_company AS (
  SELECT client_id, company_id FROM direct_cr
  UNION
  SELECT client_id, company_id FROM calls_cr
),
client_groups AS (
  SELECT client_id, MIN(company_id) AS group_key
  FROM client_company
  GROUP BY client_id
),
-- Aggregate spend + meta across all sibling clients in this market
brand_spend AS (
  SELECT
    cg.group_key,
    (ARRAY_AGG(cl.name ORDER BY length(cl.name), cl.name))[1] AS display_name,
    COUNT(DISTINCT cl.id) AS member_count,
    STRING_AGG(DISTINCT z.abbreviation, ', ' ORDER BY z.abbreviation) AS zones,
    (ARRAY_AGG(o.sales_rep ORDER BY o.issue_date_parsed DESC))[1] AS latest_rep,
    (ARRAY_AGG(cl.category ORDER BY length(cl.name), cl.name))[1] AS category,
    MIN(o.issue_date_parsed) AS first_issue,
    COUNT(DISTINCT o.issue_date_parsed)
      FILTER (WHERE o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE) AS issues_90,
    SUM(o.gross)
      FILTER (WHERE o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE) AS spend_90d
  FROM orders o
  JOIN clients cl ON cl.id = o.client_id
  JOIN zones z ON z.id = o.zone_id
  JOIN markets m ON m.id = o.market_id
  JOIN client_groups cg ON cg.client_id = cl.id
  CROSS JOIN dw_yr CROSS JOIN dw_90
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed BETWEEN dw_yr.d AND CURRENT_DATE
    AND cl.status = 'active'
    AND NOT cl.is_mapping_stub
    AND cl.has_call_tracking = TRUE  -- source-of-truth tracking flag
  GROUP BY cg.group_key
  HAVING BOOL_OR(COALESCE((
    SELECT cz.has_call_tracking FROM client_zones cz
    WHERE cz.client_id = cl.id AND cz.zone_id = z.id LIMIT 1
  ), FALSE)) = TRUE  -- at least one of the brand's zones must be tracked too
),
brand_calls AS (
  SELECT cg.group_key,
         COUNT(*) AS total_calls,
         COUNT(*) FILTER (WHERE c.is_qualified) AS qual_calls
  FROM calls c
  JOIN client_groups cg ON cg.client_id = c.client_id
  CROSS JOIN dw_90
  WHERE c.call_time >= dw_90.d::timestamptz
    AND c.call_time < (CURRENT_DATE + INTERVAL '1 day')::timestamptz
  GROUP BY cg.group_key
),
-- Distinct ad products (sizes) the brand ran in the 90d window across its
-- sibling client_ids in this market. Sorted by frequency desc (most-run first).
brand_products AS (
  SELECT group_key,
         STRING_AGG(size, ', ' ORDER BY n DESC, size) AS products
  FROM (
    SELECT cg.group_key, o.size, COUNT(*) AS n
    FROM orders o
    JOIN client_groups cg ON cg.client_id = o.client_id
    JOIN markets m ON m.id = o.market_id
    CROSS JOIN dw_90
    WHERE m.code IN ({MK_CODES})
      AND o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE
      AND o.size IS NOT NULL
    GROUP BY cg.group_key, o.size
  ) sz
  GROUP BY group_key
)
SELECT
  bs.display_name AS client,
  COALESCE(bs.category, '—') AS category,
  bs.zones,
  bs.latest_rep AS rep,
  bs.member_count,
  COALESCE(bp.products, '—') AS products,
  bs.spend_90d,
  COALESCE(bc.total_calls, 0) AS total_calls_90d,
  COALESCE(bc.qual_calls, 0) AS qual_calls_90d,
  COALESCE(bc.qual_calls, 0) / (bs.spend_90d / 1000.0) AS qual_calls_per_1k
FROM brand_spend bs
LEFT JOIN brand_calls bc ON bc.group_key = bs.group_key
LEFT JOIN brand_products bp ON bp.group_key = bs.group_key
WHERE bs.spend_90d >= 1500
  AND bs.first_issue <= (CURRENT_DATE - INTERVAL '90 days')::date  -- consistency
  AND bs.issues_90 >= 2  -- ran in 2+ issues during the 90d window
ORDER BY qual_calls_per_1k ASC, bs.spend_90d DESC
LIMIT 15  -- pulled wider so post-filter exclusions still leave 5 to show
"""


# ---------- Section 5: Top performing categories + success story --------
TOP_CATS_SQL = """
WITH dw_yr AS (SELECT (CURRENT_DATE - INTERVAL '12 months')::date AS d),
     dw_90 AS (SELECT (CURRENT_DATE - INTERVAL '90 days')::date AS d),
direct_cr AS (
  SELECT DISTINCT cpi.client_id
  FROM client_platform_ids cpi
  WHERE cpi.platform = 'callrail' AND cpi.external_id IS NOT NULL
),
calls_cr AS (
  SELECT DISTINCT c.client_id
  FROM calls c CROSS JOIN dw_yr
  WHERE c.callrail_company_id IS NOT NULL
    AND c.call_time >= dw_yr.d::timestamptz
),
tracked_clients AS (
  SELECT client_id FROM direct_cr
  UNION
  SELECT client_id FROM calls_cr
),
spend_90 AS (
  SELECT o.client_id, SUM(o.gross) AS spend_90d
  FROM orders o
  JOIN markets m ON m.id = o.market_id
  CROSS JOIN dw_90
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE
  GROUP BY o.client_id
),
calls_90 AS (
  SELECT c.client_id, COUNT(*) FILTER (WHERE c.is_qualified) AS qual_calls
  FROM calls c
  CROSS JOIN dw_90
  WHERE c.call_time >= dw_90.d::timestamptz
  GROUP BY c.client_id
)
SELECT
  COALESCE(cl.category, 'Uncategorized') AS category,
  COUNT(DISTINCT cl.id) AS clients,
  SUM(s.spend_90d) AS total_spend_90d,
  SUM(COALESCE(c.qual_calls, 0)) AS total_qual_calls_90d,
  CASE WHEN SUM(s.spend_90d) > 0
       THEN SUM(COALESCE(c.qual_calls, 0)) / (SUM(s.spend_90d) / 1000.0)
  END AS calls_per_1k
FROM spend_90 s
JOIN clients cl ON cl.id = s.client_id
LEFT JOIN calls_90 c ON c.client_id = s.client_id
WHERE cl.status = 'active'
  AND NOT cl.is_mapping_stub
  AND cl.id IN (SELECT client_id FROM tracked_clients)  -- tracked-only baseline
  AND cl.category IS NOT NULL
GROUP BY cl.category
HAVING COUNT(DISTINCT cl.id) >= 3
   AND SUM(s.spend_90d) >= 5000
ORDER BY calls_per_1k DESC NULLS LAST
LIMIT 5
"""


NEW_CLIENTS_SQL = """
WITH dw_90 AS (SELECT (CURRENT_DATE - INTERVAL '90 days')::date AS d),
-- Each client's first ACTUALLY-RUN issue in this market (no future bookings).
-- A client with only future orders booked isn't "new" yet — they haven't started.
first_in_market AS (
  SELECT o.client_id, MIN(o.issue_date_parsed) AS first_issue
  FROM orders o
  JOIN markets m ON m.id = o.market_id
  JOIN zones z ON z.id = o.zone_id
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed IS NOT NULL
    AND o.issue_date_parsed <= CURRENT_DATE
  GROUP BY o.client_id
),
-- Opening rep = sales_rep on the earliest order
opening_rep AS (
  SELECT DISTINCT ON (o.client_id) o.client_id, o.sales_rep
  FROM orders o
  JOIN markets m ON m.id = o.market_id
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed IS NOT NULL
    AND o.sales_rep IS NOT NULL AND o.sales_rep <> ''
  ORDER BY o.client_id, o.issue_date_parsed ASC, o.created_at ASC
),
-- Issues run + gross spent so far in this market (only past, not future-booked)
to_date AS (
  SELECT o.client_id,
         COUNT(DISTINCT o.issue_date_parsed) FILTER
           (WHERE o.issue_date_parsed <= CURRENT_DATE) AS issues_run,
         SUM(o.gross) FILTER
           (WHERE o.issue_date_parsed <= CURRENT_DATE) AS gross_to_date,
         STRING_AGG(DISTINCT z.abbreviation, ', ' ORDER BY z.abbreviation) AS zones
  FROM orders o
  JOIN zones z ON z.id = o.zone_id
  JOIN markets m ON m.id = o.market_id
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed IS NOT NULL
  GROUP BY o.client_id
)
SELECT
  cl.name AS client,
  COALESCE(cl.category, '—') AS category,
  td.zones,
  CASE WHEN op.sales_rep = 'hm t' THEN 'National Accounts'
       ELSE COALESCE(op.sales_rep, '—') END AS opening_rep,
  TO_CHAR(fim.first_issue, 'YYYY-MM-DD') AS first_issue,
  COALESCE(td.issues_run, 0) AS issues_run,
  COALESCE(td.gross_to_date, 0) AS gross_to_date
FROM first_in_market fim
JOIN clients cl ON cl.id = fim.client_id
LEFT JOIN opening_rep op ON op.client_id = fim.client_id
LEFT JOIN to_date td ON td.client_id = fim.client_id
CROSS JOIN dw_90
WHERE cl.status = 'active'
  AND NOT cl.is_mapping_stub
  AND fim.first_issue >= dw_90.d
  AND fim.first_issue <= CURRENT_DATE
  AND COALESCE(td.issues_run, 0) >= 1  -- must have actually run, not just booked
  AND cl.name NOT ILIKE 'THM %'  -- exclude internal cross-market siblings
ORDER BY fim.first_issue DESC, td.gross_to_date DESC NULLS LAST
"""


SUCCESS_STORY_SQL = """
WITH dw_yr AS (SELECT (CURRENT_DATE - INTERVAL '12 months')::date AS d),
     dw_90 AS (SELECT (CURRENT_DATE - INTERVAL '90 days')::date AS d),
direct_cr AS (
  SELECT DISTINCT cpi.client_id
  FROM client_platform_ids cpi
  WHERE cpi.platform = 'callrail' AND cpi.external_id IS NOT NULL
),
calls_cr AS (
  SELECT DISTINCT c.client_id
  FROM calls c CROSS JOIN dw_yr
  WHERE c.callrail_company_id IS NOT NULL
    AND c.call_time >= dw_yr.d::timestamptz
),
tracked_clients AS (
  SELECT client_id FROM direct_cr
  UNION
  SELECT client_id FROM calls_cr
),
spend_90 AS (
  SELECT o.client_id, SUM(o.gross) AS spend_90d
  FROM orders o
  JOIN markets m ON m.id = o.market_id
  CROSS JOIN dw_90
  WHERE m.code IN ({MK_CODES})
    AND o.issue_date_parsed BETWEEN dw_90.d AND CURRENT_DATE
  GROUP BY o.client_id
),
calls_90 AS (
  SELECT c.client_id, COUNT(*) FILTER (WHERE c.is_qualified) AS qual_calls
  FROM calls c
  CROSS JOIN dw_90
  WHERE c.call_time >= dw_90.d::timestamptz
  GROUP BY c.client_id
)
SELECT
  cl.name AS client,
  COALESCE(cl.category, '—') AS category,
  s.spend_90d,
  COALESCE(c.qual_calls, 0) AS qual_calls_90d,
  COALESCE(c.qual_calls, 0) / (s.spend_90d / 1000.0) AS calls_per_1k
FROM spend_90 s
JOIN clients cl ON cl.id = s.client_id
LEFT JOIN calls_90 c ON c.client_id = s.client_id
WHERE cl.status = 'active'
  AND NOT cl.is_mapping_stub
  AND cl.id IN (SELECT client_id FROM tracked_clients)
  AND cl.category = '{TOP_CAT}'
  AND s.spend_90d >= 2000
  AND COALESCE(c.qual_calls, 0) >= 5
ORDER BY calls_per_1k DESC
LIMIT 1
"""


# ---------- Markdown helpers ---------------------------------------------
def _money(v) -> str:
    if v is None:
        return "—"
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _ratio(v) -> str:
    return "—" if v is None else f"{float(v):.2f}"


def fmt_upgrade_table(rows: list[dict]) -> str:
    if not rows:
        return "_No clients meeting the upgrade criteria this cycle._\n"
    out = ["| Zone | Also Runs In | Rep | Client | 1/2P Orders | 12mo Spend | Avg/HP | Over Median | Qual Calls (90d) | Calls/$1k |",
           "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for r in rows:
        out.append(
            f"| {r['zone']} | {r.get('also_runs') or '—'} | {r['rep'] or '—'} | {r['client']} | "
            f"{r['hp_orders']} | {_money(r['hp_spend_12mo'])} | "
            f"{_money(r['avg_per_hp'])} | +{_money(r['over_median'])} | "
            f"{r['qual_calls_90d']} | {_ratio(r['qual_calls_per_1k'])} |"
        )
    return "\n".join(out) + "\n"


def fmt_underperf_table(rows: list[dict]) -> str:
    if not rows:
        return "_No underperformers above the spend threshold this cycle._\n"
    out = ["| Rank | Brand | Category | Zones | Rep | Products | 90d Spend | Total | Qual | Qual/$1k |",
           "|---:|---|---|---|---|---|---:|---:|---:|---:|"]
    for i, r in enumerate(rows, 1):
        # Annotate brands with multiple sibling client records
        name = r["client"]
        if r.get("member_count", 1) > 1:
            name = f"{name} (+{r['member_count'] - 1} sibling{'s' if r['member_count'] > 2 else ''})"
        out.append(
            f"| {i} | {name} | {r['category']} | {r['zones']} | "
            f"{r['rep'] or '—'} | {r.get('products') or '—'} | "
            f"{_money(r['spend_90d'])} | "
            f"{r['total_calls_90d']} | {r['qual_calls_90d']} | "
            f"{_ratio(r['qual_calls_per_1k'])} |"
        )
    return "\n".join(out) + "\n"


def fmt_new_clients_table(rows: list[dict]) -> str:
    if not rows:
        return "_No new clients started in this market in the last 90 days._\n"
    out = ["| Client | Category | Zones | Opening Rep | First Issue | Issues So Far | Spend to Date |",
           "|---|---|---|---|---|---:|---:|"]
    for r in rows:
        out.append(
            f"| {r['client']} | {r['category']} | {r['zones']} | "
            f"{r['opening_rep']} | {r['first_issue']} | "
            f"{r['issues_run']} | {_money(r['gross_to_date'])} |"
        )
    return "\n".join(out) + "\n"


def fmt_top_cats_table(rows: list[dict]) -> str:
    if not rows:
        return "_Not enough data to compute category leaders this cycle._\n"
    out = ["| Category | # Clients | 90d Spend | 90d Qual Calls | Calls/$1k |",
           "|---|---:|---:|---:|---:|"]
    for r in rows:
        out.append(
            f"| {r['category']} | {r['clients']} | {_money(r['total_spend_90d'])} | "
            f"{r['total_qual_calls_90d']} | {_ratio(r['calls_per_1k'])} |"
        )
    return "\n".join(out) + "\n"


# ---------- Build & write ------------------------------------------------
def build_draft(mk: str) -> Path:
    spec = MARKETS[mk]
    codes_sql = ",".join(f"'{c}'" for c in spec["codes"])
    today = date.today()
    stamp = f"{today.month}-{today.day}-{today.year}"

    print(f"\n=== Sales Cycle Kickoff: {spec['label']} ===")

    # 1. Market Analysis
    ma_path = find_latest_market_analysis(mk)
    if ma_path:
        print(f"  Market Analysis: {ma_path.name}")
    else:
        print(f"  WARNING: no [C] {mk} Market Analysis *.xlsx found in output/")

    # 2. Upgrade candidates
    print("  Querying upgrade candidates...")
    upgrades = query(UPGRADE_SQL.replace("{MK_CODES}", codes_sql))
    print(f"    {len(upgrades)} candidates")

    # 3. Underperformers (post-filter excluded brands, then take top 5)
    print("  Querying top 5 underperformers...")
    underperf_raw = query(UNDERPERF_SQL.replace("{MK_CODES}", codes_sql))
    excluded = []
    underperf = []
    for r in underperf_raw:
        name_lc = (r["client"] or "").lower()
        if any(p in name_lc for p in UNDERPERF_EXCLUDE_PATTERNS):
            excluded.append(r["client"])
            continue
        underperf.append(r)
        if len(underperf) >= 5:
            break
    if excluded:
        print(f"    Excluded (non-call-driven): {', '.join(excluded)}")
    print(f"    {len(underperf)} clients shown")

    # 5. Top categories
    print("  Querying top performing categories...")
    top_cats = query(TOP_CATS_SQL.replace("{MK_CODES}", codes_sql))
    print(f"    {len(top_cats)} categories")

    # 6. New clients in last 90 days
    print("  Querying new clients (last 90 days)...")
    new_clients = query(NEW_CLIENTS_SQL.replace("{MK_CODES}", codes_sql))
    print(f"    {len(new_clients)} new clients")

    # Success story client (best in top category, if any)
    success = None
    if top_cats:
        top_cat = top_cats[0]["category"].replace("'", "''")
        story_sql = (SUCCESS_STORY_SQL
                     .replace("{MK_CODES}", codes_sql)
                     .replace("{TOP_CAT}", top_cat))
        story_rows = query(story_sql)
        success = story_rows[0] if story_rows else None
        if success:
            print(f"    Success story: {success['client']} ({success['category']})")

    # ---- Assemble markdown email draft ----
    md = []
    md.append(f"# Sales Cycle Kickoff — {spec['label']}")
    md.append(f"_Cycle starting {today.strftime('%B %d, %Y')}_\n")
    md.append("To: Mandy")
    md.append(f"Subject: Sales Cycle Kickoff — {spec['label']} ({stamp})\n")
    md.append("Hey Mandy,\n")
    md.append(
        f"Here's your kickoff package for the new {spec['label']} cycle. "
        f"It's everything I'd normally hand off in pieces — now in one place. "
        f"Six sections below; the Market Analysis is attached.\n"
    )

    # 1. Market Analysis
    md.append("## 1. Market Analysis")
    if ma_path:
        md.append(f"**Attached:** `{ma_path.name}`")
        md.append(
            f"\nThis is the latest drop-off + YoY view across the market. "
            f"Tabs are split per rep, with the Summary tab up top for the at-risk dollars by territory. "
            f"The Year to Year tab calls out clients who ran in the comparable window last year but have $0 same-window spend this year.\n"
        )
    else:
        md.append(f"_(No latest [C] {mk} Market Analysis xlsx found in output/. Run that first, then re-generate this draft.)_\n")

    # 2. Upgrade candidates
    md.append("## 2. Full-Page Upgrade Candidates")
    md.append(
        f"Active half-page clients paying **above their zone's median half-page rate** "
        f"who are delivering **fewer than 2.5 qualified calls per $1k spent** in the last 90 days "
        f"(or zero calls). Top 5 sorted worst-to-best by call performance — these are the strongest "
        f"\"easy yes\" pitches if we need to fill pages, since they're already paying premium and "
        f"the size bump is the natural recovery story.\n"
    )
    md.append(fmt_upgrade_table(upgrades))

    # 3. Top 5 underperformers
    md.append("## 3. Top 5 Underperformers to Look At")
    md.append(
        f"Lowest qualified calls per $1k spent across **all sizes** in the last 90 days, "
        f"limited to clients spending $1.5k+ in the window so we're not flagging tiny accounts. "
        f"These are the ones we should triage — design refresh, position change, or hard conversation. "
        f"Total = all calls; Qual = 60+ second calls.\n"
    )
    md.append(fmt_underperf_table(underperf))

    # 4. Seasonality (placeholder)
    md.append("## 4. Seasonality — What to Target This Cycle")
    md.append(
        f"<!-- TODO: Claude will fill via WebSearch — categories trending in {spec['label']} "
        f"for {today.strftime('%B %Y')}. Pull seasonality angle + 2-3 category recommendations. -->\n"
    )
    md.append("_Coming next from Claude after web research._\n")

    # 5. Top performers + success story
    md.append("## 5. Top Performing Categories + Success Story")
    md.append(
        f"Categories in {spec['label']} delivering the best calls/$1k over the last 90 days "
        f"(min 3 clients and $5k spend per category to filter noise):\n"
    )
    md.append(fmt_top_cats_table(top_cats))
    if success:
        md.append(f"\n**Success story to lean on:** **{success['client']}** ({success['category']}) — "
                  f"{_money(success['spend_90d'])} in 90-day spend producing **{success['qual_calls_90d']} qualified calls** "
                  f"({_ratio(success['calls_per_1k'])} calls/$1k). They're proof the format is working when "
                  f"the offer/creative match the market — pull this name when you need to anchor a pitch.\n")
    else:
        md.append("\n_(No success story client met the 90-day spend + call thresholds — propose a category once data fills in.)_\n")

    # 6. New clients (last 90 days)
    md.append(f"## 6. New Clients — Last 90 Days")
    md.append(
        f"Active clients whose first {spec['label']} issue ran in the last 90 days. "
        f"Use this list to onboard them with extra attention, get a first-issue performance read early, "
        f"and make sure rep coverage is dialed in.\n"
    )
    md.append(fmt_new_clients_table(new_clients))

    md.append("---")
    md.append("Let me know if you want anything dug into deeper. — Masen\n")

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DRAFTS_DIR / f"[C] Sales Cycle Kickoff - {mk} {stamp}.md"
    out_path.write_text("\n".join(md), encoding="utf-8")
    print(f"\nWrote: {out_path}")
    print(f"Attach to email: {ma_path}" if ma_path else "(no xlsx attachment found)")
    return out_path


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in MARKETS:
        print("Usage: python -m scripts.sales_cycle_kickoff {CO|TX|UT}")
        sys.exit(1)
    build_draft(sys.argv[1])


if __name__ == "__main__":
    main()
