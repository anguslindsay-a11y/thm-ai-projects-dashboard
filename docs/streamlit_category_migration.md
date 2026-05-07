# Streamlit Category Migration — Implementation Guide

The new structure is a **flat 2-tier hierarchy**: 27 top-level categories + ~85 subcategories. No more "groups" layer.

---

## What changed in the database

| Before (3-tier with groups) | After (flat 2-tier) |
|---|---|
| 8 groups → 30 categories → 95 subcategories | 27 top-level categories → ~85 subcategories |
| User had to drill: Group → Category → Subcategory (3 dropdowns) | User picks Category, optionally Subcategory (2 dropdowns) |
| Group level often empty/confusing | Top-level IS the category |

The legacy `clients.category` text column is preserved as a fallback (`clients_category_backup` snapshot table).

---

## Critical UX decision: `is_primary` filtering

**This is the single most important call in the dashboard.** When the user picks "Roofing":

**A) Specialists only** — clients whose PRIMARY trade is Roofing. ← **Default.**
**B) Anyone tagged** — includes secondaries (catches multi-trade companies but pollutes the list).

```sql
-- A: Specialists only (default)
WHERE EXISTS (
    SELECT 1 FROM client_categories cc
    JOIN categories cat ON cat.id = cc.category_id
    WHERE cc.client_id = c.id
      AND cc.is_primary = true
      AND cat.slug = ANY(%(slugs)s)
)

-- B: Anyone tagged (rollup)
WHERE EXISTS (
    SELECT 1 FROM v_clients_with_categories v
    WHERE v.client_id = c.id
      AND v.slug = ANY(%(slugs)s)
)
```

Offer **B** as a "[ ] Include multi-trade companies" checkbox, off by default.

---

## 2-dropdown picker

Two dropdowns: top-level Category (multi-select) + Subcategory (filtered to picked categories).

```python
import streamlit as st
from supabase_client import fetch_categories, query

top_cats = fetch_categories(level=1)   # 27 top-level
all_subs = fetch_categories(level=2)   # ~85 subcategories

col1, col2 = st.columns(2)

with col1:
    selected_cat_names = st.multiselect(
        "Category",
        [c["name"] for c in top_cats],
        help="Pick one or more top-level categories",
    )

with col2:
    if selected_cat_names:
        # Show subcategories whose parent is in the picked top-levels
        visible_subs = [s for s in all_subs if s["parent_name"] in selected_cat_names]
        selected_sub_names = st.multiselect(
            "Subcategory (optional, more specific)",
            [s["name"] for s in visible_subs],
            help="Drill into a more specific niche",
        )
    else:
        selected_sub_names = []
        st.caption("Pick a category to see subcategories")

# Resolve to slugs at the most specific level the user picked
if selected_sub_names:
    selected_slugs = [s["slug"] for s in all_subs if s["name"] in selected_sub_names]
elif selected_cat_names:
    selected_slugs = [c["slug"] for c in top_cats if c["name"] in selected_cat_names]
else:
    selected_slugs = []

include_secondaries = st.checkbox(
    "Include multi-trade companies (secondary tags)",
    value=False,
    help="Off: only show specialists. On: also include companies tagged as a secondary trade.",
)
```

---

## fetch_categories helper

In `Streamlit Dashboard/supabase_client.py`, replace the old `fetch_categories()`:

```python
def fetch_categories(level: int = 1, include_inactive: bool = False) -> list[dict]:
    """Fetch categories at a level for dropdown options.

    Args:
        level: 1 = top-level (the main dropdown), 2 = subcategories

    Returns: [{id, name, slug, parent_name}]
    """
    rows = (
        sb.table("categories")
          .select("id,name,slug,level,parent_id,sort_order")
          .eq("level", level)
          .execute().data
    )
    if not include_inactive:
        rows = [r for r in rows if r.get("is_active", True)]

    # Lookup parent names for subcategory display
    all_cats = sb.table("categories").select("id,name").execute().data
    parent_names = {c["id"]: c["name"] for c in all_cats}

    return sorted([
        {
            "id": r["id"],
            "name": r["name"],
            "slug": r["slug"],
            "parent_name": parent_names.get(r["parent_id"]),
        }
        for r in rows
    ], key=lambda x: (x.get("sort_order", 0), x["name"]))
```

**Delete** the old `_split_categories()` function and `COMPOUND_CATEGORIES` set entirely.

---

## Filter query — canonical pattern

Wherever you have `WHERE c.category ILIKE ANY(...)`:

```python
if include_secondaries:
    cat_filter = """
        EXISTS (
            SELECT 1 FROM v_clients_with_categories v
            WHERE v.client_id = c.id AND v.slug = ANY(%(slugs)s)
        )
    """
else:
    cat_filter = """
        EXISTS (
            SELECT 1 FROM client_categories cc
            JOIN categories cat ON cat.id = cc.category_id
            WHERE cc.client_id = c.id
              AND cc.is_primary = true
              AND cat.slug = ANY(%(slugs)s)
        )
    """

sql = f"""
    SELECT DISTINCT c.id, c.name, c.status, m.code AS market
    FROM clients c
    LEFT JOIN markets m ON m.id = c.primary_market_id
    WHERE NOT c.is_mapping_stub
      AND {cat_filter}
    ORDER BY c.name
"""
rows = query(sql, {"slugs": selected_slugs})
```

---

## GROUP BY queries

```sql
-- Primary-only counts (each client counted once, in their dominant trade)
SELECT cat.name AS category, COUNT(DISTINCT cc.client_id) AS clients
FROM client_categories cc
JOIN categories cat ON cat.id = cc.category_id
JOIN clients c ON c.id = cc.client_id
WHERE cc.is_primary = true
  AND cat.level = 1
  AND NOT c.is_mapping_stub
GROUP BY cat.name
ORDER BY clients DESC;
```

---

## Hardcoded category strings in scripts

Replace string literals like `WHERE category = 'HVAC'` with slug lookups:

```python
hvac = query("""
    SELECT c.* FROM clients c
    JOIN client_categories cc ON cc.client_id = c.id AND cc.is_primary = true
    JOIN categories cat ON cat.id = cc.category_id
    WHERE cat.slug = 'hvac-plumbing'
      AND NOT c.is_mapping_stub
""")
```

---

## Migration order

1. `fetch_categories` rewrite — non-breaking
2. Drop the Group dropdown — your existing 3-tier UI just becomes 2-tier (delete the Group selectbox)
3. Filter query swap — must happen TOGETHER for any page that filters
4. `is_primary` checkbox toggle — refinement
5. Hardcoded scripts — ad-hoc

---

## Fallback plan

If anything breaks:
- Legacy `clients.category` text column is preserved
- `clients_category_backup` table has full snapshot (2,530 rows)
- Restore: `UPDATE clients SET category = b.legacy_category FROM clients_category_backup b WHERE clients.id = b.id;`
- Roll back: `DROP TABLE category_aliases, client_categories, classification_log, client_reclassification_queue, manual_tag_snapshot, categories CASCADE;`

---

## Reference

- Full taxonomy + query patterns: `docs/category_taxonomy.md`
- Recursive view: `v_clients_with_categories`
