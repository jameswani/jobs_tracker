"""Discovery orchestrator: fan out to every resolved company's ATS adapter,
filter by search-term relevance, and hand back the surviving postings."""
from __future__ import annotations

from collections import Counter

from agents.discovery import ashby, careers_page, greenhouse, lever, workday
from agents.discovery.aggregators import search_adzuna
from core.alerts import notify
from core.config import recipes, search_terms, settings
from core.local_store import RunLedger
from core.models import Company, JobPosting
from core.notion_store import get_companies

_ADAPTERS = {
    "greenhouse": greenhouse.fetch_jobs,
    "lever": lever.fetch_jobs,
    "ashby": ashby.fetch_jobs,
    "workday": workday.fetch_jobs,
}


def _matches_search_terms(title: str, terms: dict) -> bool:
    title_lower = title.lower()
    if any(term.lower() in title_lower for term in terms.get("global_exclude", [])):
        return False
    for track in terms.get("tracks", {}).values():
        if any(term.lower() in title_lower for term in track.get("include", [])):
            return True
    return False


def _fetch_for_company(company: Company) -> list[JobPosting]:
    if company.ats_type in _ADAPTERS:
        return _ADAPTERS[company.ats_type](company.name, company.ats_endpoint)
    if company.ats_type == "manual" or company.resolution_status == "Needs Manual Recipe":
        if company.name in recipes():
            return careers_page.fetch_jobs(company.name)
    return []


def discover_all() -> list[JobPosting]:
    terms = search_terms()
    max_per_company = settings().get("discovery", {}).get("max_jobs_per_company")
    results: list[JobPosting] = []

    with RunLedger("discovery") as ledger:
        companies = get_companies()
        source_failures: Counter = Counter()

        for company in companies:
            if company.paused:
                continue
            print(f"fetching {company.name} ({company.ats_type or 'unresolved'})...", flush=True)
            try:
                postings = _fetch_for_company(company)
            except Exception as exc:
                source_failures[company.ats_type or "manual"] += 1
                print(f"  -> error: {exc}", flush=True)
                notify("Discovery adapter error", f"{company.name} ({company.ats_type}): {exc}")
                continue

            if not postings:
                print("  -> 0 postings", flush=True)
                continue

            matched = 0
            for posting in postings:
                if max_per_company and matched >= max_per_company:
                    break
                if _matches_search_terms(posting.title, terms):
                    results.append(posting)
                    ledger.items += 1
                    matched += 1
            print(f"  -> {len(postings)} postings, {matched} matched a track", flush=True)

        for source, count in source_failures.items():
            if count >= 3:
                notify("Discovery source degraded", f"{source}: {count} companies failed this run")

        position_cfg = settings().get("position_search", {})
        if position_cfg.get("enabled"):
            max_total = position_cfg.get("max_total_results", 120)
            for query in position_cfg.get("queries", []):
                for location in position_cfg.get("locations", [""]):
                    if len(results) >= max_total:
                        break
                    try:
                        remaining = max_total - len(results)
                        found = search_adzuna(query, location, limit=min(position_cfg.get("results_per_query", 20), remaining))
                        results.extend(found[:remaining])
                        print(f"position search {query} / {location}: {len(found)} results", flush=True)
                    except Exception as exc:
                        notify("Position search failed", f"Adzuna {query} / {location}: {exc}")
                if len(results) >= max_total:
                    break

    return results


def main():
    postings = discover_all()
    counts = Counter(p.source for p in postings)
    print(f"Discovered {len(postings)} matching postings:")
    for source, count in sorted(counts.items()):
        print(f"  {source}: {count}")


if __name__ == "__main__":
    main()
