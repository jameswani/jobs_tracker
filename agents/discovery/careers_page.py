"""Manual-recipe careers page scraper for companies the ATS Resolver couldn't resolve."""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from agents.discovery.base import get
from core.alerts import notify
from core.config import recipes
from core.models import JobPosting


def _render_with_playwright(url: str) -> str | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        notify("Playwright unavailable", f"Skipping JS-rendered recipe for {url}")
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.goto(url, timeout=20000)
            html = page.content()
            browser.close()
            return html
    except Exception as exc:
        notify("Playwright render failed", f"{url}: {exc}")
        return None


def fetch_jobs(company_name: str) -> list[JobPosting]:
    recipe = recipes().get(company_name)
    if not recipe:
        return []

    url = recipe["url"]
    if recipe.get("render_js"):
        html = _render_with_playwright(url)
        if html is None:
            return []
    else:
        try:
            resp = get(url)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            notify("Careers page fetch failed", f"{company_name}: {exc}")
            return []

    soup = BeautifulSoup(html, "html.parser")
    postings = []
    for card in soup.select(recipe["job_selector"]):
        try:
            title_el = card.select_one(recipe["title_selector"])
            link_el = card.select_one(recipe["link_selector"])
            if not title_el or not link_el:
                continue
            title = title_el.get_text(strip=True)
            href = link_el.get("href", "")
            job_url = urljoin(url, href) if href else url
            postings.append(JobPosting(
                company=company_name,
                title=title,
                url=job_url,
                source="Careers Page",
            ))
        except Exception:
            continue
    return postings
