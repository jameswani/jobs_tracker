"""Status hygiene for Opportunities/Applications. Deliberately observe-only:
this agent flags stale applications for a human to triage rather than
transitioning Status itself, since a wrong auto-transition (e.g. marking
something Ghosted that actually got a verbal offer) is hard to notice and
annoying to undo.
"""
from __future__ import annotations

import re
from datetime import date

from core.local_store import RunLedger
from core.config import settings
from core.notion_store import db_id, get_open_opportunities, plain, query_database, rt, update_page

_FLAG_MARKER = "[tracking:possible-ghost]"


def _looks_applied(status_text: str) -> bool:
    """True once an Applications row has moved past the default 'preparing'
    state. Only one live Status option ('Preparing') exists in this workspace
    today, so we can't hardcode the full emoji-prefixed option set — normalize
    instead of matching exact strings."""
    norm = re.sub(r"[^a-z]", "", (status_text or "").lower())
    if not norm:
        return False
    return "preparing" not in norm


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _opportunity_company_role(role_title: str) -> tuple[str, str]:
    """Opportunities' Company property is a relation (not readable via plain()
    without another API call); create_opportunity() already bakes the company
    name into Role as 'Company — Title', so parse it back out from there."""
    if " — " in role_title:
        company, _, title = role_title.partition(" — ")
        return company, title
    return "", role_title


def _flag_application(app_id: str, current_notes: str, message: str) -> None:
    if _FLAG_MARKER in current_notes:
        return
    new_notes = (current_notes + "\n" if current_notes else "") + f"{_FLAG_MARKER} {message}"
    try:
        update_page(app_id, {"Notes": rt(new_notes)})
    except Exception:
        pass  # best-effort — a failed flag write shouldn't break the run


def run() -> dict:
    with RunLedger("tracking") as ledger:
        cfg = settings()["tracking"]
        ghosted_after_days = cfg["ghosted_after_days"]
        today = date.today()

        opportunities = get_open_opportunities()
        applications = query_database(db_id("applications"))
        interviews = query_database(db_id("interviews"))

        linked_application_ids = {
            r["id"]
            for iv in interviews
            for r in iv["properties"].get("Application", {}).get("relation", [])
        }

        applied_opportunities_without_application_row = []
        for opp in opportunities:
            p = opp["properties"]
            if plain(p.get("Status", {})) != "Applied":
                continue
            role_title = plain(p.get("Role", {})) or ""
            opp_company, opp_title = _opportunity_company_role(role_title)
            matched = any(
                (opp_company and opp_company.lower() in plain(a["properties"].get("Company", {})).lower())
                or (plain(a["properties"].get("Company", {})).lower() and
                    plain(a["properties"].get("Company", {})).lower() in opp_company.lower())
                for a in applications
            ) if opp_company else False
            if not matched:
                # Informational only, per spec — never auto-create an Applications row.
                applied_opportunities_without_application_row.append({
                    "opportunity_id": opp["id"],
                    "role": role_title,
                })

        needs_attention = []
        checked = 0
        for app in applications:
            checked += 1
            p = app["properties"]
            status_text = plain(p.get("Status", {}))
            if not _looks_applied(status_text):
                continue

            applied_on = _parse_date(plain(p.get("Applied On", {}))) or _parse_date(plain(p.get("Date Applied", {})))
            if not applied_on:
                continue

            days_since = (today - applied_on).days
            if days_since <= ghosted_after_days:
                continue

            thanked = bool(plain(p.get("Thank You / Follow-Up Sent", {})))
            has_interview = app["id"] in linked_application_ids
            if thanked or has_interview:
                continue

            description = {
                "application_id": app["id"],
                "title": plain(p.get("Application ID", {})) or "",
                "company": plain(p.get("Company", {})) or "",
                "role": plain(p.get("Role Title", {})) or "",
                "status": status_text,
                "days_since_applied": days_since,
                "reason": f"Applied {days_since}d ago, no thank-you/follow-up logged, no interview linked",
            }
            needs_attention.append(description)
            _flag_application(
                app["id"],
                plain(p.get("Notes", {})) or "",
                f"{today.isoformat()} — no response {days_since}d after applying, no interview logged.",
            )

        ledger.items = checked
        return {
            "checked": checked,
            "opportunities_checked": len(opportunities),
            "needs_attention": needs_attention,
            "opportunities_applied_without_application_row": applied_opportunities_without_application_row,
        }


if __name__ == "__main__":
    result = run()
    print(f"Checked {result['checked']} applications ({result['opportunities_checked']} open opportunities).")
    if result["needs_attention"]:
        print(f"{len(result['needs_attention'])} application(s) need attention:")
        for item in result["needs_attention"]:
            label = item["title"] or f"{item['company']} / {item['role']}"
            print(f"  - {label}: {item['reason']}")
    else:
        print("Nothing needs attention.")
    if result["opportunities_applied_without_application_row"]:
        print(f"({len(result['opportunities_applied_without_application_row'])} 'Applied' opportunities have no matching Applications row — informational only)")
