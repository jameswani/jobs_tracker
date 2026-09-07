"""ATS Resolver: figures out which ATS (and board slug/endpoint) a company uses."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from agents.discovery.base import get, slugify
from core.alerts import notify
from core.local_store import RunLedger, cache_resolution, cached_resolution, connect
from core.models import Company
from core.notion_store import get_companies, update_company_resolution

_GREENHOUSE_TMPL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_LEVER_TMPL = "https://api.lever.co/v0/postings/{slug}?mode=json"
_ASHBY_TMPL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _probe_greenhouse(slug: str) -> str | None:
    try:
        resp = get(_GREENHOUSE_TMPL.format(slug=slug))
        if resp.status_code == 200 and isinstance(resp.json().get("jobs"), list):
            return _GREENHOUSE_TMPL.format(slug=slug)
    except Exception:
        pass
    return None


def _probe_lever(slug: str) -> str | None:
    try:
        resp = get(_LEVER_TMPL.format(slug=slug))
        if resp.status_code == 200 and isinstance(resp.json(), list):
            return _LEVER_TMPL.format(slug=slug)
    except Exception:
        pass
    return None


def _probe_ashby(slug: str) -> str | None:
    try:
        resp = get(_ASHBY_TMPL.format(slug=slug))
        if resp.status_code == 200 and isinstance(resp.json(), dict):
            return _ASHBY_TMPL.format(slug=slug)
    except Exception:
        pass
    return None


def _fingerprint_careers_page(careers_url: str) -> tuple[str, str] | None:
    try:
        resp = get(careers_url)
        if resp.status_code != 200:
            return None
        html = resp.text
    except Exception:
        return None

    soup = BeautifulSoup(html, "html.parser")
    links = [a.get("href", "") for a in soup.find_all("a")] + [html]
    blob = " ".join(links)

    m = re.search(r"boards\.greenhouse\.io/([a-zA-Z0-9_-]+)", blob)
    if m:
        return "greenhouse", _GREENHOUSE_TMPL.format(slug=m.group(1))
    m = re.search(r"jobs\.lever\.co/([a-zA-Z0-9_-]+)", blob)
    if m:
        return "lever", _LEVER_TMPL.format(slug=m.group(1))
    m = re.search(r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)", blob)
    if m:
        return "ashby", _ASHBY_TMPL.format(slug=m.group(1))
    m = re.search(r"([a-zA-Z0-9-]+)\.myworkdayjobs\.com", blob)
    if m:
        tenant = m.group(1)
        # The CXS "site" path segment (e.g. External, Careers) isn't reliably
        # findable from the careers page HTML alone, so we only derive the
        # tenant here; this endpoint is best-effort and needs a manual check
        # against the real board before it's trusted.
        endpoint = f"https://{tenant}.myworkdayjobs.com/wday/cxs/{tenant}/jobs"
        return "workday", endpoint
    return None


def resolve_company(company: Company, conn) -> tuple[str, str, str]:
    cached = cached_resolution(conn, company.name)
    if cached and cached[0]:
        return cached[0], cached[1], "Resolved"

    for slug in slugify(company.name):
        endpoint = _probe_greenhouse(slug)
        if endpoint:
            cache_resolution(conn, company.name, "greenhouse", endpoint)
            return "greenhouse", endpoint, "Resolved"

    for slug in slugify(company.name):
        endpoint = _probe_lever(slug)
        if endpoint:
            cache_resolution(conn, company.name, "lever", endpoint)
            return "lever", endpoint, "Resolved"

    for slug in slugify(company.name):
        endpoint = _probe_ashby(slug)
        if endpoint:
            cache_resolution(conn, company.name, "ashby", endpoint)
            return "ashby", endpoint, "Resolved"

    if company.careers_url:
        found = _fingerprint_careers_page(company.careers_url)
        if found:
            ats_type, endpoint = found
            cache_resolution(conn, company.name, ats_type, endpoint)
            return ats_type, endpoint, "Resolved"

    return "", "", "Needs Manual Recipe"


def run():
    with RunLedger("resolver") as ledger:
        conn = connect()
        companies = get_companies()
        errors = 0
        for company in companies:
            if company.paused:
                continue
            needs_resolution = company.resolution_status in ("", "Pending") or not company.ats_type
            if not needs_resolution:
                continue
            print(f"resolving {company.name}...", flush=True)
            try:
                ats_type, endpoint, status = resolve_company(company, conn)
                update_company_resolution(company.page_id, ats_type, endpoint, status)
                ledger.items += 1
                print(f"  -> {status}" + (f" ({ats_type})" if ats_type else ""), flush=True)
            except Exception as exc:
                errors += 1
                print(f"  -> error: {exc}", flush=True)
                notify("Resolver error", f"{company.name}: {exc}")
                try:
                    update_company_resolution(company.page_id, "", "", "Error")
                except Exception:
                    pass
        if errors:
            notify("Resolver run finished with errors", f"{errors} companies failed")
        conn.close()


if __name__ == "__main__":
    run()
