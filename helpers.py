from config import supabase


# Product prefix -> zone abbreviation mapping for order-level zone assignment
PRODUCT_TO_ZONE = {
    # Colorado print
    "EPC": "EPC", "NOCO": "NOCO", "NORTH DENVER": "ND", "SOUTH DENVER": "SD",
    # Utah print
    "SNORTH": "NW", "SCTRL": "CW", "SSOUTH": "SW",
    # Austin print
    "AU North": "AN", "AU South": "AS",
    # San Antonio print
    "SA East": "SAE", "SA West": "SAW",
}

# IA (Inbox Advantage) zone name fragment -> zone abbreviation
IA_TO_ZONE = {
    "CO Springs": "EPC", "Denver N": "ND", "Denver S": "SD", "Northern CO": "NOCO",
    "Wasatch N": "NW", "Wasatch C": "CW", "Wasatch S": "SW",
    "Austin N": "AN", "Austin S": "AS",
    "San Antonio E": "SAE", "San Antonio W": "SAW",
}


def get_or_create_client(official_name: str) -> dict:
    """Look up a client by OfficialName. Create if not found. Returns the client row."""
    result = supabase.table("clients").select("*").eq("name", official_name).execute()
    if result.data:
        return result.data[0]
    insert = supabase.table("clients").insert({"name": official_name}).execute()
    return insert.data[0]


def get_market(market_code: str) -> dict | None:
    """Look up a market by code (CO, UT, AU, SA). Returns the market row or None."""
    result = supabase.table("markets").select("*").eq("code", market_code).execute()
    return result.data[0] if result.data else None


def get_zone(abbreviation: str) -> dict | None:
    """Look up a zone by abbreviation (NOCO, ND, SD, etc.). Returns the zone row or None."""
    result = supabase.table("zones").select("*").eq("abbreviation", abbreviation).execute()
    return result.data[0] if result.data else None


def parse_zone_from_product(product: str) -> str | None:
    """Parse a product string and return the zone abbreviation, or None for market-level products."""
    if not product:
        return None
    # Skip market-level products
    if any(kw in product for kw in ("Marketplace", "Sweepstakes", "Metro", "CROSS", "Cross Out", "SCROSS")):
        return None
    if product in ("Dallas", "Fort Worth", "Houston"):
        return None
    if "THM DAL" in product:
        return None
    # Check IA products first (they contain zone names as substrings)
    if product.startswith("IA"):
        for fragment, abbrev in IA_TO_ZONE.items():
            if fragment in product:
                return abbrev
        return None
    # Check print product prefixes
    for prefix, abbrev in PRODUCT_TO_ZONE.items():
        if product.startswith(prefix):
            return abbrev
    return None


def link_client_zone(client_id: str, zone_id: str) -> dict:
    """Link a client to a zone (idempotent)."""
    result = (
        supabase.table("client_zones")
        .select("*")
        .eq("client_id", client_id)
        .eq("zone_id", zone_id)
        .execute()
    )
    if result.data:
        return result.data[0]
    insert = (
        supabase.table("client_zones")
        .insert({"client_id": client_id, "zone_id": zone_id})
        .execute()
    )
    return insert.data[0]


def upsert_platform_id(client_id: str, platform: str, platform_guid: str) -> dict:
    """Insert or update a platform ID for a client."""
    result = (
        supabase.table("client_platform_ids")
        .upsert(
            {
                "client_id": client_id,
                "platform": platform,
                "platform_guid": platform_guid,
            },
            on_conflict="platform_guid",
        )
        .execute()
    )
    return result.data[0]
