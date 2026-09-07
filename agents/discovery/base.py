"""Shared HTTP client + slug guessing for the discovery agents."""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

_USER_AGENT = "job-pipeline-discovery/1.0 (+https://github.com/jameslako)"
_TIMEOUT = 15.0

_SUFFIXES = (
    "incorporated", "corporation", "company", "holdings", "technologies",
    "inc", "llc", "corp", "co", "ltd", "plc", "group", "labs", "technology",
)


@lru_cache(maxsize=1)
def client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": _USER_AGENT}, timeout=_TIMEOUT, follow_redirects=True)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    reraise=True,
)
def get(url: str, **kwargs) -> httpx.Response:
    return client().get(url, **kwargs)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
    reraise=True,
)
def post(url: str, **kwargs) -> httpx.Response:
    return client().post(url, **kwargs)


def _strip_suffix(words: list[str]) -> list[str]:
    trimmed = list(words)
    while trimmed and trimmed[-1].lower() in _SUFFIXES:
        trimmed = trimmed[:-1]
    return trimmed or words


def slugify(company_name: str) -> list[str]:
    """Return plausible ATS board-slug variants, most-likely-first."""
    name = unicodedata.normalize("NFKD", company_name or "").encode("ascii", "ignore").decode()
    name = name.replace("&", " and ")
    name = re.sub(r"[^a-zA-Z0-9 -]", " ", name)
    words = [w for w in re.split(r"[\s-]+", name.strip()) if w]
    if not words:
        return []

    trimmed = _strip_suffix(list(words))

    variants: list[str] = []

    def add(ws: list[str], sep: str):
        if ws:
            candidate = sep.join(w.lower() for w in ws)
            if candidate and candidate not in variants:
                variants.append(candidate)

    add(trimmed, "")
    add(trimmed, "-")
    add(words, "")
    add(words, "-")
    if len(trimmed) > 1:
        add(trimmed[:1], "")

    return variants
