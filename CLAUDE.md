# THMedia Client Data Hub

## Project Overview
This project centralizes THMedia's client data from multiple platforms (Magazine Manager, CallRail, Uniqode, Inbox Advantage) into a single Supabase (PostgreSQL) database. The database is already created and the schema is already deployed in Supabase.

## Architecture
- **Database**: Supabase (PostgreSQL) — schema is live and tables are created
- **Data ingestion**: Python ETL scripts pull from platform APIs on a schedule
- **Client mapping**: An Excel spreadsheet (Client_Mapping_Name_Cleaning_Updated.xlsx) contains 3,133 mapping records linking client names across 4 platforms. This needs to be imported into Supabase.
- **AI layer**: Claude connects to Supabase via MCP for natural language queries
- **Scheduling**: Windows Task Scheduler runs ETL scripts on a schedule

## Key Concepts
- **Magazine Manager is the source of truth** for client names and billing data
- **OfficialName** in the mapping spreadsheet is the canonical client name
- **Markets vs Zones**: Markets are the 4 operating regions (CO, UT, AU, SA). Zones are the 11 distribution areas within those markets (e.g., SD=South Denver, EPC=El Paso County). Zone assignment is derived from the `product` column in orders.
- **_GUID_THM** is the platform-specific ID in a consistent format:
  - Magazine Manager: `MM-{zone}-{id}` (e.g., MM-CO-7457)
  - CallRail: `COM{company_guid}` (e.g., COM5c9e5d17d96142cc9feb63be6b6c6c2d)
  - Uniqode: `UQ-XX-{campaign_id}` (e.g., UQ-XX-2560593)
  - Inbox Advantage: `IA-{zone}-{name}` (e.g., IA-CO-888 Heating and Air)
- **DB column** in the mapping spreadsheet is the market code: CO=Colorado, UT=Utah, AU=Austin, SA=San Antonio
- **Qualified call** = any call 60+ seconds (auto-calculated by the database)
- Anstel's test line (303-220-4242) should be excluded from analysis

## Client Status (derived from orders, not MM)
`clients.status` is auto-computed from `orders.issue_date_parsed` by `scripts/import_report.sync_client_statuses()` on every weekly refresh. Do NOT trust `clients.priority` (raw MM field, very messy). Use `status` for all active-client queries.
- **active** — has at least one order with issue_date >= today (current or future)
- **cancelled** — most recent order within the past 90 days (just dropped off)
- **expired** — most recent order 90–365 days ago
- **dormant** — most recent order over 365 days ago
- **prospect** — zero orders ever (CallRail-only, mapping stubs, new leads)
- **inactive** — legacy value, no longer set by the pipeline

## Ad Size Vocabulary (standardized across orders, ad_placements, runsheet_entries)
All three tables now use the same 20 canonical size names — no more "Half Page" vs "1/2 Page" confusion.

**Print — standard sizes**
- Full Page, 1/2 Page, 1/2 Page Vertical, 1/4 Page, Double Page

**Print — cover positions**
- Front Cover, Back Cover 2/3 Page, Back Cover Banner

**Marketplace tiers (formerly "Directory Listing")**
- Marketplace Listing (generic), Marketplace Basic, Marketplace Featured, Marketplace Certified, Certified Feature

**Email placements (Inbox Advantage)**
- Sponsored Email, Exclusive Email, Premium Email

**OPP (Opposite Page) placements**
- OPP PopOut, OPP Bookmark, OPP Plus One

**Special**
- Sweepstakes

Two boolean flags on `orders` capture qualifiers:
- `is_cross_book` — TRUE when the raw MM size had "Cross" or "x" prefix (cross-booked from another market)
- `is_deck_package` — TRUE when the raw MM size had "DECK" prefix (bundled deck-up rate package)

```sql
-- All Full Page ads
SELECT * FROM orders WHERE size = 'Full Page';

-- Direct insertions only (exclude cross-books from other markets)
SELECT * FROM orders WHERE size = 'Full Page' AND NOT is_cross_book;

-- Deck-up Full Pages
SELECT * FROM orders WHERE size = 'Full Page' AND is_deck_package;
```

## clients.is_mapping_stub
Boolean flag (default FALSE). TRUE for 1,306 clients that are pure mapping-spreadsheet ghosts — no orders, calls, QR scans, IA campaigns, or platform IDs. Always exclude from analytics:
```sql
WHERE NOT is_mapping_stub  -- leaves 1,660 real/semi-real clients
```
Real prospects (have a CallRail number, inbound calls, or other activity but no orders yet) have `is_mapping_stub=false` and should still appear in prospect queries.

## Markets & Zones
- **Colorado (CO)**: NOCO (Northern Colorado, 80k), ND (North Denver, 100k), SD (South Denver, 120k), EPC (El Paso County, 80k)
- **Utah (UT)**: NW (North Wasatch), CW (Central Wasatch), SW (South Wasatch)
- **Austin (AU)**: AN (Austin North), AS (Austin South)
- **San Antonio (SA)**: SAE (San Antonio East), SAW (San Antonio West)

## Supabase Tables
markets, zones, sales_reps, clients, client_platform_ids, client_zones, client_phone_numbers, categories, client_categories, category_aliases, classification_log, client_reclassification_queue, magazine_issues, ad_placements, orders, calls, call_tags, qr_scans, form_submissions, client_notes

## Category Taxonomy (use junction, NOT clients.category)
- **Flat 2-tier hierarchy:** 27 top-level categories + ~85 subcategories. NO groups layer. See `docs/category_taxonomy.md` for the full tree.
- **Source of truth:** `client_categories` junction table. `source IN ('manual','mm_api','llm_auto','legacy_text')` — Manual > MM API > LLM > Legacy precedence.
- **Default filter for reports:** `WHERE cc.is_primary = true` to get specialists only. Use `v_clients_with_categories` view for multi-tag rollup when you actually want it.
- **Backward-compat shim:** `clients.category` text column still populated as the primary tag for legacy code paths, but DO NOT query for analytics — was 10-20% wrong (e.g. RW was tagged Windows but actually does window cleaning).
- **Key distinctions:** Window install (slug `windows`) ≠ Window cleaning (slug `window-cleaning` under Cleaning Services). Garage Doors are under Garages, not Doors. Concrete/Pavers/Driveways is its own top-level. HVAC, Plumbing, Water Heaters, Water Treatment all roll up to "HVAC & Plumbing" top-level. Window Wells are a subcategory under Windows. Foundation Repair is its own top-level.
- **Handyman/GC clients** are deliberately tagged ONLY in Handyman Services or Construction & Design — NOT in every specialty their ad mentions. Prevents pollution.
- Bulk classification: `scripts/auto_classify_clients.py`. Review: `scripts/build_category_review.py` → `setup/import_category_approvals.py`.

## Call Tracking (use these — do NOT derive from CallRail account presence)
- `clients.has_call_tracking` — boolean rollup. TRUE if ANY zone is tracked. NULL = not in source file (unknown).
- `client_zones.has_call_tracking` — per-zone flag. NULL = unknown.
- `clients.call_tracking_notes` — raw audit text from MM, do not query directly.
- `client_phone_numbers` — secondary table parsed from notes. Holds tracking #, destination #, in-ad # with placement (Bookmark/PopOut/IA/etc.) and business line (Sales/Service/Roofing/HVAC). **Enrichment only — never overrides zone or platform mappings.** Filter `AND NOT is_historical` for current state.
- See `docs/call_tracking_data_model.md` for full query patterns + the CallRail hygiene audit.

## Scheduled Tasks (Windows Task Scheduler)
Staggered to avoid contention. The watchdog at 11 AM emails an alert if anything failed.

| Time | Task | Frequency | Script |
|---|---|---|---|
| 08:00 | THM Data Hub - Monthly CallRail Audit | 1st of month | `scripts/monthly_callrail_audit.py` |
| 08:30 | THM Data Hub - Daily CallRail ETL | Daily | `etl/etl_callrail.py` |
| 09:00 | CallRail Daily AutoTag | Daily | `Callrail Tagging/daily_autotag.bat` (separate folder) |
| 10:00 | THM Data Hub - Weekly Category Maintenance | Mondays | `scripts/maintain_categories.py` |
| 11:00 | **THM Data Hub - Daily Task Watchdog** | Daily | `scripts/task_watchdog.py` — emails alert if any task in last 36h failed |

Adding a new scheduled task: add it to the table above, pick a time slot that doesn't collide, and confirm the watchdog will pick up its name (matches `THM|CallRail` substring in `WATCHED_PATTERNS`).

## Key Views
- client_performance_snapshot: key metrics for active clients (joins to markets)
- monthly_call_summary: call counts + spend by client by month (uses orders for spend)
- zone_performance: aggregated metrics by real zone (clients, calls, revenue, distribution)
- missed_calls_alert: missed calls from last 24h with rep info

## Credentials
All API keys and credentials are stored in .env (never commit this). Required variables:
- SUPABASE_URL
- SUPABASE_KEY
- CALLRAIL_API_KEY
- CALLRAIL_ACCOUNT_ID

## Project Structure
```
thm-data-hub/
  .env                        # API keys (gitignored)
  .gitignore
  CLAUDE.md                   # This file
  config.py                   # Supabase connection
  helpers.py                  # Shared client lookup functions
  schema/
    thm_client_hub_schema_v2.sql
  setup/
    import_from_mapping.py    # Reads mapping spreadsheet -> Supabase
  etl/
    etl_callrail.py
    etl_uniqode.py
  scripts/
    run_etl.bat
  logs/
  data/                       # Spreadsheets and CSVs (gitignored)
```

## Current Status
- Supabase project live with markets/zones schema (4 markets, 11 zones)
- 2,966 clients, 41,067 orders, 73,580 calls, 8,368 QR scans imported
- Client status auto-synced from orders: 437 active, 54 cancelled, 289 expired, 361 dormant, 1,825 prospect
- 1,306 of those prospects are flagged `is_mapping_stub=TRUE` (exclude from analytics)
- 22 case-duplicate clients merged (Apex Clean Air, Handyman Hub, Brothers That Just Do Gutters, McIntire Roofing, Utah Led, etc.)
- All analytic views rebuilt on `calls_enriched` with `is_test_call` flag; test calls count toward volume but excluded from qualified/missed
- client_zones rebuilt from order data
- CallRail ETL operational (Mondays 7am via Task Scheduler), Uniqode/IA/Ads imported via weekly refresh
- Some clients have NULL primary_market_id (Cross-Market/Uniqode entries)

## Important Notes
- Rate card pricing is sensitive and must never appear in outputs
- CallRail API docs: https://apidocs.callrail.com/
- The import script (import_from_mapping.py) is idempotent — safe to run multiple times
- ETL scripts use upsert (on_conflict) to prevent duplicate records
