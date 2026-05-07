"""
Seed the canonical category tree (top-level categories + subcategories).

Flat 2-tier structure: ~27 top-level categories with subcategories under each.
No "groups" layer — was over-engineered. Top-level IS the dropdown the user picks.

Idempotent — safe to run multiple times. Inserts use ON CONFLICT DO NOTHING.

Usage:
  python setup/seed_categories.py
  python setup/seed_categories.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[&,/]", " ", text)
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")


# ===== Canonical Tree (flat, 2-tier) =====
# Format: [(top_category_name, [subcategory_name, ...]), ...]
TREE = [
    # --- Exterior trades ---
    ("Roofing", ["Asphalt Roofing", "Metal Roofing", "Tile Roofing", "Roof Repair"]),
    ("Siding & Gutters", ["Siding", "Gutters", "Soffit & Fascia"]),
    ("Windows", ["Window Install/Replacement", "Window Wells", "Skylights", "Blinds & Shutters"]),
    ("Doors", ["Entry Doors", "Patio Doors", "Glass Doors", "Interior Doors"]),
    ("Garages", ["Garage Doors", "Garage Floor Coatings", "Garage Storage"]),
    ("Painting", ["Interior Painting", "Exterior Painting", "Specialty Coatings"]),

    # --- Outdoor / Yard ---
    ("Decks & Outdoor Living", ["Decks", "Porches", "Pergolas", "Outdoor Kitchens", "Fire Features", "Patios"]),
    ("Awnings & Patio Covers", ["Awnings", "Sunrooms", "Patio Covers"]),
    ("Landscaping", ["Lawn Care", "Garden Design", "Sprinklers", "Hardscaping", "Artificial Turf"]),
    ("Concrete, Pavers & Driveways", ["Concrete", "Pavers", "Driveways", "Walkways", "Curbing"]),
    ("Tree Services", ["Tree Removal", "Pruning", "Stump Grinding"]),
    ("Fences & Gates", ["Fences", "Gates", "Iron Railings"]),
    ("Pools & Spas", ["Pools", "Hot Tubs & Spas", "Pool Service"]),

    # --- Interior / Structural ---
    ("Home Remodeling", ["Kitchen Remodel", "Bath Remodel", "Basement Finishing", "Whole-Home Remodel", "Cabinetry & Storage", "Walls & Insulation"]),
    ("Foundation Repair", ["Foundation Leveling", "Concrete Lifting", "Basement Waterproofing", "Crawl Space Repair"]),
    ("Flooring", ["Carpet", "Hardwood", "Tile", "Vinyl", "Laminate"]),

    # --- Mechanical / Trades ---
    ("HVAC & Plumbing", ["Heating & Air", "Plumbing", "Water Heaters", "Water Treatment"]),
    ("Electrical & Lighting", ["Electrical", "Lighting", "Smart Home"]),
    ("Solar & Energy", ["Solar", "Energy Efficiency", "Battery Storage"]),

    # --- Specialty Services ---
    ("Cleaning Services", ["House Cleaning", "Carpet Cleaning", "Window Cleaning", "Pressure Washing"]),
    ("Restoration & Junk Removal", ["Restoration", "Junk Removal", "Demolition"]),
    ("Handyman Services", ["General Handyman", "Repairs"]),
    ("Pest & Wildlife", ["Pest Control", "Wildlife Removal"]),

    # --- Construction / Big projects ---
    ("Construction & Design", ["General Contractors", "Custom Homes", "Architects", "ADUs"]),

    # --- Misc ---
    ("Appliances", []),
    ("Furniture", []),
    ("Not Home Improvement", []),
]


# ===== Alias map: legacy text values -> target slug =====
# Mostly identity for legacy names that are unchanged. Multi-text values
# get split on commas at migration time, so each fragment maps individually.
LEGACY_ALIAS_MAP = {
    # Direct matches with legacy MM column values
    "Windows": "windows",
    "Window Wells": "windows",
    "Window Well Covers": "windows",
    "Egress Windows": "windows",
    "Blinds & Shutters": "windows",
    "Blinds": "windows",
    "Shutters": "windows",
    "Window Treatments": "windows",
    "Window Coverings": "windows",
    "Drapes & Curtains": "windows",
    "Doors": "doors",
    "Glass & Doors": "doors",
    "Garages": "garages",
    "Roofing": "roofing",
    "Roofers": "roofing",
    "Siding & Gutters": "siding-gutters",
    "Painting": "painting",
    "Decks and Porches": "decks-outdoor-living",
    "Decks": "decks-outdoor-living",
    "Outdoor Living": "decks-outdoor-living",
    "Awnings & Patio Covers": "awnings-patio-covers",
    "Landscaping": "landscaping",
    "Artificial Turf": "artificial-turf",
    "Synthetic Grass": "artificial-turf",
    "Astro Turf": "artificial-turf",
    "Tree Services": "tree-services",
    "Concrete, Pavers & Driveways": "concrete-pavers-driveways",
    "Concrete/Pavers": "concrete-pavers-driveways",
    "Concrete": "concrete-pavers-driveways",
    "Pavers & Driveways": "concrete-pavers-driveways",
    "Fences & Gates": "fences-gates",
    "Iron & Railings": "fences-gates",
    "Pools & Spas": "pools-spas",
    "Kitchen & Bath Remodeling": "home-remodeling",
    "Kitchens": "home-remodeling",
    "Bathrooms": "home-remodeling",
    "Bathroom Remodeling": "home-remodeling",
    "Kitchen Remodeling": "home-remodeling",
    "Basement Finishing & Remodeling": "home-remodeling",
    "Basement Finishing": "home-remodeling",
    "Cabinetry": "home-remodeling",
    "Storage & Shelves": "home-remodeling",
    "Walls & Insulation": "home-remodeling",
    "Marble & Granite": "home-remodeling",
    "Tile & Stone": "flooring",
    "Home Remodeling": "home-remodeling",
    "Home Improvement": "home-remodeling",
    "Attics": "home-remodeling",
    "Foundation Repair": "foundation-repair",
    "Foundation": "foundation-repair",
    "Groundworks": "foundation-repair",
    "GWRK": "foundation-repair",
    "Concrete Lifting": "foundation-repair",
    "Foundation Leveling": "foundation-repair",
    "Carpet & Flooring": "flooring",
    "Heating & Air": "hvac-plumbing",
    "HVAC": "hvac-plumbing",
    "Plumbing & Water": "hvac-plumbing",
    "Plumbing": "hvac-plumbing",
    "Electrical & Lighting": "electrical-lighting",
    "Solar Power & Energy": "solar-energy",
    "Cleaning Services": "cleaning-services",
    "Exterior Cleaning": "cleaning-services",
    "Restoration & Junk Removal": "restoration-junk-removal",
    "Restoration Services": "restoration-junk-removal",
    "Handyman Services": "handyman-services",
    "Preventative Maintenance": "handyman-services",
    "Animal & Pest Control": "pest-wildlife",
    "Construction Services": "construction-design",
    "Building & Design": "construction-design",
    "Builders/Remodelers": "construction-design",
    "Builders & Remodelers": "construction-design",
    "Interior & Design": "construction-design",
    "Custom Homes": "construction-design",
    "Custom Home Builder": "construction-design",
    "Architects": "construction-design",
    "Architecture": "construction-design",
    "ADUs": "construction-design",
    "Whole-Home Remodel": "construction-design",
    "Whole Home Remodel": "construction-design",
    "General Contractors": "construction-design",
    "General Contractor": "construction-design",
    "Appliances": "appliances",
    "Furniture": "furniture",
    "Not Home Improvement": "not-home-improvement",
    "Real Estate": "not-home-improvement",
    "Marketing": "not-home-improvement",
    "Specialty Services": "handyman-services",  # closest match
    "Exterior Services": "siding-gutters",       # generic exterior
    "Fireplaces": "home-remodeling",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    slug_to_id: dict[str, str] = {}

    def insert_category(name: str, parent_id: str | None, level: int, sort_order: int) -> str:
        slug = slugify(name)
        existing = sb.table("categories").select("id").eq("slug", slug).execute().data
        if existing:
            slug_to_id[slug] = existing[0]["id"]
            return existing[0]["id"]
        if args.dry_run:
            print(f"  [DRY] {slug} (level {level}, parent {parent_id})")
            slug_to_id[slug] = f"DRY-{slug}"
            return slug_to_id[slug]
        row = {"name": name, "slug": slug, "level": level, "sort_order": sort_order}
        if parent_id:
            row["parent_id"] = parent_id
        result = sb.table("categories").insert(row).execute().data
        slug_to_id[slug] = result[0]["id"]
        return result[0]["id"]

    print("Seeding flat tree (top-level categories + subcategories)...")
    cat_count = sub_count = 0
    for c_idx, (cat_name, subs) in enumerate(TREE):
        cid = insert_category(cat_name, None, 1, c_idx)
        cat_count += 1
        for s_idx, sub_name in enumerate(subs):
            insert_category(sub_name, cid, 2, s_idx)
            sub_count += 1
    print(f"  {cat_count} top-level categories, {sub_count} subcategories")

    print("\nSeeding alias map...")
    alias_count = 0
    skipped = []
    for legacy_text, target_slug in LEGACY_ALIAS_MAP.items():
        target_id = slug_to_id.get(target_slug)
        if not target_id:
            skipped.append((legacy_text, target_slug))
            continue
        if args.dry_run:
            alias_count += 1
            continue
        existing = sb.table("category_aliases").select("alias").eq("alias", legacy_text).execute().data
        if existing:
            continue
        sb.table("category_aliases").insert({
            "alias": legacy_text,
            "category_id": target_id,
            "source": "legacy_text",
        }).execute()
        alias_count += 1
    print(f"  {alias_count} aliases inserted")
    if skipped:
        print(f"  WARNING: {len(skipped)} aliases pointed to unknown slugs:")
        for txt, slug in skipped:
            print(f"    {txt!r} -> {slug!r}")

    print("\nDone.")


if __name__ == "__main__":
    main()
