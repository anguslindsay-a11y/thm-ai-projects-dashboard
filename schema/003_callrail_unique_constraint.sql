-- ============================================================
-- Schema Update: Add unique constraint on calls.callrail_id
-- Required for ETL upsert (ON CONFLICT) to work correctly
-- Run in Supabase SQL Editor before running etl_callrail.py
-- ============================================================

ALTER TABLE calls ADD CONSTRAINT calls_callrail_id_unique
    UNIQUE (callrail_id);
