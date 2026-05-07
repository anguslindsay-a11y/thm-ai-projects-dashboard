-- 006_call_tracking.sql
-- Adds call tracking yes/no fields imported from THM Call Tracking.xlsx.
--
-- client_zones.has_call_tracking: per-zone flag (a client can be tracked in some zones but not others)
-- clients.has_call_tracking: rollup, TRUE if any client_zones row is TRUE
-- clients.call_tracking_notes: raw "Call Track Notes" text from MM, preserved for audit

ALTER TABLE client_zones
  ADD COLUMN IF NOT EXISTS has_call_tracking BOOLEAN;

ALTER TABLE clients
  ADD COLUMN IF NOT EXISTS has_call_tracking BOOLEAN,
  ADD COLUMN IF NOT EXISTS call_tracking_notes TEXT;

CREATE INDEX IF NOT EXISTS idx_clients_has_call_tracking ON clients(has_call_tracking);
CREATE INDEX IF NOT EXISTS idx_client_zones_has_call_tracking ON client_zones(has_call_tracking);
