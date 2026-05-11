-- 013_client_activities_search_index.sql
-- Add trigram + full-text search support to client_activities.notes.
-- Enables ILIKE / similarity / @@ to_tsquery searches at scale.
--
-- With the 3-year backfill running ~200k rows and growing, an ILIKE
-- search like '%cancel%' is critical for cancellation pattern detection,
-- pre-call intel, and rep coaching. Without these indexes, full-table
-- scans would be seconds-long at this volume.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Trigram for ILIKE searches like '%cancel%' or '%pause%'
CREATE INDEX IF NOT EXISTS idx_client_activities_notes_trgm
  ON client_activities
  USING gin (notes gin_trgm_ops);

-- Full-text for word-aware searches (to_tsquery('cancel & pause'))
CREATE INDEX IF NOT EXISTS idx_client_activities_notes_fts
  ON client_activities
  USING gin (to_tsvector('english', coalesce(notes, '')));
