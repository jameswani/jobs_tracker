"""Weekly funnel metrics rollup, written to the Pipeline Metrics DB."""
from __future__ import annotations

import re
from datetime import date, timedelta

from core.local_store import RunLedger
from core.notion_store import create_metrics_row, db_id, plain, query_database


def _looks_applied(status_text: str) -> bool:
    """Same normalization as agents.tracking._looks_applied: this workspace's
    Applications Status select currently only has the default 'Preparing'
    option live, so match by absence of that word rather than an exact
    emoji-prefixed string list that may not exist yet."""
    norm = re.sub(r"[^a-z]", "", (status_text or "").lower())
    if not norm:
        return False
    return "preparing" not in norm


def run() -> dict:
    with RunLedger("analytics") as ledger:
        opportunities = query_database(db_id("opportunities"))
        applications = query_database(db_id("applications"))
        interviews = query_database(db_id("interviews"))

        discovered = len(opportunities)
        shortlisted = sum(
            1 for o in opportunities if plain(o["properties"].get("Status", {})) == "Shortlisted"
        )
        applied = len(applications)
        responses = sum(
            1 for a in applications if _looks_applied(plain(a["properties"].get("Status", {})))
        )
        interviews_count = len(interviews)

        # "Offer" is a real Opportunities Status option today; Applications has no
        # offer-flavored option live yet, so also check by substring in case one
        # gets added later (defensive, not a hardcoded guess at the exact string).
        opp_offers = sum(1 for o in opportunities if plain(o["properties"].get("Status", {})) == "Offer")
        app_offers = sum(
            1 for a in applications if "offer" in (plain(a["properties"].get("Status", {})) or "").lower()
        )
        offers = opp_offers + app_offers

        response_rate = responses / applied if applied else 0.0
        interview_rate = interviews_count / applied if applied else 0.0
        offer_rate = offers / applied if applied else 0.0

        today = date.today()
        iso = today.isocalendar()
        week_label = f"{iso.year}-W{iso.week:02d}"
        week_start = (today - timedelta(days=today.weekday())).isoformat()

        summary = (
            f"{discovered} opportunities discovered, {shortlisted} shortlisted, "
            f"{applied} application(s) sent. Response rate {response_rate:.0%}, "
            f"interview rate {interview_rate:.0%}, offer rate {offer_rate:.0%}."
        )

        metrics = {
            "week": week_label,
            "week_start": week_start,
            "discovered": discovered,
            "shortlisted": shortlisted,
            "applied": applied,
            "responses": responses,
            "interviews": interviews_count,
            "offers": offers,
            "response_rate": response_rate,
            "interview_rate": interview_rate,
            "offer_rate": offer_rate,
            "summary": summary,
        }

        try:
            create_metrics_row({
                "Week": {"title": [{"text": {"content": week_label}}]},
                "Week Start": {"date": {"start": week_start}},
                "Discovered": {"number": discovered},
                "Shortlisted": {"number": shortlisted},
                "Applied": {"number": applied},
                "Responses": {"number": responses},
                "Interviews": {"number": interviews_count},
                "Offers": {"number": offers},
                "Response Rate": {"number": response_rate},
                "Interview Rate": {"number": interview_rate},
                "Offer Rate": {"number": offer_rate},
                "Summary": {"rich_text": [{"text": {"content": summary[:1990]}}]},
            })
        except RuntimeError:
            pass  # Metrics DB not provisioned yet — still return the computed numbers

        ledger.items = discovered + applied
        return metrics


if __name__ == "__main__":
    result = run()
    for key, value in result.items():
        print(f"{key}: {value}")
