-- ============================================================
-- Schema Update: Add client detail fields + orders table
-- Run in Supabase SQL Editor (Settings > SQL Editor > New Query)
-- ============================================================

-- 1. Add new columns to clients table
ALTER TABLE clients ADD COLUMN IF NOT EXISTS priority text;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS sales_attrib text;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS mm_start_issue date;

-- 2. Create orders table for Magazine Manager order data
CREATE TABLE IF NOT EXISTS orders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    mm_order_id integer NOT NULL,
    client_id uuid REFERENCES clients(id),
    zone_id uuid REFERENCES zones(id),
    issue_date text,
    issue_date_parsed date,
    product text,
    size text,
    position text,
    notes text,
    net numeric(12,2),
    gross numeric(12,2),
    amount_due numeric(12,2),
    sales_rep text,
    commission_rep text,
    contact_type text,
    ia_category text,
    opp_category text,
    biz_category text,
    special_section text,
    proposal_type text,
    space text,
    year integer,
    created_at timestamptz DEFAULT now()
);

-- 3. Unique constraint: order ID is unique per zone (market)
ALTER TABLE orders ADD CONSTRAINT orders_mm_order_id_zone_unique
    UNIQUE (mm_order_id, zone_id);

-- 4. Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_orders_client_id ON orders(client_id);
CREATE INDEX IF NOT EXISTS idx_orders_zone_id ON orders(zone_id);
CREATE INDEX IF NOT EXISTS idx_orders_year ON orders(year);
CREATE INDEX IF NOT EXISTS idx_orders_issue_date_parsed ON orders(issue_date_parsed);
CREATE INDEX IF NOT EXISTS idx_orders_mm_order_id ON orders(mm_order_id);

-- 5. Enable RLS on orders (same pattern as other tables)
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;

-- 6. RLS policies — allow service_role full access, anon read-only
CREATE POLICY "Service role full access on orders"
    ON orders FOR ALL
    USING (auth.role() = 'service_role');

CREATE POLICY "Anon read access on orders"
    ON orders FOR SELECT
    USING (true);

-- 7. Updated_at trigger (reuse if exists, or create)
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
