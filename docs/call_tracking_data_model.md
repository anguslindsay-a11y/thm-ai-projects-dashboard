# Call Tracking — Data Model Reference

> **For:** Streamlit app, future chats, anyone querying call-tracking data.
> **TL;DR:** Use `clients.has_call_tracking` and `client_zones.has_call_tracking`
> as the source of truth. The notes-derived `client_phone_numbers` table is
> additive enrichment — it never overrides zone or platform mappings.

---

## Source-of-truth fields (use these for filtering)

| Field | Type | Meaning |
|---|---|---|
| `clients.has_call_tracking` | `boolean` | TRUE if the client is on call tracking in **any** zone. NULL = unknown (client not in the call-tracking source file). |
| `client_zones.has_call_tracking` | `boolean` | Per-zone tracking flag. NULL = unknown. |
| `clients.call_tracking_notes` | `text` | Raw "Call Track Notes" text from MagManager — preserved for audit only, do not query directly. |

### Canonical queries

```sql
-- All active clients on call tracking
SELECT * FROM clients
WHERE status = 'active'
  AND has_call_tracking = true
  AND NOT is_mapping_stub;

-- Active clients NOT on call tracking (untracked spend — calls won't appear in CallRail)
SELECT * FROM clients
WHERE status = 'active'
  AND has_call_tracking = false
  AND NOT is_mapping_stub;

-- Per-zone tracking heatmap
SELECT z.abbreviation,
       COUNT(*) FILTER (WHERE cz.has_call_tracking)        AS tracked,
       COUNT(*) FILTER (WHERE NOT cz.has_call_tracking)    AS not_tracked,
       COUNT(*) FILTER (WHERE cz.has_call_tracking IS NULL) AS unknown
FROM client_zones cz
JOIN zones z ON z.id = cz.zone_id
JOIN clients c ON c.id = cz.client_id
WHERE NOT c.is_mapping_stub
GROUP BY z.abbreviation
ORDER BY z.abbreviation;
```

---

## Enrichment table — `client_phone_numbers`

Parsed automatically from `clients.call_tracking_notes`. **Secondary** —
join when you want phone-level / placement / business-line context.

| Column | Type | Notes |
|---|---|---|
| `client_id` | uuid | FK to clients |
| `phone_number` | text | digits-only 10-digit (e.g. `7195237716`) |
| `phone_display` | text | original formatted (e.g. `719-523-7716`) |
| `role` | text | `tracking` (CT #), `destination` (real office #), `in_ad` (published), `unknown` |
| `zone_id` | uuid | FK to zones (nullable) |
| `zone_label_raw` | text | raw label from notes (`North`, `N/S`, `EPC`, ...) |
| `placement` | text | `Bookmark`, `PopOut`, `OPP`, `IA`, `In Book`, `Sweepstakes`, `Cross-Book`, `Cross-Market`, `Double PopOut` |
| `business_line` | text | `Sales`, `Service`, `Roofing`, `HVAC`, `IAQ`, etc. |
| `is_historical` | boolean | TRUE for cancelled/retired/old numbers |
| `source` | text | always `ct_notes` for now |
| `notes_excerpt` | text | the raw line we parsed |

### Use cases & queries

#### 1. Reverse phone lookup (which client owns this number?)

```sql
SELECT c.name, c.status, cpn.role, cpn.placement, cpn.business_line, cpn.is_historical
FROM client_phone_numbers cpn
JOIN clients c ON c.id = cpn.client_id
WHERE cpn.phone_number = '7195237716';
```

#### 2. Placement-level call attribution

Join `calls.tracking_number` to `client_phone_numbers.phone_number` where
`role = 'tracking'` to learn which placement (Bookmark, PopOut, IA) drove
each call.

```sql
SELECT cpn.placement, COUNT(*) AS call_count
FROM calls ca
JOIN client_phone_numbers cpn
  ON cpn.phone_number = regexp_replace(ca.tracking_number, '\D', '', 'g')
 AND cpn.role = 'tracking'
 AND NOT cpn.is_historical
WHERE ca.client_id = '<uuid>'
GROUP BY cpn.placement;
```

#### 3. Untracked-spend report (CT = NO + active orders)

```sql
SELECT c.name, m.code AS market, SUM(o.gross) AS gross_90d
FROM clients c
JOIN orders o ON o.client_id = c.id
LEFT JOIN markets m ON m.id = c.primary_market_id
WHERE c.status = 'active'
  AND c.has_call_tracking = false
  AND o.issue_date_parsed >= NOW() - INTERVAL '90 days'
GROUP BY c.name, m.code
ORDER BY gross_90d DESC;
```

#### 4. Broken-tracking report (CT = YES but no recent calls)

```sql
SELECT c.name, m.code AS market, MAX(ca.call_time) AS last_call
FROM clients c
LEFT JOIN markets m ON m.id = c.primary_market_id
LEFT JOIN calls ca ON ca.client_id = c.id AND ca.call_time >= NOW() - INTERVAL '90 days'
WHERE c.status = 'active'
  AND c.has_call_tracking = true
GROUP BY c.id, c.name, m.code
HAVING COUNT(ca.id) = 0
ORDER BY c.name;
```

#### 5. Multi-product business call splits

```sql
-- Calls broken out by business line (Sales/Service/Roofing/HVAC/etc.)
SELECT cpn.business_line, COUNT(DISTINCT ca.id) AS calls
FROM calls ca
JOIN client_phone_numbers cpn
  ON cpn.phone_number = regexp_replace(ca.tracking_number, '\D', '', 'g')
 AND cpn.role = 'tracking'
WHERE ca.client_id = '<uuid>'
  AND cpn.business_line IS NOT NULL
GROUP BY cpn.business_line;
```

---

## CallRail account hygiene buckets

Run this to find broken/stale CallRail mappings:

```sql
WITH recent_calls AS (
  SELECT callrail_company_id, COUNT(*) AS calls_90d, MAX(call_time) AS last_call
  FROM calls WHERE call_time >= NOW() - INTERVAL '90 days'
  GROUP BY callrail_company_id
)
SELECT
  CASE
    WHEN c.has_call_tracking = false THEN 'ct_NO_but_has_callrail'
    WHEN c.status = 'active' AND COALESCE(rc.calls_90d, 0) = 0 THEN 'ACTIVE_no_calls_90d'
    WHEN c.status IN ('cancelled','expired','dormant') AND COALESCE(rc.calls_90d, 0) > 0 THEN 'INACTIVE_still_calls'
    WHEN c.status IN ('cancelled','expired','dormant') AND COALESCE(rc.calls_90d, 0) = 0 THEN 'inactive_retire_account'
    ELSE 'healthy'
  END AS bucket,
  c.name, cpi.external_id, cpi.external_name, c.status, COALESCE(rc.calls_90d, 0) AS calls_90d
FROM client_platform_ids cpi
JOIN clients c ON c.id = cpi.client_id
LEFT JOIN recent_calls rc ON rc.callrail_company_id = cpi.external_id
WHERE cpi.platform = 'callrail'
ORDER BY bucket, c.name;
```

Buckets in priority order:
1. **`ACTIVE_no_calls_90d`** — broken tracking, urgent. Active client, has a CallRail account mapped, but zero calls in 90 days. Likely a forwarding misconfiguration.
2. **`INACTIVE_still_calls`** — leakage. Cancelled/expired/dormant client still sending calls. Either retire the account in CallRail or restore the client's status if they're actually back.
3. **`ct_NO_but_has_callrail`** — possible stale CallRail account. Client is marked NOT on call tracking but a CR account is still linked. Candidate for CallRail-side retirement.
4. **`inactive_retire_account`** — fully cold. CallRail account on an inactive client with no recent calls. Safe to retire.

---

## Refreshing the data

```bash
# Re-run after a new MagManager call-tracking export lands in data/THM Call Tracking.xlsx
python setup/import_call_tracking.py

# Re-parse notes into client_phone_numbers (use --reset to clobber prior parse)
python setup/parse_call_tracking_notes.py --reset
```

### CallRail-evidence guard

The importer runs a final guard step that **trusts CallRail data over the source file** when they conflict. If a client appears in the file as NCT/in-ad but has a CallRail account producing real calls in the last 365 days, the guard forces `has_call_tracking = true` at both the client rollup and the TX zone level.

This protects against MagManager's call-tracking field being incomplete (especially for TX, which has no structured CT column in MM). When the MagManager API replaces the spreadsheet flow, this guard becomes a safety net rather than a primary fix.

---

## Important caveats

- **Notes are messy.** ~12% of rows are bare phone numbers with no zone/role
  context — they land as `role = 'unknown'`. Don't read those as authoritative.
- **`is_historical = true`** rows are PRESERVED, not deleted, because they
  inform "when did the client switch CT" timeline analysis. Filter them out
  for current-state queries: `AND NOT is_historical`.
- **The notes parser does not write back to `client_zones` or
  `client_platform_ids`.** Those remain authoritative for zone and
  CallRail-account membership respectively.
