"""Ashby job board adapter."""
from __future__ import annotations

from agents.discovery.base import get
from core.alerts import notify
from core.models import JobPosting


def fetch_jobs(company_name: str, endpoint_or_slug: str) -> list[JobPosting]:
    url = endpoint_or_slug
    if not url.startswith("http"):
        url = f"https://api.ashbyhq.com/posting-api/job-board/{endpoint_or_slug}"

    try:
        resp = get(url)
        resp.raise_for_status()
        data = resp.json()
        jobs = data.get("jobs", [])
    except Exception as exc:
        notify("Ashby fetch failed", f"{company_name}: {exc}")
        return []

    postings = []
    for job in jobs:
        try:
            job_url = job.get("jobUrl") or (
                f"https://jobs.ashbyhq.com/{endpoint_or_slug}/{job['id']}" if job.get("id") else ""
            )
            postings.append(JobPosting(
                company=company_name,
                title=job.get("title", ""),
                url=job_url,
                source="Ashby",
                location=job.get("location", ""),
                remote=bool(job.get("isRemote", False)),
                description=job.get("descriptionPlain", ""),
            ))
        except Exception:
            continue
    return postings
