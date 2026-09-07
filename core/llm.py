"""LLM client wrappers. Backend is chosen by config/settings.yaml -> llm.provider
(openai | anthropic | ollama); every call site dispatches on it so switching providers is a
config edit, not a code change. Degrades gracefully when no provider is usable:
scoring falls back to rule-based (caller checks for None)."""
from __future__ import annotations

import re
from functools import lru_cache

import httpx

from core.config import anthropic_key, openai_key, profile, settings
from core.models import JobPosting, ScoreResult

_THINK_TAG = re.compile(r"<think>.*?</think>", re.DOTALL)

def _provider() -> str:
    return settings()["llm"].get("provider", "openai")


def _ollama_host() -> str:
    return settings()["llm"].get("ollama_host", "http://localhost:11434")

@lru_cache(maxsize=1)
def _anthropic_client():
    key = anthropic_key()
    if not key:
        return None
    import anthropic
    return anthropic.Anthropic(api_key=key)


@lru_cache(maxsize=1)
def _openai_client():
    key = openai_key()
    if not key:
        return None
    from openai import OpenAI
    return OpenAI(api_key=key)


def _strip_thinking(text: str) -> str:
    return _THINK_TAG.sub("", text).strip()


def llm_available() -> bool:
    if _provider() == "openai":
        return _openai_client() is not None
    if _provider() == "ollama":
        try:
            httpx.get(f"{_ollama_host()}/api/tags", timeout=2.0)
            return True
        except httpx.TransportError:
            return False
    return _anthropic_client() is not None


_SCORING_SYSTEM = """You score job postings for fit against a specific candidate.
Be strict and realistic: 85+ means an unusually strong match the candidate should
prioritize; 40 or below means not worth applying. Consider skills overlap,
seniority fit (candidate is new-grad/early-career; senior roles score low),
track alignment with the candidate's target career paths, and sponsorship needs.
Classify the role into exactly one track."""


def score_job(post: JobPosting) -> ScoreResult | None:
    if not llm_available():
        return None
    prof = profile()
    cfg = settings()["llm"]
    prompt = (
        f"CANDIDATE PROFILE:\n{prof['summary']}\n"
        f"Seniority: {prof['seniority']} ({prof['years_experience']} yrs)\n"
        f"Sponsorship required: {prof['sponsorship_required']}\n"
        f"Skills: {prof['skills']}\n"
        f"Key experience: {prof['key_experience']}\n\n"
        f"JOB POSTING:\nCompany: {post.company}\nTitle: {post.title}\n"
        f"Location: {post.location}\nDescription:\n{post.description[:6000]}"
    )

    if _provider() == "ollama":
        resp = httpx.post(
            f"{_ollama_host()}/api/chat",
            json={
                "model": cfg["scoring_model"],
                "messages": [
                    {"role": "system", "content": _SCORING_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                "format": ScoreResult.model_json_schema(),
                "stream": False,
                "options": {"num_predict": cfg["scoring_max_tokens"]},
            },
            timeout=120.0,
        )
        resp.raise_for_status()
        content = _strip_thinking(resp.json()["message"]["content"])
        return ScoreResult.model_validate_json(content)

    if _provider() == "openai":
        resp = _openai_client().responses.parse(
            model=cfg["scoring_model"], instructions=_SCORING_SYSTEM,
            input=prompt, text_format=ScoreResult,
        )
        return resp.output_parsed

    client = _anthropic_client()
    resp = client.messages.parse(
        model=cfg["scoring_model"],
        max_tokens=cfg["scoring_max_tokens"],
        system=_SCORING_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ScoreResult,
    )
    return resp.parsed_output


_DOCS_SYSTEM = """You tailor resumes and cover letters. STRICT RULES:
- NEVER fabricate experience, metrics, employers, dates, or skills.
- Only reselect, reorder, and rephrase bullets from the provided experience bank.
- Only use numbers that appear verbatim in the experience bank.
- Match keywords from the job description where honest to do so.
Output plain markdown."""


def generate_document(kind: str, jd_text: str, bank_text: str, base_resume_text: str) -> str:
    if not llm_available():
        raise RuntimeError(
            "No LLM backend available — set OPENAI_API_KEY, ANTHROPIC_API_KEY, or configure Ollama"
        )
    cfg = settings()["llm"]
    task = (
        "Produce a tailored one-page RESUME in markdown (name/contact header, sections, bullets)."
        if kind == "resume"
        else "Produce a tailored one-page COVER LETTER in markdown."
    )
    content = (
        f"{task}\n\nJOB DESCRIPTION:\n{jd_text[:8000]}\n\n"
        f"BASE RESUME (structure/format reference):\n{base_resume_text[:6000]}\n\n"
        f"EXPERIENCE BANK (sole source of truth for content):\n{bank_text[:60000]}"
    )

    if _provider() == "ollama":
        resp = httpx.post(
            f"{_ollama_host()}/api/chat",
            json={
                "model": cfg["documents_model"],
                "messages": [
                    {"role": "system", "content": _DOCS_SYSTEM},
                    {"role": "user", "content": content},
                ],
                "stream": False,
                "options": {"num_predict": cfg["documents_max_tokens"]},
            },
            timeout=300.0,
        )
        resp.raise_for_status()
        return _strip_thinking(resp.json()["message"]["content"])

    if _provider() == "openai":
        resp = _openai_client().responses.create(
            model=cfg["documents_model"], instructions=_DOCS_SYSTEM,
            input=content, max_output_tokens=cfg["documents_max_tokens"],
        )
        return resp.output_text.strip()

    client = _anthropic_client()
    with client.messages.stream(
        model=cfg["documents_model"],
        max_tokens=cfg["documents_max_tokens"],
        system=_DOCS_SYSTEM,
        messages=[{"role": "user", "content": content}],
    ) as stream:
        return "".join(t for t in stream.text_stream)
