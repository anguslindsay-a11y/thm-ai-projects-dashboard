"""CallRail account hygiene audit.

Bucketizes every CallRail account linked in client_platform_ids and writes
an Excel with one tab per priority bucket so the team can act on broken or
stale tracking.

Buckets (priority order):
  1. ACTIVE_no_calls_90d      — broken tracking, urgent
  2. INACTIVE_still_calls     — leakage, retire CR account or restore client
  3. ct_NO_but_has_callrail   — possible stale CR account
  4. inactive_retire_account  — fully cold CR accounts to retire
  5. mismatched_label         — CallRail label noticeably different from client name
  6. healthy                  — for reference/sanity check only

Usage:
  python scripts/callrail_hygiene_audit.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.analyze import query, to_xlsx


AUDIT_SQL = """
WITH cr AS (
  SELECT cpi.client_id,
         cpi.external_id    AS callrail_company_id,
         cpi.external_name  AS callrail_label,
         c.name             AS client_name,
         c.status,
         c.has_call_tracking,
         c.is_mapping_stub,
         m.code             AS market
  FROM client_platform_ids cpi
  JOIN clients c   ON c.id = cpi.client_id
  LEFT JOIN markets m ON m.id = c.primary_market_id
  WHERE cpi.platform = 'callrail'
),
recent_calls AS (
  SELECT callrail_company_id, COUNT(*) AS calls_90d, MAX(call_time) AS last_call
  FROM calls WHERE call_time >= NOW() - INTERVAL '90 days'
  GROUP BY callrail_company_id
),
all_calls AS (
  SELECT callrail_company_id,
         COUNT(*) AS calls_total,
         MAX(call_time) AS last_call_ever
  FROM calls
  GROUP BY callrail_company_id
),
recent_orders AS (
  SELECT client_id, MAX(issue_date_parsed) AS last_order
  FROM orders
  GROUP BY client_id
)
SELECT
  cr.client_name,
  cr.market,
  cr.status,
  cr.has_call_tracking,
  cr.callrail_label,
  cr.callrail_company_id,
  COALESCE(rc.calls_90d, 0)              AS calls_90d,
  COALESCE(ac.calls_total, 0)            AS calls_total,
  ac.last_call_ever,
  ro.last_order,
  -- Lowercased token similarity (rough): flag if no overlap > 3 chars
  cr.client_id
FROM cr
LEFT JOIN recent_calls rc ON rc.callrail_company_id = cr.callrail_company_id
LEFT JOIN all_calls    ac ON ac.callrail_company_id = cr.callrail_company_id
LEFT JOIN recent_orders ro ON ro.client_id = cr.client_id
WHERE NOT cr.is_mapping_stub
ORDER BY cr.client_name;
"""


def name_tokens(s: str) -> set[str]:
    if not s:
        return set()
    cleaned = "".join(ch.lower() if ch.isalnum() or ch.isspace() else " " for ch in s)
    return {t for t in cleaned.split() if len(t) >= 3 and t not in {
        "the", "and", "for", "llc", "inc", "ltd", "corp", "company", "inc.",
        "thm", "co", "ut", "tx", "us", "usa",
        # Zone words shouldn't count as a "match" between names
        "north", "south", "east", "west", "metro", "noco", "epc", "central",
        "denver", "wasatch", "austin", "antonio", "san", "salt", "lake",
        "colorado", "utah", "texas",
    }}


def classify(row: dict) -> str:
    has_ct = row.get("has_call_tracking")
    status = row.get("status")
    calls_90d = row.get("calls_90d") or 0

    # Mismatch flag is layered on top of other buckets — but we surface it
    # as its own top-level bucket when the names truly diverge.
    cr_tokens = name_tokens(row.get("callrail_label") or "")
    cn_tokens = name_tokens(row.get("client_name") or "")
    overlap = cr_tokens & cn_tokens
    is_mismatch = bool(cr_tokens) and bool(cn_tokens) and not overlap

    if has_ct is False:
        return "ct_NO_but_has_callrail"
    if status == "active" and calls_90d == 0:
        return "ACTIVE_no_calls_90d"
    if status in ("cancelled", "expired", "dormant") and calls_90d > 0:
        return "INACTIVE_still_calls"
    if status in ("cancelled", "expired", "dormant") and calls_90d == 0:
        return "inactive_retire_account"
    if is_mismatch:
        return "mismatched_label"
    return "healthy"


def main():
    print("Querying CallRail audit data...")
    rows = query(AUDIT_SQL)
    print(f"  {len(rows)} CallRail accounts under non-stub clients")

    # Classify and split
    buckets: dict[str, list[dict]] = {
        "Summary": [],
        "1. ACTIVE_no_calls_90d": [],
        "2. INACTIVE_still_calls": [],
        "3. ct_NO_but_has_callrail": [],
        "4. inactive_retire_account": [],
        "5. mismatched_label": [],
        "6. healthy (reference)": [],
    }
    bucket_to_tab = {
        "ACTIVE_no_calls_90d":      "1. ACTIVE_no_calls_90d",
        "INACTIVE_still_calls":     "2. INACTIVE_still_calls",
        "ct_NO_but_has_callrail":   "3. ct_NO_but_has_callrail",
        "inactive_retire_account":  "4. inactive_retire_account",
        "mismatched_label":         "5. mismatched_label",
        "healthy":                  "6. healthy (reference)",
    }

    def _strip_tz(dt):
        if dt and hasattr(dt, "tzinfo") and dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt

    for r in rows:
        bucket = classify(r)
        r_out = {
            "client_name": r["client_name"],
            "market": r["market"],
            "status": r["status"],
            "has_call_tracking": r["has_call_tracking"],
            "callrail_label": r["callrail_label"],
            "callrail_company_id": r["callrail_company_id"],
            "calls_90d": r["calls_90d"],
            "calls_total": r["calls_total"],
            "last_call_ever": _strip_tz(r["last_call_ever"]),
            "last_order": _strip_tz(r["last_order"]),
        }
        # Also flag mismatched names within their primary bucket
        cr_tokens = name_tokens(r.get("callrail_label") or "")
        cn_tokens = name_tokens(r.get("client_name") or "")
        if cr_tokens and cn_tokens and not (cr_tokens & cn_tokens):
            r_out["name_mismatch"] = "Y"
        else:
            r_out["name_mismatch"] = ""
        buckets[bucket_to_tab[bucket]].append(r_out)

    # Build Summary
    summary = []
    summary.append({"bucket": "Total CallRail accounts (non-stub clients)", "count": len(rows), "action": ""})
    summary.append({"bucket": "", "count": "", "action": ""})
    summary.append({
        "bucket": "1. ACTIVE_no_calls_90d",
        "count": len(buckets["1. ACTIVE_no_calls_90d"]),
        "action": "URGENT — investigate broken tracking. Active clients should be getting calls.",
    })
    summary.append({
        "bucket": "2. INACTIVE_still_calls",
        "count": len(buckets["2. INACTIVE_still_calls"]),
        "action": "LEAKAGE — either retire the CallRail account or restore client status if they're back.",
    })
    summary.append({
        "bucket": "3. ct_NO_but_has_callrail",
        "count": len(buckets["3. ct_NO_but_has_callrail"]),
        "action": "Stale — client marked NOT on CT but a CR account is still mapped. Likely retire CR-side.",
    })
    summary.append({
        "bucket": "4. inactive_retire_account",
        "count": len(buckets["4. inactive_retire_account"]),
        "action": "Cold — CR account on inactive client with no recent calls. Safe to retire.",
    })
    summary.append({
        "bucket": "5. mismatched_label",
        "count": len(buckets["5. mismatched_label"]),
        "action": "CR label and client name share no overlap — likely wrong account mapped.",
    })
    summary.append({
        "bucket": "6. healthy (reference)",
        "count": len(buckets["6. healthy (reference)"]),
        "action": "No action needed.",
    })
    buckets["Summary"] = summary

    print("\nBucket counts:")
    for k, v in buckets.items():
        print(f"  {k}: {len(v)}")

    out_path = to_xlsx(
        "CallRail Hygiene Audit",
        sheets=buckets,
    )
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
