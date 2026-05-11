-- 012_magmanager_api.sql
-- MagManager (Mirabel) API integration — schema additions for the new ETL.
--
-- This migration scaffolds storage for the THREE endpoints currently accessible
-- on our API key: api_ContactsGetTHM, api_OpportunityGetTHM,
-- api_ContactActivityGetTHM.
--
-- NOT included yet (waiting on Mirabel to grant API access):
--   - Orders endpoint (api_OrdersGetPowerBI / api_OrdersGetTHM)
--   - Products endpoint (api_ProductsGetPowerBI / api_ProductsGetTHM)
--   - Pub Schedule endpoint (api_PubScheduleGetPowerBI / api_PubScheduleGetTHM)
-- Tables for those will be added in 013 once endpoints are live.
--
-- The api_ProposalsGetTHM endpoint IS accessible but flagged as unreliable
-- for order data; not ingesting until cross-validated against the real
-- Orders endpoint. No `proposals` table is created here.

-- ----------------------------------------------------------------------
-- 1) clients: add MagManager identity + custom-field columns
-- ----------------------------------------------------------------------
-- Existing columns we will REUSE (already on clients):
--   priority        ← MM "Priority" (extracted from JSON array)
--   sales_attrib    ← MM "SalesAttrib"
--   mm_start_issue  ← MM "StartIssue" (parsed "11/2012" → 2012-11-01)

ALTER TABLE clients
  -- Identity (cross-tenant unique)
  ADD COLUMN IF NOT EXISTS mm_global_id           TEXT,
  ADD COLUMN IF NOT EXISTS mm_database            TEXT,
  ADD COLUMN IF NOT EXISTS mm_customer_id         INTEGER,

  -- Raw priority JSON (for safety — extracted value lives in clients.priority)
  ADD COLUMN IF NOT EXISTS mm_priority_raw        JSONB,

  -- Rep attribution (companion to existing sales_attrib)
  ADD COLUMN IF NOT EXISTS mm_inside_sales_attrib TEXT,

  -- Contact groupings (e.g. ['Autopay'])
  ADD COLUMN IF NOT EXISTS mm_contact_groups      TEXT[],

  -- Distribution intent ("Active North Denver~Active South Denver~...")
  ADD COLUMN IF NOT EXISTS mm_mail_copies         TEXT,

  -- Lifecycle metadata
  ADD COLUMN IF NOT EXISTS mm_last_cancel_reason  TEXT,
  ADD COLUMN IF NOT EXISTS mm_billing_notes       TEXT,
  ADD COLUMN IF NOT EXISTS mm_spotted             TEXT,

  -- Order summary (NOT line items — those come from Orders endpoint later)
  ADD COLUMN IF NOT EXISTS mm_first_order_date    DATE,
  ADD COLUMN IF NOT EXISTS mm_last_order_date     DATE,

  -- API row timestamps (used for incremental sync detection)
  ADD COLUMN IF NOT EXISTS mm_date_added          TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS mm_date_modified       TIMESTAMPTZ,

  -- Misc
  ADD COLUMN IF NOT EXISTS mm_url                 TEXT,

  -- Cohort flag: TRUE when the client first appeared via MM API initial sync
  -- (never had orders, calls, ads, IA, or any other data source). Once a
  -- non-MM data point arrives (order, call, ad, etc.), set FALSE.
  ADD COLUMN IF NOT EXISTS is_mm_only             BOOLEAN NOT NULL DEFAULT FALSE;

-- mm_global_id should be unique when populated. Partial unique index so NULLs
-- don't collide (lots of existing rows will have NULL until first sync).
CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_mm_global_id_unique
  ON clients(mm_global_id)
  WHERE mm_global_id IS NOT NULL;

-- (mm_database, mm_customer_id) is the natural lookup key during ETL
CREATE UNIQUE INDEX IF NOT EXISTS idx_clients_mm_db_customerid_unique
  ON clients(mm_database, mm_customer_id)
  WHERE mm_database IS NOT NULL AND mm_customer_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_clients_is_mm_only
  ON clients(is_mm_only)
  WHERE is_mm_only = TRUE;

CREATE INDEX IF NOT EXISTS idx_clients_mm_date_modified
  ON clients(mm_date_modified DESC);


-- ----------------------------------------------------------------------
-- 2) opportunities: sales pipeline (Open / Won / Lost)
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS opportunities (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- MM identity
  mm_database             TEXT NOT NULL,
  mm_opportunity_id       INTEGER NOT NULL,

  -- Resolved local client (NULL until reconciled by ETL)
  client_id               UUID REFERENCES clients(id) ON DELETE SET NULL,

  -- MM contact (may differ from CustomerID after sub-contact rollup)
  mm_contact_id           INTEGER,

  -- Core
  name                    TEXT,
  description             TEXT,
  next_step               TEXT,
  notes                   TEXT,

  -- Pipeline stage
  stage_id                INTEGER,
  stage_name              TEXT,
  stage_percent_closed    SMALLINT,
  status                  TEXT,    -- 'Open' | 'Won' | 'Lost'
  is_won                  SMALLINT,  -- 1 = Won, 0 = Lost, -1 = Open

  -- Type & source
  opportunity_type        TEXT,
  source                  TEXT,
  loss_reason             TEXT,

  -- Rep attribution
  owner_rep_id            INTEGER,
  owner_rep_name          TEXT,
  assigned_rep_id         INTEGER,
  assigned_rep_name       TEXT,

  -- Business unit + product attribution (multi-value)
  business_unit_primary   TEXT,
  business_units          TEXT[],
  product_primary         TEXT,
  products                TEXT[],
  proposal_ids            INTEGER[],  -- linked proposals (from MM)

  -- Money
  amount                  NUMERIC(12,2),
  probability             SMALLINT,
  expected_revenue        NUMERIC(12,2),

  -- Dates
  close_date              DATE,
  actual_close_date       DATE,
  mm_created_date         TIMESTAMPTZ,
  mm_modified_date        TIMESTAMPTZ,

  -- ETL audit
  synced_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (mm_database, mm_opportunity_id)
);

CREATE INDEX IF NOT EXISTS idx_opportunities_client
  ON opportunities(client_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_status
  ON opportunities(status);
CREATE INDEX IF NOT EXISTS idx_opportunities_close_date
  ON opportunities(close_date);
CREATE INDEX IF NOT EXISTS idx_opportunities_assigned_rep
  ON opportunities(assigned_rep_id);
CREATE INDEX IF NOT EXISTS idx_opportunities_mm_modified
  ON opportunities(mm_modified_date DESC);


-- ----------------------------------------------------------------------
-- 3) client_activities: notes, calls, emails, meetings
-- ----------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS client_activities (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

  -- MM identity
  mm_database     TEXT NOT NULL,
  mm_activity_id  INTEGER NOT NULL,

  -- Resolved local client (NULL until reconciled)
  client_id       UUID REFERENCES clients(id) ON DELETE SET NULL,
  mm_customer_id  INTEGER,  -- raw MM CustomerID for backfill lookup

  -- Rep
  rep_id          INTEGER,
  rep_name        TEXT,

  -- Content
  notes           TEXT,
  activity_type   TEXT,  -- "Call", "Email", "Meeting Sales", often NULL

  -- Classification flags (from gsActivities boolean columns)
  is_call         BOOLEAN,
  is_email        BOOLEAN,
  is_letter       BOOLEAN,
  is_mass_email   BOOLEAN,
  is_system       BOOLEAN,  -- TRUE = auto-generated by other MM modules

  -- Timing
  date_added      TIMESTAMPTZ,
  date_completed  TIMESTAMPTZ,
  callback_date   TIMESTAMPTZ,
  meeting_date    TIMESTAMPTZ,

  -- ETL audit
  synced_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  UNIQUE (mm_database, mm_activity_id)
);

CREATE INDEX IF NOT EXISTS idx_client_activities_client
  ON client_activities(client_id);
CREATE INDEX IF NOT EXISTS idx_client_activities_date_added
  ON client_activities(date_added DESC);
CREATE INDEX IF NOT EXISTS idx_client_activities_rep
  ON client_activities(rep_id);
CREATE INDEX IF NOT EXISTS idx_client_activities_mm_customer
  ON client_activities(mm_database, mm_customer_id);


-- ----------------------------------------------------------------------
-- 4) Documentation comments
-- ----------------------------------------------------------------------
COMMENT ON COLUMN clients.mm_global_id IS
  'MagManager cross-tenant canonical identifier ({tenant_id}-{gsCustomersID}, e.g. ''2400-1618'')';
COMMENT ON COLUMN clients.mm_database IS
  'MM tenant database name (thehomemagcolorado | thehomemagutah | thehomemagsanantonio). SA covers both AU and SA markets — disambiguate via clients.primary_market_id.';
COMMENT ON COLUMN clients.is_mm_only IS
  'TRUE when the client first appeared via MM API initial sync with no other source data. Flip to FALSE when any other data source (order/call/ad/IA) arrives.';
COMMENT ON COLUMN clients.mm_priority_raw IS
  'Raw Priority JSON from MM. The single primary value is extracted to clients.priority. Multi-value priorities (rare) live here as a fallback.';

COMMENT ON TABLE opportunities IS
  'Sales pipeline from MagManager api_OpportunityGetTHM. One row per MM opportunity. business_units/products/proposal_ids arrays capture multi-attribution from MM junction tables.';
COMMENT ON TABLE client_activities IS
  'Contact activity log from MagManager api_ContactActivityGetTHM. Notes, calls, emails, meetings. Filter is_system=false to exclude auto-generated entries.';
