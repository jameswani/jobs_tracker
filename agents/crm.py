"""Networking follow-up reminders. Read-only: surfaces who's due for outreach
so the daily-digest orchestrator can list it — never messages anyone or
writes back to Notion itself.
"""
from __future__ import annotations

from datetime import date, timedelta

from core.config import notion_ids, settings
from core.local_store import RunLedger
from core.notion_store import get_contacts, plain


def _parse_date(text: str) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None

def due_contacts() -> list[dict]:
    ids = notion_ids()
    followup_prop = ids.get("crm_followup_prop") or "Next Follow-Up Date"
    lastcontact_prop = ids.get("crm_lastcontact_prop") or "Last Contact Date"
    default_cadence = settings()["crm"]["default_cadence_days"]
    today = date.today()

    due = []
    for contact in get_contacts():
        p = contact["properties"]
        name = plain(p.get("Full Name", {})) or "(unnamed contact)"
        company = plain(p.get("Company", {})) or ""
        next_followup = _parse_date(plain(p.get(followup_prop, {})))
        last_contact = _parse_date(plain(p.get(lastcontact_prop, {})))
        cadence_raw = plain(p.get("Cadence (days)", {}))
        cadence = int(cadence_raw) if isinstance(cadence_raw, (int, float)) else default_cadence

        reason = None
        if next_followup is not None and next_followup <= today:
            reason = f"Follow-up was scheduled for {next_followup.isoformat()}"
        elif next_followup is None:
            if last_contact is not None and (last_contact + timedelta(days=cadence)) <= today:
                reason = (
                    f"No follow-up date set; last contact {last_contact.isoformat()} "
                    f"+ {cadence}d cadence has elapsed"
                )
            elif last_contact is None:
                # Judgment call: a contact with neither date set has effectively
                # infinite time elapsed — surface it rather than silently never
                # reminding about it, since this is a read-only reminder, not a mutation.
                reason = "No last-contact or follow-up date on file"

        if not reason:
            continue

        priority = plain(p.get("Follow-Up Priority", {})) or ""
        action = f"Reach out to {name}" + (f" at {company}" if company else "")
        if priority:
            action += f" (priority: {priority})"

        due.append({
            "name": name,
            "company": company,
            "reason": reason,
            "suggested_action": action,
        })
    return due


def run() -> list[dict]:
    with RunLedger("crm") as ledger:
        due = due_contacts()
        ledger.items = len(due)
        return due


if __name__ == "__main__":
    contacts = run()
    if not contacts:
        print("No contacts are due for follow-up.")
    else:
        print(f"{len(contacts)} contact(s) due for follow-up:")
        for c in contacts:
            print(f"  - {c['name']} ({c['company'] or 'no company'}): {c['reason']}")
            print(f"      -> {c['suggested_action']}")
