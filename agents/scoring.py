"""Two-stage scoring: free rule-based track/exclusion filtering (stage 1), then
cost-bounded LLM fit-scoring (stage 2) with a rule-based fallback so the
pipeline still produces a full Opportunities DB without an API key.
"""
from __future__ import annotations

from core.alerts import notify
from core.config import search_terms, settings
from core.local_store import RunLedger, connect, record_posting
from core.llm import llm_available, score_job
from core.models import JobPosting, ScoreResult
from core.notion_store import create_opportunity, get_companies

_STATUSES = ("Shortlisted", "Discovered", "Screened Out")


def _match_tracks(title: str, tracks: dict) -> list[tuple[str, str]]:
    """Tracks whose include keywords appear in the title, longest/most-specific
    keyword match first (so e.g. 'investment banking analyst' beats a shorter
    sibling keyword when several tracks match)."""
    title_l = title.lower()
    matches = [
        (key, kw)
        for key, track in tracks.items()
        for kw in track["include"]
        if kw.lower() in title_l
    ]
    matches.sort(key=lambda m: len(m[1]), reverse=True)
    return matches


def _rule_fallback_score(track_label: str) -> ScoreResult:
    return ScoreResult(
        match_score=55, tech_score=50, finance_score=50,
        quant_score=50, leadership_score=50,
        track=track_label, summary="",
        rationale="Rule-based fallback — LLM unavailable or batch limit reached",
    )


def score_and_publish(postings: list[JobPosting]) -> dict:
    counts = {status: 0 for status in _STATUSES}
    if not postings:
        return counts

    with RunLedger("scoring") as ledger:
        cfg = settings()["scoring"]
        tracks = search_terms()["tracks"]
        global_exclude = [kw.lower() for kw in search_terms()["global_exclude"]]
        label_to_resume = {t["label"]: t["resume"] for t in tracks.values()}

        conn = connect()
        try:
            companies_by_name = {c.name.lower(): c.page_id for c in get_companies()}
            llm_ok = llm_available()
            llm_calls = 0

            for post in postings:
                ledger.items += 1
                print(f"scoring {post.company} — {post.title}...", flush=True)
                title_l = post.title.lower()

                if any(kw in title_l for kw in global_exclude):
                    status, score = "Screened Out", None
                else:
                    matches = _match_tracks(post.title, tracks)
                    if not matches:
                        status, score = "Screened Out", None
                    else:
                        rule_track_label = tracks[matches[0][0]]["label"]
                        score = None
                        if llm_ok and llm_calls < cfg["llm_batch_limit"]:
                            llm_calls += 1
                            try:
                                score = score_job(post)
                            except Exception as exc:
                                notify("Scoring", f"LLM call failed for {post.company} / {post.title}: {exc}")
                        if score is None:
                            score = _rule_fallback_score(rule_track_label)

                        if score.match_score >= cfg["shortlist_threshold"]:
                            status = "Shortlisted"
                        elif score.match_score < cfg["screen_out_threshold"]:
                            status = "Screened Out"
                        else:
                            status = "Discovered"

                resume_name = label_to_resume.get(score.track) if score else None
                company_page_id = companies_by_name.get(post.company.lower())
                notion_id = create_opportunity(post, company_page_id, score, status, resume_name)
                record_posting(conn, post.dedup_key, notion_id, post.company, post.title, post.url, post.source)
                counts[status] += 1
                print(f"  -> {status}" + (f" ({score.match_score})" if score else ""), flush=True)
        finally:
            conn.close()

    return counts


if __name__ == "__main__":
    result = score_and_publish([])
    print("no postings to score (invoke via orchestrator)")
