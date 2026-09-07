"""Position-based discovery through Adzuna's public jobs API."""
from __future__ import annotations

from datetime import date

from agents.discovery.base import get
from core.config import adzuna_credentials
from core.models import JobPosting


def search_adzuna(query: str, location: str = "", country: str = "us", limit: int = 20) -> list[JobPosting]:
    app_id, app_key = adzuna_credentials()
    if not app_id or not app_key:
        return []
    params = {"app_id": app_id, "app_key": app_key, "results_per_page": min(limit, 50), "what": query, "content-type": "application/json"}
    if location:
        params["where"] = location
    resp = get(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1", params=params)
    resp.raise_for_status()
    postings = []
    for job in resp.json().get("results", []):
        try:
            postings.append(JobPosting(
                company=(job.get("company") or {}).get("display_name", ""),
                title=job.get("title", ""), url=job.get("redirect_url", ""),
                source="Adzuna", location=(job.get("location") or {}).get("display_name", ""),
                description=job.get("description", ""),
                posted_at=date.fromisoformat(job["created"][:10]) if job.get("created") else None,
            ))
        except Exception:
            continue
    return postings
