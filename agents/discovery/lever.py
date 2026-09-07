"""Lever job board adapter."""
from __future__ import annotations

from agents.discovery.base import get
from core.alerts import notify
from core.models import JobPosting


def fetch_jobs(company_name: str, endpoint_or_slug: str) -> list[JobPosting]:
    url = endpoint_or_slug
    if not url.startswith("http"):
        url = f"https://api.lever.co/v0/postings/{endpoint_or_slug}?mode=json"

    try:
        resp = get(url)
        resp.raise_for_status()
        postings_raw = resp.json()
        if not isinstance(postings_raw, list):
            raise ValueError("unexpected Lever response shape")
    except Exception as exc:
        notify("Lever fetch failed", f"{company_name}: {exc}")
        return []

    postings = []
    for job in postings_raw:
        try:
            categories = job.get("categories") or {}
            postings.append(JobPosting(
                company=company_name,
                title=job.get("text", ""),
                url=job.get("hostedUrl", ""),
                source="Lever",
                location=categories.get("location", ""),
                description=job.get("descriptionPlain", "") or job.get("description", ""),
            ))
        except Exception:
            continue
    return postings
