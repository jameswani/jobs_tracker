"""On-demand tailored resume / cover-letter generation for a single opportunity."""
from __future__ import annotations

import argparse
import re
from functools import lru_cache
from pathlib import Path

from docx import Document

from core.config import ROOT, settings
from core.llm import generate_document
from core.notion_store import get_page, plain

# Fixed reference files on disk (not per-opportunity, not configurable) —
# see task spec: these are the candidate's real source-of-truth documents.
_BANK_PATH = Path("/Users/jameslako/Desktop/roadmap/Final_Experience_Bank.docx")
_BASE_RESUME_PATH = Path("/Users/jameslako/Desktop/roadmap/Resume/James_Lako_SWE.docx")


def _read_docx_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


@lru_cache(maxsize=1)
def load_experience_bank() -> str:
    return _read_docx_text(_BANK_PATH)


@lru_cache(maxsize=1)
def load_base_resume() -> str:
    return _read_docx_text(_BASE_RESUME_PATH)


def _sanitize(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", name or "").strip("-")
    return cleaned or "unknown"


def generate_for_opportunity(opportunity_page_id: str, kinds: list[str] | None = None) -> dict:
    if kinds is None:
        kinds = ["resume", "cover_letter"]

    page = get_page(opportunity_page_id)
    props = page.get("properties", {})
    role_title = plain(props.get("Role", {})) or "Unknown Role"

    # Company on Opportunities is a relation, unreadable via plain() without a
    # second API call; create_opportunity() already bakes the name into Role as
    # "Company — Title", so recover it from there instead.
    if " — " in role_title:
        company, title = role_title.split(" — ", 1)
    else:
        company, title = "Unknown Company", role_title

    ai_summary = plain(props.get("AI Summary", {})) or ""
    notes = plain(props.get("Notes", {})) or ""
    url = plain(props.get("Job Posting URL", {})) or ""
    deadline = plain(props.get("Application Deadline", {})) or ""

    # This template never stores the original job description verbatim — only
    # our own derived summary/notes — so jd_text below is a reconstruction, not
    # the real JD text. generate_document() is told to work from this plus the
    # experience bank, which is the actual source of truth for content.
    jd_lines = [f"Company: {company}", f"Role: {title}"]
    if ai_summary:
        jd_lines.append(f"Summary: {ai_summary}")
    if notes:
        jd_lines.append(f"Notes: {notes}")
    if deadline:
        jd_lines.append(f"Application Deadline: {deadline}")
    if url:
        jd_lines.append(f"Posting URL: {url}")
    jd_text = "\n".join(jd_lines)

    bank_text = load_experience_bank()
    base_resume_text = load_base_resume()

    out_dir = ROOT / settings()["paths"]["output"] / f"{_sanitize(company)}_{_sanitize(title)}"
    out_dir.mkdir(parents=True, exist_ok=True)

    results: dict = {"resume": None, "cover_letter": None}
    for kind in kinds:
        try:
            markdown = generate_document(kind, jd_text, bank_text, base_resume_text)
        except RuntimeError as exc:
            results[kind] = f"ERROR: {exc}"
            continue
        path = out_dir / f"{kind}.md"
        path.write_text(markdown)
        results[kind] = str(path)
    return results


def _cli():
    parser = argparse.ArgumentParser(description="Generate tailored documents for a Notion opportunity.")
    parser.add_argument("opportunity_page_id")
    parser.add_argument("--resume-only", action="store_true")
    parser.add_argument("--cover-letter-only", action="store_true")
    args = parser.parse_args()

    if args.resume_only:
        kinds = ["resume"]
    elif args.cover_letter_only:
        kinds = ["cover_letter"]
    else:
        kinds = ["resume", "cover_letter"]

    result = generate_for_opportunity(args.opportunity_page_id, kinds)
    for kind, path in result.items():
        if path is not None:
            print(f"{kind}: {path}")


if __name__ == "__main__":
    _cli()
