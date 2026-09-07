"""One-time (idempotent) upgrade of the Career Command Center template:
- adds automation fields (ATS resolution, Track, proper dates/relations)
- adds missing select options
- creates the Metrics DB + Daily Digest / System Health pages
- writes generated IDs to config/notion_ids.yaml
Run: .venv/bin/python -m scripts.upgrade_notion_schema
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import ROOT, settings  # noqa: E402
from core import notion_store as ns  # noqa: E402

DBS = settings()["notion"]["databases"]
PAGE = settings()["notion"]["command_center_page"]


def merge_select_options(db: dict, prop: str, new_options: list[str]) -> dict | None:
    existing = db["properties"].get(prop)
    if not existing or existing["type"] != "select":
        return None
    current = [o["name"] for o in existing["select"]["options"]]
    merged = existing["select"]["options"] + [
        {"name": o} for o in new_options if o not in current
    ]
    if len(merged) == len(current):
        return None
    return {"select": {"options": merged}}


def ensure_props(db_id: str, wanted: dict):
    """Add properties that don't exist yet."""
    db = ns.get_database(db_id)
    to_add = {k: v for k, v in wanted.items() if k not in db["properties"]}
    if to_add:
        ns.update_database(db_id, properties=to_add)
        print(f"  + added {list(to_add)}")


def main():
    ids = {}

    print("Opportunities…")
    opp = ns.get_database(DBS["opportunities"])
    props = {}
    for prop, opts in {
        "Status": ["Discovered", "Shortlisted", "Screened Out", "Offer", "Ghosted", "Closed", "Withdrawn"],
        "Source": ["Greenhouse", "Lever", "Ashby", "Workday", "Careers Page", "Aggregator", "Manual"],
        "Work Mode": ["Remote"],
    }.items():
        merged = merge_select_options(opp, prop, opts)
        if merged:
            props[prop] = merged
    if props:
        ns.update_database(DBS["opportunities"], properties=props)
        print(f"  + extended select options: {list(props)}")
    ensure_props(DBS["opportunities"], {
        "Track": {"select": {"options": [{"name": n} for n in (
            "Software Engineering", "Product Management", "Quantitative Finance",
            "Investment Banking", "FinTech", "Data / ML", "Other")]}},
        "Industry": {"rollup": {"relation_property_name": "Company", "rollup_property_name": "Industry", "function": "show_original"}},
    })

    print("Companies…")
    ensure_props(DBS["companies"], {
        "ATS Type": {"select": {"options": [{"name": n} for n in (
            "greenhouse", "lever", "ashby", "workday", "manual")]}},
        "ATS Endpoint": {"url": {}},
        "Resolution Status": {"select": {"options": [{"name": n} for n in (
            "Pending", "Resolved", "Needs Manual Recipe", "Error")]}},
        "Paused": {"checkbox": {}},
    })

    print("Networking_CRM…")
    crm = ns.get_database(DBS["crm"])
    crm_follow, crm_last = "Next Follow-Up Date", "Last Contact Date"
    needs_retype = (
        crm["properties"].get(crm_follow, {}).get("type") != "date"
        or crm["properties"].get(crm_last, {}).get("type") != "date"
    )
    if needs_retype:
        try:
            ns.update_database(DBS["crm"], properties={crm_follow: {"date": {}}, crm_last: {"date": {}}})
            print("  ~ retyped follow-up fields to date")
        except Exception as e:
            print(f"  ! retype failed ({e}); adding new date fields")
            crm_follow, crm_last = "Next Follow-Up", "Last Contacted"
            ensure_props(DBS["crm"], {crm_follow: {"date": {}}, crm_last: {"date": {}}})
    else:
        print("  = follow-up fields already dates")
    ids["crm_followup_prop"] = crm_follow
    ids["crm_lastcontact_prop"] = crm_last
    ensure_props(DBS["crm"], {
        "Cadence (days)": {"number": {"format": "number"}},
        "Company Link": {"relation": {"database_id": DBS["companies"], "single_property": {}}},
        "Industry": {"rollup": {"relation_property_name": "Company Link", "rollup_property_name": "Industry", "function": "show_original"}},
    })

    print("Applications…")
    ensure_props(DBS["applications"], {
        "Opportunity": {"relation": {"database_id": DBS["opportunities"], "single_property": {}}},
        "Applied On": {"date": {}},
        "Next Action Due": {"date": {}},
        # Keeps the Applications tracker groupable by the same industry as Companies.
        "Industry": {"rollup": {"relation_property_name": "Opportunity", "rollup_property_name": "Industry", "function": "show_original"}},
    })

    print("Interviews…")
    ensure_props(DBS["interviews"], {
        "Application": {"relation": {"database_id": DBS["applications"], "single_property": {}}},
        "Scheduled For": {"date": {}},
    })

    print("Metrics DB…")
    matches = [r for r in ns.search("Pipeline Metrics", "database")
               if "".join(t["plain_text"] for t in r.get("title", [])) == "Pipeline Metrics"]
    if matches:
        ids["metrics_db"] = matches[0]["id"]
        print("  = already exists")
    else:
        db = ns.create_database(PAGE, "Pipeline Metrics", {
            "Week": {"title": {}},
            "Week Start": {"date": {}},
            "Discovered": {"number": {}}, "Shortlisted": {"number": {}},
            "Applied": {"number": {}}, "Responses": {"number": {}},
            "Interviews": {"number": {}}, "Offers": {"number": {}},
            "Response Rate": {"number": {"format": "percent"}},
            "Interview Rate": {"number": {"format": "percent"}},
            "Offer Rate": {"number": {"format": "percent"}},
            "Summary": {"rich_text": {}},
        })
        ids["metrics_db"] = db["id"]
        print("  + created")

    for key, title in (("digest_page", "Daily Digest"), ("health_page", "System Health")):
        match = None
        for r in ns.search(title, "page"):
            for p in r.get("properties", {}).values():
                if p.get("type") == "title" and "".join(x["plain_text"] for x in p["title"]) == title:
                    match = r
        if match:
            ids[key] = match["id"]
            print(f"{title}: = already exists")
        else:
            page = ns.create_page(PAGE, title)
            ids[key] = page["id"]
            print(f"{title}: + created")

    out = ROOT / settings()["notion"]["generated_ids_file"]
    out.write_text(yaml.safe_dump(ids))
    print(f"\nWrote {out}:\n{yaml.safe_dump(ids)}")


if __name__ == "__main__":
    main()
