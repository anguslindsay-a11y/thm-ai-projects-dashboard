"""
Phase 4 — Build Excel review report for low-confidence + disagreement-flagged
classification results.

Three sheets:
  1. Disagreements: legacy primary != LLM primary (highest priority — RW-style cases)
  2. Low Confidence (<0.70): clients where LLM hedged
  3. Medium Confidence (0.70-0.85): spot-check candidates

Each row has the client name, evidence summary, top tags with confidence + reasoning,
and an "Approved" column for the user to mark decisions. The companion script
setup/import_category_approvals.py applies approved values back to client_categories.

Usage:
  python scripts/build_category_review.py
"""
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from scripts.analyze import to_xlsx

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")


def parse_legacy_primary(legacy_text: str | None, alias_to_name: dict[str, str]) -> str | None:
    """Parse the first matched alias from the legacy text to get the primary legacy category name.
    Mirrors longest-match-first logic used in setup/migrate_categories.py."""
    if not legacy_text or not legacy_text.strip():
        return None
    remaining = legacy_text.strip()
    sorted_aliases = sorted(alias_to_name.keys(), key=len, reverse=True)
    while remaining:
        remaining = remaining.lstrip(", ").strip()
        if not remaining:
            break
        for alias in sorted_aliases:
            if remaining.startswith(alias):
                tail = remaining[len(alias):].lstrip()
                if not tail or tail.startswith(","):
                    return alias_to_name[alias]  # first match = primary
        # Fall back: skip first comma-fragment
        if "," in remaining:
            _, _, remaining = remaining.partition(",")
        else:
            return None
    return None


def build_path_lookup(sb) -> dict[str, str]:
    """Return {category_id: 'Group > Category > Subcategory'} display string."""
    rows = sb.table("categories").select("id,name,parent_id,level").execute().data
    by_id = {r["id"]: r for r in rows}

    def path_for(cid: str) -> str:
        node = by_id.get(cid)
        if not node:
            return ""
        chain = [node["name"]]
        cur = node
        while cur.get("parent_id"):
            cur = by_id.get(cur["parent_id"])
            if not cur:
                break
            chain.append(cur["name"])
        return " > ".join(reversed(chain))

    return {cid: path_for(cid) for cid in by_id}


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # 1) Pull all client_categories with their joined info
    print("Loading classification state...")

    # Build alias_text -> category_name map for legacy parsing
    alias_rows = sb.table("category_aliases").select("alias,categories(name)").execute().data
    alias_to_name = {a["alias"]: (a.get("categories") or {}).get("name")
                     for a in alias_rows if (a.get("categories") or {}).get("name")}

    # Build path lookup so each tag shows full hierarchy
    path_lookup = build_path_lookup(sb)

    # Use views/joins via SQL via PostgREST — easier with raw client.
    # Pull llm_auto rows + legacy_text in two queries, build client maps.
    page = 0
    rows = []
    while True:
        chunk = (sb.table("client_categories")
                 .select("client_id,category_id,is_primary,source,confidence,reasoning,categories(name,slug,level)")
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
    print(f"  {len(rows)} total client_categories rows")

    # Pull clients (name + status)
    clients_map: dict[str, dict] = {}
    page = 0
    while True:
        chunk = (sb.table("clients").select("id,name,status,category,is_mapping_stub")
                 .eq("is_mapping_stub", False)
                 .range(page * 1000, page * 1000 + 999).execute().data)
        if not chunk:
            break
        for c in chunk:
            clients_map[c["id"]] = c
        if len(chunk) < 1000:
            break
        page += 1
    print(f"  {len(clients_map)} real clients")

    # Build per-client structure
    by_client: dict[str, dict] = {}
    for r in rows:
        cid = r["client_id"]
        if cid not in clients_map:
            continue
        if cid not in by_client:
            legacy_text = clients_map[cid].get("category")
            by_client[cid] = {
                "name": clients_map[cid]["name"],
                "status": clients_map[cid]["status"],
                "legacy_text": legacy_text,
                "llm": [], "legacy": [], "manual": [],
                "primary_llm": None,
                "primary_legacy": parse_legacy_primary(legacy_text, alias_to_name),
            }
        cat_name = (r.get("categories") or {}).get("name") if isinstance(r.get("categories"), dict) else None
        cat_slug = (r.get("categories") or {}).get("slug") if isinstance(r.get("categories"), dict) else None
        cat_level = (r.get("categories") or {}).get("level") if isinstance(r.get("categories"), dict) else None
        path = path_lookup.get(r["category_id"], cat_name or "")
        item = {
            "name": cat_name, "slug": cat_slug, "level": cat_level, "path": path,
            "is_primary": r["is_primary"],
            "confidence": r.get("confidence"), "reasoning": r.get("reasoning"),
        }
        if r["source"] == "llm_auto":
            by_client[cid]["llm"].append(item)
            if r["is_primary"]:
                by_client[cid]["primary_llm_path"] = path  # full path for display
                by_client[cid]["primary_llm"] = cat_name   # bare name for disagreement compare
        elif r["source"] == "legacy_text":
            by_client[cid]["legacy"].append(item)
            # primary_legacy already derived from clients.category text above
        elif r["source"] == "manual":
            by_client[cid]["manual"].append(item)

    # Build review rows by category
    disagreements = []
    low_conf = []
    med_conf = []

    for cid, data in by_client.items():
        if data["manual"]:
            continue  # already reviewed manually
        if not data["llm"]:
            continue  # not classified yet
        primary_llm_row = next((t for t in data["llm"] if t["is_primary"]), None)
        if not primary_llm_row:
            continue

        all_tag_str = " | ".join(
            f"{t['path']} ({float(t['confidence']):.2f})"
            for t in sorted(data["llm"], key=lambda x: -float(x["confidence"] or 0))
        )

        base_row = {
            "client": data["name"],
            "status": data["status"],
            "llm_primary": data.get("primary_llm_path") or data["primary_llm"],
            "llm_all_tags": all_tag_str,
            "legacy_primary": data["primary_legacy"],
            "legacy_text_raw": data["legacy_text"],
            "primary_confidence": float(primary_llm_row["confidence"] or 0),
            "reasoning": (primary_llm_row.get("reasoning") or "")[:400],
            "approved_primary": "",  # blank for user to fill
            "approved_secondaries": "",
            "notes": "",
        }

        # Disagreement: LLM primary != legacy primary, AND there was a legacy primary
        if data["primary_legacy"] and data["primary_llm"] != data["primary_legacy"]:
            disagreements.append(base_row)
            continue

        conf = base_row["primary_confidence"]
        if conf < 0.70:
            low_conf.append(base_row)
        elif conf < 0.85:
            med_conf.append(base_row)

    # Sort within each
    disagreements.sort(key=lambda r: (r["status"] != "active", r["client"]))
    low_conf.sort(key=lambda r: (r["primary_confidence"], r["client"]))
    med_conf.sort(key=lambda r: (r["primary_confidence"], r["client"]))

    # Summary tab
    summary = [
        {"category": "Disagreements (LLM primary ≠ legacy primary)", "count": len(disagreements),
         "action": "Highest priority — likely RW-style miscategorizations to confirm/correct"},
        {"category": "Low confidence (<0.70)", "count": len(low_conf),
         "action": "LLM hedged — needs human eyes"},
        {"category": "Medium confidence (0.70 - 0.85)", "count": len(med_conf),
         "action": "Spot-check; mostly correct but verify"},
        {"category": "Total review queue", "count": len(disagreements) + len(low_conf) + len(med_conf), "action": ""},
    ]

    print(f"\nDisagreements: {len(disagreements)}")
    print(f"Low confidence: {len(low_conf)}")
    print(f"Medium confidence: {len(med_conf)}")
    print(f"Total review queue: {len(disagreements) + len(low_conf) + len(med_conf)}")

    from datetime import datetime as _dt
    stamp = _dt.now().strftime("%Y-%m-%d %H%M")
    out_path = to_xlsx(
        f"Category Review {stamp}",
        sheets={
            "Summary": summary,
            "1. Disagreements": disagreements,
            "2. Low Confidence": low_conf,
            "3. Medium Confidence": med_conf,
        },
    )
    print(f"\nWrote: {out_path}")
    print("\nFor each row in tabs 1-3, fill the 'approved_primary' column with the correct category name (or 'OK' to confirm the LLM choice).")
    print("Use 'approved_secondaries' for additional tags (comma-separated category names) if needed.")
    print("Then run: python setup/import_category_approvals.py output/[C]\\ Category\\ Review\\ ...xlsx")


if __name__ == "__main__":
    main()
