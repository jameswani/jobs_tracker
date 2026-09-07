"""Shared pydantic models. Every discovery adapter emits JobPosting."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9 ]", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


class JobPosting(BaseModel):
    company: str
    title: str
    url: str
    source: str                      # Greenhouse | Lever | Ashby | Workday | Careers Page | Manual
    location: str = ""
    remote: bool = False
    description: str = ""
    posted_at: Optional[date] = None
    comp_min: Optional[float] = None
    comp_max: Optional[float] = None

    @property
    def dedup_key(self) -> str:
        return f"{_norm(self.company)}|{_norm(self.title)}|{_norm(self.location)[:40]}"


class ScoreResult(BaseModel):
    """Structured output returned by the LLM scoring call."""
    match_score: int = Field(ge=0, le=100, description="Overall fit 0-100")
    tech_score: int = Field(ge=0, le=100)
    finance_score: int = Field(ge=0, le=100)
    quant_score: int = Field(ge=0, le=100)
    leadership_score: int = Field(ge=0, le=100)
    track: str = Field(description="One of: Software Engineering, Product Management, Quantitative Finance, Investment Banking, FinTech, Data / ML, Other")
    summary: str = Field(description="3-line summary of the role")
    rationale: str = Field(description="2-3 bullets explaining the score")


class Company(BaseModel):
    page_id: str
    name: str
    ats_type: str = ""               # greenhouse | lever | ashby | workday | manual | ""
    ats_endpoint: str = ""
    resolution_status: str = ""      # Pending | Resolved | Needs Manual Recipe | Error
    careers_url: str = ""
    paused: bool = False
