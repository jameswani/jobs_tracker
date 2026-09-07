"""All Notion I/O goes through this module (single choke point, rate-limited).

Uses raw HTTP against the classic (2022-06-28) Notion API — the notion-client
SDK's v3 databases.update()/create() silently drop `properties` under the
newer multi-data-source model, while the REST API itself still serves flat
database properties correctly under the pinned version header.

Property names below match the existing Career Command Center template plus
the fields added by scripts/upgrade_notion_schema.py.
"""
from __future__ import annotations

import time
from datetime import date
from functools import lru_cache

import httpx

from core.config import notion_ids, notion_token, settings
from core.models import Company, JobPosting, ScoreResult

_API = "https://api.notion.com/v1"
_VERSION = "2022-06-28"
_MIN_INTERVAL = 0.34  # ~3 req/s Notion rate limit
_last_call = 0.0


def _throttle():
    global _last_call
    wait = _MIN_INTERVAL - (time.time() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


@lru_cache(maxsize=1)
def _http() -> httpx.Client:
    return httpx.Client(
        base_url=_API,
        headers={
            "Authorization": f"Bearer {notion_token()}",
            "Notion-Version": _VERSION,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


def _request(method: str, path: str, **kwargs) -> dict:
    _throttle()
    resp = _http().request(method, path, **kwargs)
    if resp.status_code >= 400:
        raise RuntimeError(f"Notion API {method} {path} -> {resp.status_code}: {resp.text[:500]}")
    return resp.json() if resp.text else {}


def _db(name: str) -> str:
    return settings()["notion"]["databases"][name]


def _query_all(database_id: str, **body) -> list[dict]:
    results, cursor = [], None
    while True:
        payload = dict(body)
        if cursor:
            payload["start_cursor"] = cursor
        resp = _request("POST", f"/databases/{database_id}/query", json=payload)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            return results
        cursor = resp["next_cursor"]


# ---------- property helpers ----------

def _plain(prop: dict) -> str:
    t = prop.get("type")
    if t in ("rich_text", "title"):
        return "".join(x["plain_text"] for x in prop.get(t, []))
    if t == "select":
        return (prop.get("select") or {}).get("name", "")
    if t == "url":
        return prop.get("url") or ""
    if t == "checkbox":
        return prop.get("checkbox")
    if t == "date":
        return ((prop.get("date") or {}).get("start")) or ""
    if t == "number":
        return prop.get("number")
    return ""


def rt(text: str) -> dict:
    return {"rich_text": [{"text": {"content": (text or "")[:1990]}}]}


def sel(name: str) -> dict:
    return {"select": {"name": name}}


# ---------- Companies ----------

def get_companies() -> list[Company]:
    rows = _query_all(_db("companies"))
    out = []
    for r in rows:
        p = r["properties"]
        out.append(Company(
            page_id=r["id"],
            name=_plain(p.get("Company Name", {})) or "",
            ats_type=_plain(p.get("ATS Type", {})) or "",
            ats_endpoint=_plain(p.get("ATS Endpoint", {})) or "",
            resolution_status=_plain(p.get("Resolution Status", {})) or "",
            careers_url=_plain(p.get("Website/URL", {})) or "",
            paused=bool(_plain(p.get("Paused", {})) or False),
        ))
    return [c for c in out if c.name]


def update_company_resolution(page_id: str, ats_type: str, endpoint: str, status: str):
    _request("PATCH", f"/pages/{page_id}", json={"properties": {
        "ATS Type": sel(ats_type) if ats_type else {"select": None},
        "ATS Endpoint": {"url": endpoint or None},
        "Resolution Status": sel(status),
        "Hiring Platform": rt(ats_type.title() if ats_type else ""),
    }})


# ---------- Documents (resume versions) ----------

@lru_cache(maxsize=1)
def resume_pages() -> dict[str, str]:
    """Map document name -> page id, for the Resume Used relation."""
    rows = _query_all(_db("documents"))
    return {_plain(r["properties"].get("Name", {})): r["id"] for r in rows}


# ---------- Opportunities ----------

def existing_dedup_keys() -> set[str]:
    rows = _query_all(_db("opportunities"))
    return {_plain(r["properties"].get("Duplicate Key", {})) for r in rows} - {""}


def create_opportunity(post: JobPosting, company_page_id: str | None,
                       score: ScoreResult | None, status: str,
                       resume_name: str | None) -> str:
    props: dict = {
        "Role": {"title": [{"text": {"content": f"{post.company} — {post.title}"[:200]}}]},
        "Job Posting URL": {"url": post.url},
        "Location": rt(post.location),
        "Source": sel(post.source),
        "Status": sel(status),
        "Date Found": {"date": {"start": date.today().isoformat()}},
        "Duplicate Key": rt(post.dedup_key),
        "Role Type": rt(post.title),
    }
    if post.remote:
        props["Work Mode"] = sel("Remote")
    if company_page_id:
        props["Company"] = {"relation": [{"id": company_page_id}]}
    if post.comp_min:
        props["Compensation Min ($)"] = {"number": post.comp_min}
    if post.comp_max:
        props["Compensation Max ($)"] = {"number": post.comp_max}
    if score:
        props.update({
            "Match Score (1-100)": {"number": score.match_score},
            "Tech Score (1-100)": {"number": score.tech_score},
            "Finance Score (1-100)": {"number": score.finance_score},
            "Quant Score (1-100)": {"number": score.quant_score},
            "Leadership Score (1-100)": {"number": score.leadership_score},
            "AI Summary": rt(score.summary),
            "Notes": rt(score.rationale),
            "Track": sel(score.track),
        })
    if resume_name and resume_name in resume_pages():
        props["Resume Used"] = {"relation": [{"id": resume_pages()[resume_name]}]}
    page = _request("POST", "/pages", json={
        "parent": {"database_id": _db("opportunities")},
        "properties": props,
    })
    return page["id"]


def get_open_opportunities() -> list[dict]:
    return _query_all(_db("opportunities"), filter={
        "or": [
            {"property": "Status", "select": {"equals": s}}
            for s in ("Discovered", "Shortlisted", "Applied", "Interviewing", "Pending Review")
        ]
    })


def update_opportunity(page_id: str, props: dict):
    _request("PATCH", f"/pages/{page_id}", json={"properties": props})


# ---------- CRM ----------

def get_contacts() -> list[dict]:
    return _query_all(_db("crm"))


# ---------- Pages (digest / health) ----------

def replace_page_content(page_id: str, markdown_lines: list[str]):
    """Clear a page's blocks and write fresh paragraph/heading blocks."""
    existing = _request("GET", f"/blocks/{page_id}/children")
    for block in existing["results"]:
        _request("DELETE", f"/blocks/{block['id']}")
    blocks = []
    for line in markdown_lines[:90]:
        if line.startswith("## "):
            blocks.append({"heading_2": {"rich_text": [{"text": {"content": line[3:]}}]}})
        elif line.startswith("- "):
            blocks.append({"bulleted_list_item": {"rich_text": [{"text": {"content": line[2:][:1990]}}]}})
        else:
            blocks.append({"paragraph": {"rich_text": [{"text": {"content": line[:1990]}}]}})
    _request("PATCH", f"/blocks/{page_id}/children", json={"children": blocks})


def create_metrics_row(props: dict):
    metrics_db = notion_ids().get("metrics_db")
    if not metrics_db:
        raise RuntimeError("Metrics DB not created yet — run scripts/upgrade_notion_schema.py")
    _request("POST", "/pages", json={"parent": {"database_id": metrics_db}, "properties": props})


# ---------- Generic helpers (for agents needing DBs beyond the ones above) ----------

def db_id(name: str) -> str:
    """Look up a configured database id by its settings.yaml key
    (opportunities | companies | documents | crm | interviews | applications)."""
    return _db(name)


def plain(prop: dict) -> str:
    """Public accessor for extracting a plain value from a Notion property dict."""
    return _plain(prop)


def query_database(database_id: str, **body) -> list[dict]:
    """Generic paginated query. body may include filter=..., sorts=..."""
    return _query_all(database_id, **body)


def create_page_in(database_id: str, properties: dict) -> dict:
    return _request("POST", "/pages", json={"parent": {"database_id": database_id}, "properties": properties})


def update_page(page_id: str, properties: dict) -> dict:
    return _request("PATCH", f"/pages/{page_id}", json={"properties": properties})


def get_page(page_id: str) -> dict:
    return _request("GET", f"/pages/{page_id}")


# ---------- Schema admin (used by scripts/upgrade_notion_schema.py) ----------

def get_database(database_id: str) -> dict:
    return _request("GET", f"/databases/{database_id}")


def update_database(database_id: str, properties: dict | None = None, **fields) -> dict:
    body = dict(fields)
    if properties:
        body["properties"] = properties
    return _request("PATCH", f"/databases/{database_id}", json=body)


def create_database(parent_page_id: str, title: str, properties: dict) -> dict:
    return _request("POST", "/databases", json={
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": [{"type": "text", "text": {"content": title}}],
        "properties": properties,
    })


def search(query: str, object_type: str | None = None) -> list[dict]:
    body: dict = {"query": query}
    if object_type:
        body["filter"] = {"property": "object", "value": object_type}
    return _request("POST", "/search", json=body)["results"]


def create_page(parent_page_id: str, title: str) -> dict:
    return _request("POST", "/pages", json={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": [{"type": "text", "text": {"content": title}}]},
    })
