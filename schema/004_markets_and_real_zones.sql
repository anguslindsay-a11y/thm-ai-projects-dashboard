-- Migration 004: Restructure zones into markets + real distribution zones
-- Applied: 2026-04-09
--
-- Before: zones table had 5 rows (CO, UT, AU, SA, XX) that were actually markets
-- After: markets table (4 markets) + zones table (11 real distribution zones)
--
-- This migration was applied in multiple steps via Supabase MCP:
--   004a: Create markets table, add market_id/abbreviation/distribution columns
--   004b: Drop old views, swap constraints, drop old zone rows, recreate views

-- Step 1: Create markets table
CREATE TABLE IF NOT EXISTS markets (
  id uuid PRIMARY KEY DEFAULT extensions.uuid_generate_v4(),
  code text NOT NULL UNIQUE,
  name text NOT NULL UNIQUE,
  state text NOT NULL,
  is_active boolean DEFAULT true,
  created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now()
);

ALTER TABLE markets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Service role full access on markets"
  ON markets FOR ALL USING (auth.role() = 'service_role');

CREATE POLICY "Anon read access on markets"
  ON markets FOR SELECT USING (true);

INSERT INTO markets (code, name, state) VALUES
  ('CO', 'Colorado', 'CO'),
  ('UT', 'Utah', 'UT'),
  ('AU', 'Austin', 'TX'),
  ('SA', 'San Antonio', 'TX');

-- Step 2: Add market_id columns
ALTER TABLE orders ADD COLUMN market_id uuid REFERENCES markets(id);
ALTER TABLE clients ADD COLUMN primary_market_id uuid REFERENCES markets(id);
ALTER TABLE sales_reps ADD COLUMN primary_market_id uuid REFERENCES markets(id);
ALTER TABLE zones ADD COLUMN market_id uuid REFERENCES markets(id);
ALTER TABLE zones ADD COLUMN abbreviation text;
ALTER TABLE zones ADD COLUMN distribution_count integer;

-- Step 3: Populate market_id from existing zone_id mappings (DML - run separately)
-- Step 4: Insert 11 real zones (DML - run separately)
-- Step 5: Parse product -> zone_id on orders (DML - run separately)
-- Step 6: Rebuild client_zones from orders (DML - run separately)

-- Step 7: Cleanup
-- Drop old views, swap constraints, drop old columns, recreate views
-- (See 004b migration in Supabase dashboard for full DDL)
