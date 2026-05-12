-- 014_clients_has_orders.sql
-- Adds clients.has_orders boolean — the canonical "is this a real client
-- with order history" flag. Used by:
--   - Streamlit dropdowns (filter to real clients only)
--   - Platform ETLs (CallRail/Uniqode/IA) as the valid-attach-target check
--   - Reports needing the "core book" cohort
--
-- Maintained by sync_client_has_orders() — run on every orders ingest +
-- weekly refresh. TRUE when client has either a local orders row OR a
-- non-NULL mm_first_order_date (which means MM says they've ordered, even
-- if our local orders table doesn't have the rows yet).
--
-- When the MM Orders endpoint goes live, the local-orders side becomes
-- comprehensive and we can drop the mm_first_order_date branch. Until then
-- both signals are needed.

ALTER TABLE clients
  ADD COLUMN IF NOT EXISTS has_orders BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_clients_has_orders
  ON clients(has_orders) WHERE has_orders = TRUE;

COMMENT ON COLUMN clients.has_orders IS
  'TRUE when client has at least one order from any source (local orders table OR MM-derived mm_first_order_date). Use this as the canonical filter for "real clients with revenue history". Maintained by sync_client_has_orders().';


-- Recompute the flag from current data. Idempotent — safe to re-run.
CREATE OR REPLACE FUNCTION sync_client_has_orders()
RETURNS TABLE(flipped_to_true INTEGER, flipped_to_false INTEGER) AS $$
DECLARE
  to_true  INTEGER;
  to_false INTEGER;
BEGIN
  -- TRUE: any client with local orders OR an MM first-order date
  WITH flip_on AS (
    UPDATE clients
    SET has_orders = TRUE
    WHERE has_orders = FALSE
      AND (
        EXISTS (SELECT 1 FROM orders o WHERE o.client_id = clients.id)
        OR mm_first_order_date IS NOT NULL
      )
    RETURNING 1
  )
  SELECT COUNT(*) INTO to_true FROM flip_on;

  -- FALSE: clients flagged TRUE that no longer have either signal
  -- (rare — happens when orders get deleted / MM contact updates)
  WITH flip_off AS (
    UPDATE clients
    SET has_orders = FALSE
    WHERE has_orders = TRUE
      AND NOT EXISTS (SELECT 1 FROM orders o WHERE o.client_id = clients.id)
      AND mm_first_order_date IS NULL
    RETURNING 1
  )
  SELECT COUNT(*) INTO to_false FROM flip_off;

  RETURN QUERY SELECT to_true, to_false;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION sync_client_has_orders IS
  'Recompute clients.has_orders from current orders + mm_first_order_date data. Run after every orders ingest + MM contacts sync. Returns counts of (flipped_to_true, flipped_to_false).';

-- Initial backfill
SELECT * FROM sync_client_has_orders();
