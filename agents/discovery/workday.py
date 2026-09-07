"""Workday CXS job board adapter.

Workday has no stable public schema across tenants (site name, facet keys,
and response field names vary), so this is best-effort: POST the standard
search body, defensively pull whatever fields look right, and give up
quietly rather than guessing wrong data into the pipeline.
"""
from __future__ import annotations

from agents.discovery.base import post
from core.alerts import notify
from core.models import JobPosting

_PAGE_SIZE = 20


def _endpoint_url(tenant_or_endpoint: str) -> str:
    if tenant_or_endpoint.startswith("http"):
        return tenant_or_endpoint
    tenant = tenant_or_endpoint
    return f"https://{tenant}.myworkdayjobs.com/wday/cxs/{tenant}/jobs"


def fetch_jobs(company_name: str, tenant_or_endpoint: str) -> list[JobPosting]:
    url = _endpoint_url(tenant_or_endpoint)
    postings: list[JobPosting] = []
    offset = 0
    failures = 0

    while True:
        try:
            resp = post(url, json={
                "appliedFacets": {},
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            })
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            failures += 1
            if failures == 1:
                notify("Workday fetch failed", f"{company_name}: {exc}")
            break

        job_postings = data.get("jobPostings") or []
        if not job_postings:
            break

        for job in job_postings:
            try:
                path = job.get("externalPath", "")
                job_url = url.split("/wday/cxs/")[0] + path if path else ""
                postings.append(JobPosting(
                    company=company_name,
                    title=job.get("title", ""),
                    url=job_url,
                    source="Workday",
                    location=job.get("locationsText", "") or job.get("location", ""),
                    posted_at=None,
                ))
            except Exception:
                continue

        offset += _PAGE_SIZE
        total = data.get("total")
        if total is not None and offset >= total:
            break
        if offset > 500:
            break

    return postings
