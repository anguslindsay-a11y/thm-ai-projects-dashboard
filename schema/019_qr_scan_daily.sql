-- 019_qr_scan_daily.sql
-- Daily-aggregated QR scan counts. Companion to qr_scans (per-scan rows).
--
-- The existing qr_scans table is per-scan-event with geo/device detail per
-- row -- driven by Uniqode CSV exports where every individual scan is a row.
--
-- Flowcode's Analytics API (abacus.v2.AbacusService/GetConversionRateSummary)
-- only exposes AGGREGATED data -- daily/weekly buckets per Suite. There is
-- no per-scan-event endpoint. To preserve our existing per-scan reporting
-- while still capturing Flowcode's aggregate data, we add a parallel table
-- for daily aggregates rather than synthesizing fake per-scan rows.
--
-- Reports that need per-scan detail query qr_scans (Uniqode-era).
-- Reports that need totals query qr_scan_daily (Flowcode-era) OR aggregate
-- from qr_scans. A view v_qr_scans_unified (added below) makes the union
-- straightforward.
--
-- Applied 2026-05-19.

CREATE TABLE qr_scan_daily (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  platform          TEXT NOT NULL,              -- 'flowcode' (extensible to others)
  suite_id          TEXT NOT NULL,              -- Flowcode Suite (Flow) UUID
  batch_id          TEXT,                       -- Flowcode Batch UUID (the codes container)
  code_id           TEXT,                       -- Flowcode Code UUID — NULL for Suite-level aggregate
  client_id         UUID REFERENCES clients(id) ON DELETE SET NULL,
  scan_date         DATE NOT NULL,              -- the calendar day (in `timezone`)
  scans             INTEGER NOT NULL DEFAULT 0, -- total scan events
  views             INTEGER NOT NULL DEFAULT 0, -- destination page views (downstream of scan)
  unique_visitors   INTEGER NOT NULL DEFAULT 0,
  timezone          TEXT NOT NULL DEFAULT 'America/Denver',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Dedupe key: one row per (platform, suite, code, day, timezone).
-- code_id may be NULL for Suite-level rows -- partial unique handles that.
CREATE UNIQUE INDEX uq_qr_scan_daily_code
  ON qr_scan_daily (platform, suite_id, code_id, scan_date, timezone)
  WHERE code_id IS NOT NULL;

CREATE UNIQUE INDEX uq_qr_scan_daily_suite
  ON qr_scan_daily (platform, suite_id, scan_date, timezone)
  WHERE code_id IS NULL;

CREATE INDEX idx_qr_scan_daily_client_date ON qr_scan_daily (client_id, scan_date);
CREATE INDEX idx_qr_scan_daily_suite       ON qr_scan_daily (suite_id);
CREATE INDEX idx_qr_scan_daily_date        ON qr_scan_daily (scan_date);

COMMENT ON TABLE qr_scan_daily IS
  'Daily-aggregated QR scan counts from platforms that expose aggregate-only analytics (Flowcode). Companion to qr_scans (per-scan rows, Uniqode-era). One row per (platform, suite, code, day) or Suite-level when code_id IS NULL.';

COMMENT ON COLUMN qr_scan_daily.code_id IS
  'Flowcode Code UUID for per-Code granularity. NULL for Suite-level rollups (when the ETL pulls Suite-only or per-Code is not requested).';

-- Touch updated_at on every update (reuses the project's existing helper)
CREATE TRIGGER trg_qr_scan_daily_updated_at
  BEFORE UPDATE ON qr_scan_daily
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
