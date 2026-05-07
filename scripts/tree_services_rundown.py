"""Tree Services category performance rundown across all markets.

Pulls:
  - Orders (spend, avg per issue, zones, ad sizes)
  - Calls (total, qualified, missed, first-time)
  - QR scans
  - Email campaigns (views, clicks, audience)

Scope: clients where category or subcategory mentions "Tree Service" / "Tree"
       and status in (active, cancelled, expired). Excludes mapping stubs.
"""
from scripts.analyze import query, to_xlsx

TREE_FILTER = """
  NOT c.is_mapping_stub
  AND (c.category ILIKE '%tree service%' OR c.subcategory ILIKE '%tree%')
  AND c.status IN ('active','cancelled','expired')
"""

ORDERS_SQL = f"""
WITH tree_clients AS (
  SELECT c.id, c.name, c.status, m.code as market
  FROM clients c
  LEFT JOIN markets m ON c.primary_market_id = m.id
  WHERE {TREE_FILTER}
)
SELECT
  tc.name,
  tc.status,
  tc.market,
  COUNT(DISTINCT o.id) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months') as orders_12mo,
  COALESCE(ROUND(SUM(o.net) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months'), 0), 0) as spend_12mo,
  COALESCE(ROUND(AVG(o.net) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months'), 0), 0) as avg_spend_per_issue,
  MIN(o.issue_date_parsed) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months') as first_issue,
  MAX(o.issue_date_parsed) as last_issue,
  STRING_AGG(DISTINCT z.abbreviation, ', ' ORDER BY z.abbreviation) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months') as zones,
  STRING_AGG(DISTINCT o.size, ', ' ORDER BY o.size) FILTER (WHERE o.issue_date_parsed >= CURRENT_DATE - INTERVAL '12 months') as ad_sizes
FROM tree_clients tc
LEFT JOIN orders o ON o.client_id = tc.id
LEFT JOIN zones z ON o.zone_id = z.id
GROUP BY tc.name, tc.status, tc.market
ORDER BY tc.status, spend_12mo DESC NULLS LAST
"""

CALLS_SQL = f"""
WITH tree_clients AS (
  SELECT c.id, c.name FROM clients c WHERE {TREE_FILTER}
)
SELECT
  tc.name,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '12 months' AND ca.caller_number <> '+13032204242') as total_calls,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '12 months' AND ca.is_qualified AND ca.caller_number <> '+13032204242') as qualified_calls,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '12 months' AND ca.is_missed AND ca.caller_number <> '+13032204242') as missed_calls,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '12 months' AND ca.is_first_time AND ca.caller_number <> '+13032204242') as first_time_callers,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '3 months' AND ca.caller_number <> '+13032204242') as calls_90d,
  COUNT(ca.id) FILTER (WHERE ca.call_time >= CURRENT_DATE - INTERVAL '3 months' AND ca.is_qualified AND ca.caller_number <> '+13032204242') as qualified_90d
FROM tree_clients tc
LEFT JOIN calls ca ON ca.client_id = tc.id
GROUP BY tc.name
"""

ENGAGEMENT_SQL = f"""
WITH tree_clients AS (
  SELECT c.id, c.name FROM clients c WHERE {TREE_FILTER}
),
qr AS (
  SELECT tc.id, tc.name,
    COUNT(q.id) FILTER (WHERE q.scan_time >= CURRENT_DATE - INTERVAL '12 months') as qr_scans_12mo,
    COUNT(q.id) FILTER (WHERE q.scan_time >= CURRENT_DATE - INTERVAL '3 months') as qr_scans_90d
  FROM tree_clients tc
  LEFT JOIN qr_scans q ON q.client_id = tc.id
  GROUP BY tc.id, tc.name
),
em AS (
  SELECT ecc.client_id,
    COUNT(DISTINCT ec.id) FILTER (WHERE ec.drop_date >= CURRENT_DATE - INTERVAL '12 months') as email_campaigns_12mo,
    COALESCE(SUM(ec.d30_views) FILTER (WHERE ec.drop_date >= CURRENT_DATE - INTERVAL '12 months'), 0) as email_views,
    COALESCE(SUM(ec.d30_clicks) FILTER (WHERE ec.drop_date >= CURRENT_DATE - INTERVAL '12 months'), 0) as email_clicks,
    COALESCE(SUM(ec.audience_size) FILTER (WHERE ec.drop_date >= CURRENT_DATE - INTERVAL '12 months'), 0) as audience_total
  FROM email_campaign_clients ecc
  JOIN email_campaigns ec ON ecc.campaign_id = ec.id
  GROUP BY ecc.client_id
)
SELECT qr.name,
  COALESCE(qr.qr_scans_12mo, 0) as qr_scans_12mo,
  COALESCE(qr.qr_scans_90d, 0) as qr_scans_90d,
  COALESCE(em.email_campaigns_12mo, 0) as email_campaigns_12mo,
  COALESCE(em.email_views, 0) as email_views_30d,
  COALESCE(em.email_clicks, 0) as email_clicks_30d,
  COALESCE(em.audience_total, 0) as audience_total,
  CASE WHEN COALESCE(em.email_views, 0) > 0
       THEN ROUND(100.0 * em.email_clicks / em.email_views, 2)
       ELSE 0 END as email_ctv_pct
FROM qr
LEFT JOIN em ON qr.id = em.client_id
"""


def merge(orders, calls, engage):
    calls_by = {r["name"]: r for r in calls}
    engage_by = {r["name"]: r for r in engage}
    merged = []
    for o in orders:
        row = {
            "Client": o["name"],
            "Status": o["status"],
            "Market": o["market"],
            "Zones": o["zones"] or "",
            "Ad Sizes (12mo)": o["ad_sizes"] or "",
            "Orders 12mo": o["orders_12mo"] or 0,
            "Spend 12mo": float(o["spend_12mo"] or 0),
            "Avg $/Issue": float(o["avg_spend_per_issue"] or 0),
            "First Issue (12mo)": o["first_issue"],
            "Last Issue": o["last_issue"],
        }
        c = calls_by.get(o["name"], {})
        row["Calls 12mo"] = c.get("total_calls", 0)
        row["Qualified 12mo"] = c.get("qualified_calls", 0)
        row["Missed 12mo"] = c.get("missed_calls", 0)
        row["First-Time Callers"] = c.get("first_time_callers", 0)
        row["Calls 90d"] = c.get("calls_90d", 0)
        row["Qualified 90d"] = c.get("qualified_90d", 0)
        total = c.get("total_calls", 0) or 0
        qual = c.get("qualified_calls", 0) or 0
        row["Qual Rate %"] = round(100 * qual / total, 1) if total else 0
        e = engage_by.get(o["name"], {})
        row["QR Scans 12mo"] = e.get("qr_scans_12mo", 0)
        row["QR Scans 90d"] = e.get("qr_scans_90d", 0)
        row["Email Campaigns 12mo"] = e.get("email_campaigns_12mo", 0)
        row["Email Views"] = e.get("email_views_30d", 0)
        row["Email Clicks"] = e.get("email_clicks_30d", 0)
        row["Email Audience"] = e.get("audience_total", 0)
        row["Email CTV %"] = e.get("email_ctv_pct", 0)
        merged.append(row)
    return merged


def market_summary(rows):
    """Summarize by market + status."""
    agg = {}
    for r in rows:
        key = (r["Market"], r["Status"])
        a = agg.setdefault(key, {
            "Market": r["Market"], "Status": r["Status"],
            "Clients": 0, "Total Spend 12mo": 0.0,
            "Total Calls 12mo": 0, "Qualified 12mo": 0,
            "QR Scans 12mo": 0, "Email Clicks 12mo": 0,
        })
        a["Clients"] += 1
        a["Total Spend 12mo"] += r["Spend 12mo"]
        a["Total Calls 12mo"] += r["Calls 12mo"]
        a["Qualified 12mo"] += r["Qualified 12mo"]
        a["QR Scans 12mo"] += r["QR Scans 12mo"]
        a["Email Clicks 12mo"] += r["Email Clicks"]
    out = list(agg.values())
    out.sort(key=lambda x: (x["Status"], -x["Total Spend 12mo"]))
    for r in out:
        r["Total Spend 12mo"] = round(r["Total Spend 12mo"], 0)
    return out


def top_bottom(rows):
    active = [r for r in rows if r["Status"] == "active"]
    top = sorted(active, key=lambda x: -x["Spend 12mo"])[:5]
    # Underperformers: active clients with low call volume relative to spend
    def score(r):
        spend = r["Spend 12mo"] or 0
        calls = r["Qualified 12mo"] or 0
        if spend == 0:
            return 0
        return calls / (spend / 1000)  # qualified calls per $1k spend
    under = sorted([r for r in active if r["Spend 12mo"] > 5000], key=score)[:5]
    return top, under


def main():
    print("Querying orders...")
    orders = query(ORDERS_SQL)
    print(f"  {len(orders)} clients")
    print("Querying calls...")
    calls = query(CALLS_SQL)
    print("Querying QR + email engagement...")
    engage = query(ENGAGEMENT_SQL)

    merged = merge(orders, calls, engage)
    mkt_summary = market_summary(merged)
    top, under = top_bottom(merged)

    sheets = {
        "Summary by Market": mkt_summary,
        "Top Performers (Active)": top,
        "Underperformers (Active)": under,
        "Full Rundown": merged,
    }
    path = to_xlsx("Tree Services Category Rundown", sheets=sheets,
                   money_cols={"Spend 12mo", "Avg $/Issue", "Total Spend 12mo"})
    print(f"Wrote: {path}")


if __name__ == "__main__":
    main()
