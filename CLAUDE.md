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
- **_GUID_THM** is the platform-specific ID in a consistent format:
  - Magazine Manager: `MM-{zone}-{id}` (e.g., MM-CO-7457)
  - CallRail: `COM{company_guid}` (e.g., COM5c9e5d17d96142cc9feb63be6b6c6c2d)
  - Uniqode: `UQ-XX-{campaign_id}` (e.g., UQ-XX-2560593)
  - Inbox Advantage: `IA-{zone}-{name}` (e.g., IA-CO-888 Heating and Air)
- **DB column** in the spreadsheet is the zone code: CO=Colorado, UT=Utah, AU=Austin, SA=San Antonio, XX=Cross-Market
- **Qualified call** = any call 60+ seconds (auto-calculated by the database)
- Anstel's test line (303-220-4242) should be excluded from analysis

## Supabase Tables (already created)
zones, sales_reps, clients, client_platform_ids, client_zones, magazine_issues, ad_placements, calls, call_tags, qr_scans, form_submissions, client_notes

## Key Views (already created)
- client_performance_snapshot: all key metrics for active clients
- monthly_call_summary: call counts + spend by client by month (for YOY)
- zone_performance: aggregated metrics by zone
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
- Supabase project created and schema deployed
- Mapping spreadsheet exists with 3,133 records (1,750 unique clients)
- 463 rows in spreadsheet still missing OfficialName (can be handled later)
- Need to: set up Python environment, run import script, then build ETL scripts

## Important Notes
- Rate card pricing is sensitive and must never appear in outputs
- CallRail API docs: https://apidocs.callrail.com/
- The import script (import_from_mapping.py) is idempotent — safe to run multiple times
- ETL scripts use upsert (on_conflict) to prevent duplicate records
