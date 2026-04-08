from config import supabase


def get_or_create_client(official_name: str) -> dict:
    """Look up a client by OfficialName. Create if not found. Returns the client row."""
    result = supabase.table("clients").select("*").eq("name", official_name).execute()
    if result.data:
        return result.data[0]
    # Create new client
    insert = supabase.table("clients").insert({"name": official_name}).execute()
    return insert.data[0]


def get_or_create_zone(zone_code: str, zone_names: dict = None) -> dict:
    """Look up a zone by code. Create if not found. Returns the zone row."""
    if zone_names is None:
        zone_names = {
            "CO": "Colorado",
            "UT": "Utah",
            "AU": "Austin",
            "SA": "San Antonio",
            "XX": "Cross-Market",
        }
    result = supabase.table("zones").select("*").eq("code", zone_code).execute()
    if result.data:
        return result.data[0]
    name = zone_names.get(zone_code, zone_code)
    insert = supabase.table("zones").insert({"code": zone_code, "name": name}).execute()
    return insert.data[0]


def link_client_zone(client_id: str, zone_id: str) -> dict:
    """Link a client to a zone (idempotent via upsert)."""
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
