"""
Seed zone_zip_codes from the 4 distribution map PDFs (CO, UT, AU, SA — 2026).

Source PDFs:
  data/Distribution-Maps-THMCO-2026.pdf
  data/Distribution-Maps-THMUT-2026 (1).pdf
  data/Distribution-Maps-THMAU-2026 (1).pdf
  data/Distribution-Maps-THMSA-2026 (1).pdf

CO has per-zip distribution counts (homes per zip).
UT/AU/SA only carry zip + city + county.

The off_page_subzone field is the operational sub-route within the main zone
(e.g., NC1/NC2 inside NOCO; N1/N2 inside ND; etc.).

Idempotent — uses upsert on (zone_id, zip_code).

Usage:
  python setup/import_zone_zip_codes.py
  python setup/import_zone_zip_codes.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


# ===== ZIP DATA =====
# Format: { zone_abbreviation: [ (zip, city, county, distribution_count|None, subzone|None), ... ] }

DATA = {
    # ---- CO: NOCO (Northern Colorado) — split into NC1/NC2 ----
    "NOCO": [
        # NC1
        ("80549", "Wellington",   "Larimer", 1249, "NC1"),
        ("80512", "Bellvue",      "Larimer", 483,  "NC1"),
        ("80513", "Berthoud",     "Larimer", 4471, "NC1"),
        ("80517", "Estes Park",   "Larimer", 2399, "NC1"),
        ("80521", "Fort Collins", "Larimer", 4093, "NC1"),
        ("80526", "Fort Collins", "Larimer", 7300, "NC1"),
        ("80534", "Johnstown",    "Weld",    3221, "NC1"),
        ("80535", "Laporte",      "Larimer", 386,  "NC1"),
        ("80536", "Livermore",    "Larimer", 356,  "NC1"),
        ("80537", "Loveland",     "Larimer", 5926, "NC1"),
        ("80538", "Loveland",     "Larimer", 7737, "NC1"),
        ("80542", "Mead",         "Weld",    1560, "NC1"),
        ("80543", "Milliken",     "Weld",    596,  "NC1"),
        # NC2
        ("80524", "Fort Collins", "Larimer", 6566,  "NC2"),
        ("80525", "Fort Collins", "Larimer", 10171, "NC2"),
        ("80528", "Fort Collins", "Larimer", 4895,  "NC2"),
        ("80547", "Timnath",      "Larimer", 2690,  "NC2"),
        ("80550", "Windsor",      "Weld",    9874,  "NC2"),
        ("80615", "Eaton",        "Weld",    1235,  "NC2"),
        ("80631", "Greeley",      "Weld",    316,   "NC2"),
        ("80634", "Greeley",      "Weld",    4476,  "NC2"),
    ],

    # ---- CO: ND (North Denver) — split into N1/N2 ----
    "ND": [
        # N1
        ("80301", "Boulder",       "Boulder",     3214, "N1"),
        ("80302", "Boulder",       "Boulder",     1168, "N1"),
        ("80304", "Boulder",       "Boulder",     3394, "N1"),
        ("80305", "Boulder",       "Boulder",     2224, "N1"),
        ("80002", "Arvada",        "Jefferson",   1053, "N1"),
        ("80004", "Arvada",        "Jefferson",   661,  "N1"),
        ("80005", "Arvada",        "Jefferson",   2962, "N1"),
        ("80007", "Arvada",        "Jefferson",   5406, "N1"),
        ("80020", "Broomfield",    "Broomfield",  2159, "N1"),
        ("80021", "Broomfield",    "Broomfield",  627,  "N1"),
        ("80027", "Louisville",    "Boulder",     6428, "N1"),
        ("80401", "Golden",        "Jefferson",   4141, "N1"),
        ("80403", "Golden",        "Jefferson",   4079, "N1"),
        ("80466", "Nederland",     "Boulder",     0,    "N1"),
        ("80501", "Longmont",      "Boulder",     0,    "N1"),
        ("80503", "Longmont",      "Boulder",     4602, "N1"),
        ("80504", "Longmont",      "Boulder",     3379, "N1"),
        ("80540", "Lyons",         "Boulder",     0,    "N1"),
        ("80238", "Denver",        "Denver",      4429, "N1"),
        # N2
        ("80514", "Dacono",        "Weld",        596,  "N2"),
        ("80530", "Frederick",     "Weld",        345,  "N2"),
        ("80022", "Commerce City", "Adams",       435,  "N2"),
        ("80023", "Westminster",   "Adams",       6251, "N2"),
        ("80026", "Lafayette",     "Boulder",     3819, "N2"),
        ("80031", "Westminster",   "Adams",       2500, "N2"),
        ("80205", "Denver",        "Denver",      300,  "N2"),
        ("80206", "Denver",        "Denver",      907,  "N2"),
        ("80207", "Denver",        "Denver",      1672, "N2"),
        ("80209", "Denver",        "Denver",      3548, "N2"),
        ("80218", "Denver",        "Denver",      488,  "N2"),
        ("80220", "Denver",        "Denver",      2504, "N2"),
        ("80221", "Denver",        "Denver",      590,  "N2"),
        ("80222", "Denver",        "Denver",      300,  "N2"),
        ("80224", "Denver",        "Denver",      1185, "N2"),
        ("80230", "Denver",        "Denver",      900,  "N2"),
        ("80231", "Denver",        "Denver",      300,  "N2"),
        ("80234", "Northglenn",    "Adams",       1243, "N2"),
        ("80237", "Denver",        "Denver",      1317, "N2"),
        ("80241", "Thornton",      "Adams",       610,  "N2"),
        ("80246", "Denver",        "Denver",      260,  "N2"),
        ("80303", "Boulder",       "Boulder",     2749, "N2"),
        ("80516", "Erie",          "Boulder",     8245, "N2"),
        ("80602", "Thornton",      "Adams",       8235, "N2"),
        ("80603", "Brighton",      "Adams",       775,  "N2"),
        ("80621", "Fort Lupton",   "Weld",        0,    "N2"),
        ("80642", "Hudson",        "Weld",        0,    "N2"),
    ],

    # ---- CO: SD (South Denver) — split into S1/S2 ----
    "SD": [
        # S1
        ("80033", "Wheat Ridge",      "Jefferson", 924,  "S1"),
        ("80120", "Littleton",        "Arapahoe",  2059, "S1"),
        ("80123", "Littleton",        "Arapahoe",  3004, "S1"),
        ("80125", "Littleton",        "Douglas",   3617, "S1"),
        ("80127", "Littleton",        "Jefferson", 5554, "S1"),
        ("80128", "Littleton",        "Jefferson", 2180, "S1"),
        ("80204", "Denver",           "Denver",    300,  "S1"),
        ("80210", "Denver",           "Denver",    3673, "S1"),
        ("80211", "Denver",           "Denver",    926,  "S1"),
        ("80212", "Denver",           "Denver",    1800, "S1"),
        ("80215", "Denver",           "Jefferson", 1395, "S1"),
        ("80223", "Denver",           "Denver",    0,    "S1"),
        ("80226", "Denver",           "Jefferson", 0,    "S1"),
        ("80227", "Denver",           "Jefferson", 1605, "S1"),
        ("80228", "Denver",           "Jefferson", 4090, "S1"),
        ("80232", "Lakewood",         "Jefferson", 0,    "S1"),
        ("80235", "Denver",           "Jefferson", 300,  "S1"),
        ("80236", "Denver",           "Denver",    0,    "S1"),
        ("80439", "Evergreen",        "Jefferson", 4960, "S1"),
        ("80465", "Morrison",         "Jefferson", 2582, "S1"),
        ("80470", "Pine",             "Jefferson", 553,  "S1"),
        ("80129", "Highlands Ranch",  "Douglas",   3513, "S1"),
        # S2
        ("80013", "Aurora",            "Arapahoe", 600,   "S2"),
        ("80014", "Aurora",            "Arapahoe", 0,     "S2"),
        ("80015", "Centennial",        "Arapahoe", 3186,  "S2"),
        ("80016", "Aurora",            "Arapahoe", 13536, "S2"),
        ("80018", "Aurora",            "Arapahoe", 381,   "S2"),
        ("80111", "Greenwood Village", "Arapahoe", 4852,  "S2"),
        ("80112", "Centennial",        "Arapahoe", 2043,  "S2"),
        ("80113", "Englewood",         "Arapahoe", 646,   "S2"),
        ("80121", "Littleton",         "Arapahoe", 294,   "S2"),
        ("80122", "Littleton",         "Arapahoe", 2654,  "S2"),
        ("80124", "Lone Tree",         "Douglas",  2937,  "S2"),
        ("80126", "Highlands Ranch",   "Douglas",  8263,  "S2"),
        ("80130", "Highlands Ranch",   "Douglas",  4248,  "S2"),
        ("80104", "Castle Rock",       "Douglas",  4261,  "S2"),
        ("80107", "Elizabeth",         "Elbert",   2039,  "S2"),
        ("80108", "Castle Pines",      "Douglas",  8824,  "S2"),
        ("80109", "Castle Rock",       "Douglas",  3197,  "S2"),
        ("80116", "Franktown",         "Douglas",  1315,  "S2"),
        ("80118", "Larkspur",          "Douglas",  2004,  "S2"),
        ("80134", "Parker",            "Douglas",  13090, "S2"),
        ("80135", "Sedalia",           "Douglas",  622,   "S2"),
        ("80138", "Parker",            "Douglas",  6271,  "S2"),
        ("80433", "Conifer",           "Jefferson", 1702, "S2"),
    ],

    # ---- CO: EPC (El Paso County) — split into E1/E2 ----
    "EPC": [
        # E1
        ("80106", "Elbert",           "Elbert",   871,  "E1"),
        ("80132", "Monument",         "El Paso",  8175, "E1"),
        ("80831", "Peyton",           "El Paso",  6058, "E1"),
        ("80908", "Colorado Springs", "El Paso",  6952, "E1"),
        ("80917", "Colorado Springs", "El Paso",  1606, "E1"),
        ("80921", "Colorado Springs", "El Paso",  6012, "E1"),
        ("80923", "Colorado Springs", "El Paso",  4486, "E1"),
        ("80924", "Colorado Springs", "El Paso",  5055, "E1"),
        # E2
        ("80927", "Colorado Springs", "El Paso", 2914, "E2"),
        ("80829", "Manitou Springs",  "El Paso", 1029, "E2"),
        ("80809", "Cascade",          "El Paso", 0,    "E2"),
        ("80817", "Fountain",         "El Paso", 477,  "E2"),
        ("80903", "Colorado Springs", "El Paso", 0,    "E2"),
        ("80904", "Colorado Springs", "El Paso", 1715, "E2"),
        ("80905", "Colorado Springs", "El Paso", 1089, "E2"),
        ("80906", "Colorado Springs", "El Paso", 4474, "E2"),
        ("80907", "Colorado Springs", "El Paso", 865,  "E2"),
        ("80909", "Colorado Springs", "El Paso", 1622, "E2"),
        ("80910", "Colorado Springs", "El Paso", 0,    "E2"),
        ("80911", "Colorado Springs", "El Paso", 588,  "E2"),
        ("80915", "Colorado Springs", "El Paso", 312,  "E2"),
        ("80916", "Colorado Springs", "El Paso", 0,    "E2"),
        ("80918", "Colorado Springs", "El Paso", 4874, "E2"),
        ("80919", "Colorado Springs", "El Paso", 5667, "E2"),
        ("80920", "Colorado Springs", "El Paso", 6427, "E2"),
        ("80922", "Colorado Springs", "El Paso", 4303, "E2"),
        ("80925", "Colorado Springs", "El Paso", 4429, "E2"),
        ("80926", "Colorado Springs", "El Paso", 0,    "E2"),
        ("80951", "Colorado Springs", "El Paso", 0,    "E2"),
    ],

    # ---- UT: NW (North Wasatch) ----
    "NW": [
        # NORTH 1
        ("84010", "Bountiful",       "Davis", None, "NORTH 1"),
        ("84014", "Centerville",     "Davis", None, "NORTH 1"),
        ("84025", "Farmington",      "Davis", None, "NORTH 1"),
        ("84037", "Kaysville",       "Davis", None, "NORTH 1"),
        ("84040", "Layton",          "Davis", None, "NORTH 1"),
        ("84054", "North Salt Lake", "Davis", None, "NORTH 1"),
        ("84087", "Wood Cross",      "Davis", None, "NORTH 1"),
        ("84403", "Ogden",           "Weber", None, "NORTH 1"),
        ("84405", "Ogden",           "Weber", None, "NORTH 1"),
        # NORTH 2
        ("84015", "Clearfield", "Davis", None, "NORTH 2"),
        ("84041", "Layton",     "Davis", None, "NORTH 2"),
        ("84067", "Roy",        "Weber", None, "NORTH 2"),
        ("84075", "Syracuse",   "Davis", None, "NORTH 2"),
        ("84315", "Hooper",     "Weber", None, "NORTH 2"),
        ("84401", "Ogden",      "Weber", None, "NORTH 2"),
        ("84404", "Ogden",      "Weber", None, "NORTH 2"),
        ("84414", "Ogden",      "Weber", None, "NORTH 2"),
    ],

    # ---- UT: CW (Central Wasatch) ----
    "CW": [
        # CENTRAL 1
        ("84060", "Park City",      "Summit",     None, "CENTRAL 1"),
        ("84081", "West Jordan",    "Salt Lake",  None, "CENTRAL 1"),
        ("84084", "West Jordan",    "Salt Lake",  None, "CENTRAL 1"),
        ("84088", "West Jordan",    "Salt Lake",  None, "CENTRAL 1"),
        ("84098", "Park City",      "Summit",     None, "CENTRAL 1"),
        ("84103", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84105", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84106", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84107", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84108", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84109", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84115", "South Salt Lake","Salt Lake",  None, "CENTRAL 1"),
        ("84117", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84123", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84124", "Salt Lake City", "Salt Lake",  None, "CENTRAL 1"),
        ("84129", "Taylorsville",   "Salt Lake",  None, "CENTRAL 1"),
        # CENTRAL 2
        ("84009", "South Jordan",   "Salt Lake", None, "CENTRAL 2"),
        ("84020", "Draper",         "Salt Lake", None, "CENTRAL 2"),
        ("84032", "Heber City",     "Wasatch",   None, "CENTRAL 2"),
        ("84047", "Midvale",        "Salt Lake", None, "CENTRAL 2"),
        ("84049", "Midway",         "Wasatch",   None, "CENTRAL 2"),
        ("84065", "Riverton",       "Salt Lake", None, "CENTRAL 2"),
        ("84070", "Sandy",          "Salt Lake", None, "CENTRAL 2"),
        ("84092", "Sandy",          "Salt Lake", None, "CENTRAL 2"),
        ("84093", "Sandy",          "Salt Lake", None, "CENTRAL 2"),
        ("84094", "Sandy",          "Salt Lake", None, "CENTRAL 2"),
        ("84095", "South Jordan",   "Salt Lake", None, "CENTRAL 2"),
        ("84096", "Riverton",       "Salt Lake", None, "CENTRAL 2"),
        ("84121", "Salt Lake City", "Salt Lake", None, "CENTRAL 2"),
    ],

    # ---- UT: SW (South Wasatch) ----
    "SW": [
        # SOUTH 1
        ("84003", "American Fork",     "Utah", None, "SOUTH 1"),
        ("84004", "Alpine",            "Utah", None, "SOUTH 1"),
        ("84005", "Eagle Mountain",    "Utah", None, "SOUTH 1"),
        ("84043", "Lehi",              "Utah", None, "SOUTH 1"),
        ("84045", "Saratoga Springs",  "Utah", None, "SOUTH 1"),
        ("84062", "Pleasant Grove",    "Utah", None, "SOUTH 1"),
        # SOUTH 2
        ("84042", "Lindon",       "Utah", None, "SOUTH 2"),
        ("84057", "Orem",         "Utah", None, "SOUTH 2"),
        ("84058", "Orem",         "Utah", None, "SOUTH 2"),
        ("84059", "Vineyard",     "Utah", None, "SOUTH 2"),
        ("84097", "Orem",         "Utah", None, "SOUTH 2"),
        ("84601", "Provo",        "Utah", None, "SOUTH 2"),
        ("84604", "Provo",        "Utah", None, "SOUTH 2"),
        ("84606", "Provo",        "Utah", None, "SOUTH 2"),
        ("84651", "Payson",       "Utah", None, "SOUTH 2"),
        ("84653", "Salem",        "Utah", None, "SOUTH 2"),
        ("84655", "Santaquin",    "Utah", None, "SOUTH 2"),
        ("84660", "Spanish Fork", "Utah", None, "SOUTH 2"),
        ("84663", "Springville",  "Utah", None, "SOUTH 2"),
        ("84664", "Mapleton",     "Utah", None, "SOUTH 2"),
    ],

    # ---- AU: AN (Austin North) ----
    "AN": [
        # NORTH 1
        ("78613", "Cedar Park",    "Williamson", None, "NORTH 1"),
        ("78626", "Georgetown",    "Williamson", None, "NORTH 1"),
        ("78628", "Georgetown",    "Williamson", None, "NORTH 1"),
        ("78633", "Georgetown",    "Williamson", None, "NORTH 1"),
        ("78641", "Leander",       "Williamson", None, "NORTH 1"),
        ("78642", "Liberty Hill",  "Williamson", None, "NORTH 1"),
        # NORTH 2
        ("78634", "Hutto",      "Williamson", None, "NORTH 2"),
        ("78664", "Round Rock", "Williamson", None, "NORTH 2"),
        ("78665", "Round Rock", "Williamson", None, "NORTH 2"),
        ("78681", "Round Rock", "Williamson", None, "NORTH 2"),
        ("78717", "Austin",     "Williamson", None, "NORTH 2"),
    ],

    # ---- AU: AS (Austin South) ----
    "AS": [
        # SOUTH 1
        ("78620", "Dripping Springs", "Hays",   None, "SOUTH 1"),
        ("78669", "Spicewood",        "Travis", None, "SOUTH 1"),
        ("78726", "Austin",           "Travis", None, "SOUTH 1"),
        ("78730", "Austin",           "Travis", None, "SOUTH 1"),
        ("78732", "Austin",           "Travis", None, "SOUTH 1"),
        ("78733", "Austin",           "Travis", None, "SOUTH 1"),
        ("78734", "Austin",           "Travis", None, "SOUTH 1"),
        ("78736", "Austin",           "Travis", None, "SOUTH 1"),
        ("78738", "The Hills",        "Travis", None, "SOUTH 1"),
        # SOUTH 2
        ("78610", "Buda",            "Hays",   None, "SOUTH 2"),
        ("78619", "Driftwood",       "Hays",   None, "SOUTH 2"),
        ("78652", "Manchaca",        "Travis", None, "SOUTH 2"),
        ("78676", "Wimberley",       "Hays",   None, "SOUTH 2"),
        ("78702", "Austin",          "Travis", None, "SOUTH 2"),
        ("78703", "Austin",          "Travis", None, "SOUTH 2"),
        ("78704", "Austin",          "Travis", None, "SOUTH 2"),
        ("78705", "Austin",          "Travis", None, "SOUTH 2"),
        ("78722", "Austin",          "Travis", None, "SOUTH 2"),
        ("78723", "Austin",          "Travis", None, "SOUTH 2"),
        ("78731", "Austin",          "Travis", None, "SOUTH 2"),
        ("78735", "Austin",          "Travis", None, "SOUTH 2"),
        ("78737", "Austin",          "Hays",   None, "SOUTH 2"),
        ("78739", "Austin",          "Travis", None, "SOUTH 2"),
        ("78741", "Austin",          "Travis", None, "SOUTH 2"),
        ("78746", "West Lake Hills", "Travis", None, "SOUTH 2"),
        ("78750", "Austin",          "Travis", None, "SOUTH 2"),
        ("78751", "Austin",          "Travis", None, "SOUTH 2"),
        ("78756", "Austin",          "Travis", None, "SOUTH 2"),
        ("78757", "Austin",          "Travis", None, "SOUTH 2"),
        ("78759", "Austin",          "Travis", None, "SOUTH 2"),
    ],

    # ---- SA: SAW (San Antonio West) ----
    "SAW": [
        # WEST 1
        ("78006", "San Antonio", "Bexar", None, "WEST 1"),
        ("78015", "San Antonio", "Bexar", None, "WEST 1"),
        ("78255", "San Antonio", "Bexar", None, "WEST 1"),
        ("78256", "San Antonio", "Bexar", None, "WEST 1"),
        ("78257", "San Antonio", "Bexar", None, "WEST 1"),
        ("78004", "San Antonio", "Bexar", None, "WEST 1"),
        ("78023", "San Antonio", "Bexar", None, "WEST 1"),
        # WEST 2
        ("78201", "San Antonio", "Bexar", None, "WEST 2"),
        ("78207", "San Antonio", "Bexar", None, "WEST 2"),
        ("78212", "San Antonio", "Bexar", None, "WEST 2"),
        ("78213", "San Antonio", "Bexar", None, "WEST 2"),
        ("78227", "San Antonio", "Bexar", None, "WEST 2"),
        ("78228", "San Antonio", "Bexar", None, "WEST 2"),
        ("78229", "San Antonio", "Bexar", None, "WEST 2"),
        ("78230", "San Antonio", "Bexar", None, "WEST 2"),
        ("78231", "San Antonio", "Bexar", None, "WEST 2"),
        ("78232", "San Antonio", "Bexar", None, "WEST 2"),
        ("78237", "San Antonio", "Bexar", None, "WEST 2"),
        ("78238", "San Antonio", "Bexar", None, "WEST 2"),
        ("78240", "San Antonio", "Bexar", None, "WEST 2"),
        ("78248", "San Antonio", "Bexar", None, "WEST 2"),
        ("78251", "San Antonio", "Bexar", None, "WEST 2"),
        ("78253", "San Antonio", "Bexar", None, "WEST 2"),
        ("78254", "San Antonio", "Bexar", None, "WEST 2"),
        ("78249", "San Antonio", "Bexar", None, "WEST 2"),
        ("78245", "San Antonio", "Bexar", None, "WEST 2"),
    ],

    # ---- SA: SAE (San Antonio East) ----
    "SAE": [
        # EAST 1
        ("78070", "Spring Branch", "Comal", None, "EAST 1"),
        ("78130", "New Braunfels", "Comal", None, "EAST 1"),
        ("78132", "New Braunfels", "Comal", None, "EAST 1"),
        ("78133", "Canyon Lake",   "Comal", None, "EAST 1"),
        ("78163", "Bulverde",      "Comal", None, "EAST 1"),
        ("78260", "San Antonio",   "Bexar", None, "EAST 1"),
        # EAST 2
        ("78108", "Cibolo",        "Guadalupe", None, "EAST 2"),
        ("78148", "Universal City","Bexar",     None, "EAST 2"),
        ("78154", "Schertz",       "Guadalupe", None, "EAST 2"),
        ("78208", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78209", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78215", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78216", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78217", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78218", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78219", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78234", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78244", "Converse",      "Bexar",     None, "EAST 2"),
        ("78247", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78258", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78259", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78261", "San Antonio",   "Bexar",     None, "EAST 2"),
        ("78266", "San Antonio",   "Comal",     None, "EAST 2"),
        ("78123", "McQueeney",     "Guadalupe", None, "EAST 2"),
        ("78124", "Marion",        "Guadalupe", None, "EAST 2"),
    ],
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    zones = sb.table("zones").select("id,abbreviation").execute().data
    abbr_to_id = {z["abbreviation"]: z["id"] for z in zones}

    rows = []
    for zone_abbr, zip_data in DATA.items():
        zone_id = abbr_to_id.get(zone_abbr)
        if not zone_id:
            print(f"  WARNING: zone {zone_abbr} not found in DB")
            continue
        for zip_code, city, county, dist_count, subzone in zip_data:
            rows.append({
                "zone_id": zone_id,
                "zip_code": zip_code,
                "city": city,
                "county": county,
                "distribution_count": dist_count,
                "off_page_subzone": subzone,
            })

    print(f"\n{len(rows)} zip rows to upsert")
    by_zone = {}
    for r in rows:
        by_zone.setdefault(r["zone_id"], 0)
        by_zone[r["zone_id"]] += 1
    abbr_by_id = {v: k for k, v in abbr_to_id.items()}
    for zid, n in sorted(by_zone.items()):
        print(f"  {abbr_by_id.get(zid, zid)}: {n} zips")

    if args.dry_run:
        print("\n--dry-run: not writing")
        return

    BATCH = 100
    written = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        sb.table("zone_zip_codes").upsert(batch, on_conflict="zone_id,zip_code").execute()
        written += len(batch)
    print(f"\n  Upserted {written} rows")


if __name__ == "__main__":
    main()
