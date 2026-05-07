-- 005_client_status_values.sql
-- Expand clients.status check constraint to support order-derived lifecycle states.
--
-- New status values (computed from orders.issue_date_parsed):
--   active    - has any order with issue_date >= today (current or future)
--   cancelled - last order within the past 90 days (recently dropped off)
--   expired   - last order between 90-365 days ago
--   dormant   - last order more than 365 days ago
--   prospect  - zero orders ever (CallRail-only, mapping stubs, new leads)
--
-- The legacy 'inactive' value is kept for backward compatibility but is no
-- longer set by the import pipeline.

ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_status_check;

ALTER TABLE clients ADD CONSTRAINT clients_status_check
    CHECK (status IN ('active', 'cancelled', 'expired', 'dormant', 'prospect', 'inactive'));
