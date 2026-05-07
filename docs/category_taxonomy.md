# Category Taxonomy — Reference

> **For:** Streamlit app, future chats, anyone querying client categories.
> **TL;DR:** Flat 2-tier hierarchy. 27 top-level categories + ~85 subcategories. Use `client_categories` junction with `is_primary=true` filter for specialists, or `v_clients_with_categories` view for multi-tag rollup.

---

## The Tree (2 layers, no groups)

| Layer | Count | Purpose |
|---|---:|---|
| Top-level category | 27 | Day-to-day filter — what the user picks in the dashboard. |
| Subcategory | ~85 | Optional finer detail. Use to drill down. |

The "groups" layer was removed (was over-engineered). Each top-level IS the dropdown option.

---

## Top-Level Categories

### Exterior trades
- **Roofing** — Asphalt, Metal, Tile, Roof Repair
- **Siding & Gutters** — Siding, Gutters, Soffit & Fascia
- **Windows** — Window Install/Replacement, Window Wells, Skylights
- **Doors** — Entry Doors, Patio Doors, Glass Doors, Interior Doors
- **Garages** — Garage Doors, Garage Floor Coatings, Garage Storage
- **Painting** — Interior Painting, Exterior Painting, Specialty Coatings

### Outdoor / Yard
- **Decks & Outdoor Living** — Decks, Porches, Pergolas, Outdoor Kitchens, Fire Features, Patios
- **Awnings & Patio Covers** — Awnings, Sunrooms, Patio Covers
- **Landscaping** — Lawn Care, Garden Design, Sprinklers, Hardscaping
- **Concrete, Pavers & Driveways** — Concrete, Pavers, Driveways, Walkways, Curbing
- **Tree Services** — Tree Removal, Pruning, Stump Grinding
- **Fences & Gates** — Fences, Gates, Iron Railings
- **Pools & Spas** — Pools, Hot Tubs & Spas, Pool Service

### Interior / Structural
- **Home Remodeling** — Kitchen Remodel, Bath Remodel, Basement Finishing, Whole-Home Remodel, Cabinetry & Storage, Walls & Insulation
- **Foundation Repair** — Foundation Leveling, Concrete Lifting, Basement Waterproofing, Crawl Space Repair
- **Flooring** — Carpet, Hardwood, Tile, Vinyl, Laminate

### Mechanical / Trades
- **HVAC & Plumbing** — Heating & Air, Plumbing, Water Heaters, Water Treatment
- **Electrical & Lighting** — Electrical, Lighting, Smart Home
- **Solar & Energy** — Solar, Energy Efficiency, Battery Storage

### Specialty Services
- **Cleaning Services** — House Cleaning, Carpet Cleaning, Window Cleaning, Pressure Washing
- **Restoration & Junk Removal** — Restoration, Junk Removal, Demolition
- **Handyman Services** — General Handyman, Repairs
- **Pest & Wildlife** — Pest Control, Wildlife Removal

### Construction / Big projects
- **Construction & Design** — General Contractors, Custom Homes, Architects, ADUs

### Misc
- **Appliances**
- **Furniture**
- **Not Home Improvement** — catch-all

---

## Tables

### `categories`
The tree.
- `id`, `name`, `slug`, `parent_id`, `level` (1=top, 2=sub), `sort_order`, `is_active`

### `client_categories`
Many-to-many junction. Multi-tag.
- `client_id`, `category_id`, `is_primary` (exactly one TRUE per client), `source`, `confidence`, `reasoning`
- `source` values: `manual` (user-locked), `mm_api` (when integrated), `llm_auto` (Haiku), `legacy_text` (initial backfill)

### `category_aliases`
Translation map. Used by ETL to normalize incoming free-text values.

### `classification_log`
Audit trail per LLM run.

### `client_reclassification_queue`
Continuous-classification queue.

### `clients_category_backup`
Snapshot of original `clients.category` text values (2,530 rows). Fallback only — do not query for analytics.

### `manual_tag_snapshot`
Snapshot taken during the 2026-04-29 restructure. 64 manual tags preserved for re-application.

---

## Source-of-truth hierarchy

When in doubt about a client's category:
1. **`client_categories.source='manual'`** — user-locked, authoritative
2. **`client_categories.source='mm_api'`** — MagManager (when integrated)
3. **`client_categories.source='llm_auto'`** — Haiku classification with confidence + reasoning
4. **`client_categories.source='legacy_text'`** — initial backfill from old `clients.category` column

The `clients.category` text column still exists as a backward-compat shim. Don't query it for analytics.

---

## Canonical queries

### CRITICAL: `is_primary=true` for specialists

**This is the default for most reports.** When the user picks "Kitchen & Bath Remodeling" subcategory, they want specialists, not handyman companies that happen to mention bathroom services.

```sql
-- Specialists in a given category (DEFAULT)
SELECT DISTINCT c.name
FROM clients c
JOIN client_categories cc ON cc.client_id = c.id
JOIN categories cat ON cat.id = cc.category_id
WHERE cc.is_primary = true
  AND cat.slug = 'roofing'
  AND NOT c.is_mapping_stub;

-- All clients tagged (multi-trade rollup)
SELECT DISTINCT c.name
FROM clients c
JOIN v_clients_with_categories v ON v.client_id = c.id
WHERE v.slug = 'roofing'
  AND NOT c.is_mapping_stub;
```

### Subcategory drill-down

```sql
-- Only window installers (not cleaners or well-cover companies)
SELECT c.name FROM clients c
JOIN client_categories cc ON cc.client_id = c.id AND cc.is_primary
JOIN categories cat ON cat.id = cc.category_id
WHERE cat.slug = 'window-installreplacement';

-- Only window cleaners (under Cleaning Services)
SELECT c.name FROM clients c
JOIN client_categories cc ON cc.client_id = c.id AND cc.is_primary
JOIN categories cat ON cat.id = cc.category_id
WHERE cat.slug = 'window-cleaning';
```

### Multi-tag client breakdown

```sql
-- Clients tagged in 2+ categories (genuine multi-trade)
SELECT c.name, STRING_AGG(cat.name, ', ' ORDER BY cc.is_primary DESC) AS categories
FROM clients c
JOIN client_categories cc ON cc.client_id = c.id
JOIN categories cat ON cat.id = cc.category_id
WHERE cat.level = 1
GROUP BY c.id, c.name
HAVING COUNT(DISTINCT cat.id) >= 2
ORDER BY c.name;
```

### Top-level dropdown options

```sql
-- For Streamlit dropdown
SELECT id, name, slug FROM categories
WHERE level = 1 AND is_active = true
ORDER BY sort_order, name;
```

### Subcategory filtered by parent

```sql
-- Subcategories under a given top-level
SELECT id, name, slug FROM categories
WHERE level = 2
  AND parent_id IN (SELECT id FROM categories WHERE slug = ANY(ARRAY['roofing','siding-gutters']))
  AND is_active = true;
```

---

## How clients get classified

### One-time backfill (2026-04-29)
1. **Phase 2** — `setup/migrate_categories.py` parsed every `clients.category` text value via the alias map, longest-match-first to handle compounds like "Concrete, Pavers & Driveways". Output: `client_categories` rows with `source='legacy_text'`.
2. **Phase 3** — `scripts/auto_classify_clients.py` built multi-signal evidence bundles (name + ad services_listed + CT notes + order products + CallRail labels) and sent each to Haiku 4.5. Output: junction rows with `source='llm_auto'`, confidence, reasoning. Audit log in `classification_log`.

### Ongoing
- **Manual review:** `scripts/build_category_review.py` exports flagged cases (disagreements + low-confidence) to Excel. User edits `approved_primary`. `setup/import_category_approvals.py` applies decisions and locks tags as `source='manual'`.
- **MM API (when integrated):** daily sync pulls MM's category custom field. Each MM string is looked up in `category_aliases`. Manual tags preserved during sync.
- **New data triggers:** new ad / first orders → client enqueued for re-classification.

---

## Important caveats

- **Legacy `clients.category` text is unreliable.** Russel Williams was tagged "Electrical & Lighting, Windows" but they're actually a window CLEANING company. Trust `client_categories` joins, not the text column.
- **`is_primary=true` enforced as one per client** via partial unique index. Don't try to insert a second primary; demote the existing one first.
- **Mapping stubs (`clients.is_mapping_stub=true`)** are not auto-classified and excluded from analytics by default. Always filter `AND NOT is_mapping_stub`.
- **Handyman/GC clients are deliberately tagged ONLY in Handyman Services or Construction & Design** — not in every specialty their ad mentions. This prevents pollution of trade-specific dropdowns.
