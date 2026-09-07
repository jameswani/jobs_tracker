"""New-posting detection: cross-references the local sqlite mirror and the live
Notion Opportunities DB, then collapses same-company near-duplicate titles
within the incoming batch itself (multiple ATSs/boards often list the exact
same req with slightly different title formatting).
"""
from __future__ import annotations

from rapidfuzz import fuzz

from core.local_store import RunLedger, connect, known_keys, record_posting
from core.models import JobPosting
from core.notion_store import existing_dedup_keys

_TITLE_SIMILARITY_THRESHOLD = 92


def _company_part(post: JobPosting) -> str:
    return post.dedup_key.split("|", 1)[0]


def _title_part(post: JobPosting) -> str:
    parts = post.dedup_key.split("|")
    return parts[1] if len(parts) > 1 else ""


def dedupe(postings: list[JobPosting]) -> list[JobPosting]:
    with RunLedger("dedup") as ledger:
        conn = connect()
        try:
            already_known = known_keys(conn) | existing_dedup_keys()

            survivors: list[JobPosting] = []
            for post in postings:
                ledger.items += 1
                key = post.dedup_key

                if key in already_known:
                    record_posting(conn, key, None, post.company, post.title, post.url, post.source)
                    continue

                duplicate_of = next(
                    (
                        s for s in survivors
                        if _company_part(s) == _company_part(post)
                        and fuzz.ratio(_title_part(s), _title_part(post)) >= _TITLE_SIMILARITY_THRESHOLD
                    ),
                    None,
                )
                if duplicate_of is not None:
                    # Same-company near-duplicate title within this batch — keep the
                    # first occurrence, but still note this posting's source against it.
                    record_posting(conn, duplicate_of.dedup_key, None, duplicate_of.company,
                                    duplicate_of.title, duplicate_of.url, post.source)
                    continue

                survivors.append(post)

            return survivors
        finally:
            conn.close()
