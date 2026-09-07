"""Greenhouse job board adapter."""
from __future__ import annotations

import re

from agents.discovery.base import get
from core.alerts import notify
from core.models import JobPosting

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", html or "")).strip()


def fetch_jobs(company_name: str, endpoint_or_slug: str) -> list[JobPosting]:
    url = endpoint_or_slug
    if not url.startswith("http"):
        url = f"https://boards-api.greenhouse.io/v1/boards/{endpoint_or_slug}/jobs"

    try:
        resp = get(url, params={"content": "true"})
        resp.raise_for_status()
        jobs = resp.json().get("jobs", [])
    except Exception as exc:
        notify("Greenhouse fetch failed", f"{company_name}: {exc}")
        return []

    postings = []
    for job in jobs:
        try:
            postings.append(JobPosting(
                company=company_name,
                title=job.get("title", ""),
                url=job.get("absolute_url", ""),
                source="Greenhouse",
                location=(job.get("location") or {}).get("name", ""),
                description=_strip_html(job.get("content", "")),
            ))
        except Exception:
            continue
    return postings
