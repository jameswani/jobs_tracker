# Autonomous Apply & Knowledge Vault — Project Specification v2

**Owner:** James Lako
**Status:** DRAFT — scoping decisions made (§0), architecture not yet built
**Companion docs:** `docs/ARCHITECTURE.md` (the discovery/scoring/tracking pipeline this extends), `pipeline-frontend/ARCHITECTURE.md` (the UI this plugs into)
**Date:** 2026-07-13

---

## 0. Decisions already made

| Question | Decision |
|---|---|
| How autonomous is "hit apply"? | **Tiered.** Where the system *can* submit directly (predictable/API-capable platforms), it does. Everywhere else, it fills out the entire form and stops — the user creates the portal account themselves (one-time, per company) and clicks the final submit. |
| How does the Knowledge Vault get populated? | **Both, in sequence.** Upload existing documents (resume/CV/Experience Bank/LinkedIn export) → LLM extracts structured entries → user reviews/corrects in a form. The same form also covers anything the documents didn't mention. |

Everything below is designed around these two decisions.

---

## 1. Goals

1. **Vault** — capture the user's full history (experience, projects, skills, conferences, citations, lectures, presentations, leadership roles) as structured, queryable data — not a single prose document.
2. **Targeting** — user states what roles/companies they want; system generates tailored resumes/cover letters from the vault and finds matching postings (this is the existing pipeline, extended to pull from the vault instead of one fixed docx).
3. **Browse & approve** — user reviews matches and approves the ones they want to pursue.
4. **Apply** — system submits directly where it safely can; otherwise fills the entire application and hands off for one final human click.
5. **Track** — dashboard status updates itself as responses arrive, by reading the user's inbox.
6. **Zero-touch** — the only recurring human input should be: approve a match, click submit where required, and occasionally create an account on a new portal.

---

## 2. Honest Constraints (read before approving)

| Constraint | Impact | Mitigation |
|---|---|---|
| **Auto-submission legality/bot-detection varies wildly per ATS.** Some platforms' terms prohibit automated submission; Workday in particular actively fingerprints bot behavior. | A generic form-filler that submits everywhere is a real ban/legal-risk surface. | The tiering decision in §0 exists specifically for this: only ever direct-submit where a documented, sanctioned path exists (an actual application API, confirmed per company — never assumed just because a company uses Greenhouse/Lever). Everywhere else: fill, don't submit. |
| **Voluntary self-identification questions (race, gender, veteran, disability status) are legally sensitive.** | Guessing or auto-filling these from inferred data would be a real harm, not just a bug. | Hard rule: these fields are **never** inferred or guessed. Filled only from an explicit, separately-consented "voluntary disclosures" section the user fills in themselves; otherwise select "decline to answer" if the form offers it, or leave blank. |
| **CAPTCHAs and anti-bot challenges appear on some submit flows.** | Attempting to solve/bypass these crosses from "personal automation" into abuse-tooling territory. | Hard rule: on CAPTCHA/anti-bot detection, abort the fill and route to a human-review queue. Never attempt to solve it. |
| **LLM extraction from uploaded documents can hallucinate or misattribute dates/numbers.** | A resume bullet with a fabricated metric is worse than no bullet. | Every extracted vault entry starts `verified: false`. The document generator (`agents/documents.py`) may only pull from `verified: true` entries — this is the existing "never fabricate" rule, now enforced at the data layer instead of just a prompt instruction. |
| **Inbox access is a high-sensitivity OAuth grant.** | Requesting broad mailbox access is a bigger ask than anything else in this system. | Request the narrowest scope available (Gmail read-only, ideally restricted further), never send or delete mail, per-user revocable token. |
| **Matching an inbound email to the right application isn't 100% reliable.** | A mis-filed "rejection" or missed interview invite is costly. | Low-confidence matches go to a review queue on the dashboard rather than being silently auto-filed. |
| **Portal accounts (Workday, Ashby, custom) must be created by the user, not the system.** (Per §0.) | The auto-apply engine can't proceed on Tier B platforms until an account exists. | The engine detects "no account on file for this portal" and surfaces a one-time "create an account at {company}" task before it will attempt to fill anything there. |

---

## 3. System Overview

```
                    ┌───────────────────────────────────────────────────┐
                    │              EXISTING PIPELINE (unchanged)         │
                    │   Discovery → Dedup → Scoring → Notion/SQLite      │
                    └───────────────────────┬───────────────────────────┘
                                             │ matched opportunities
                                             ▼
┌──────────────┐   uploads    ┌─────────────────────┐   verified entries   ┌──────────────────┐
│ User uploads  │────────────▶│  Vault Intake Agent  │──────────────────────▶│  Knowledge Vault  │
│ resume/CV/    │             │  (LLM extraction +   │                       │ (Experience ·     │
│ LinkedIn      │             │   review UI)         │◀──────────────────────│  Project · Skill · │
└──────────────┘             └─────────────────────┘   manual add/edit      │  Publication ·    │
                                                                              │  Talk · Leadership)│
                                                                              └─────────┬──────────┘
                                                                                        │ verified only
                                                                                        ▼
┌──────────────┐  approve    ┌──────────────────────┐   tailored docs      ┌──────────────────────┐
│  User browses │────────────▶│  Document Generator   │◀────────────────────│  Document Generator   │
│  matches      │             │  (extends documents.py)│                    │  pulls from vault      │
└──────┬───────┘             └───────────┬──────────┘                       └──────────────────────┘
       │                                  │ generated resume/cover letter
       ▼                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                      AUTO-APPLY AGENT                         │
│  Tier A: direct submit (confirmed API-capable portals)        │
│  Tier B: browser-fill, stop before submit (Workday/custom)    │
│          — requires user-created account, detected up front   │
│  Hard stops: CAPTCHA/anti-bot → human queue.                  │
│              Voluntary disclosures → never inferred.          │
└──────────────────────────────┬────────────────────────────────┘
                                │ ApplicationRecord
                                ▼
┌─────────────────────────────────────────────────────────────┐
│                     INBOX TRACKING AGENT                      │
│  Gmail OAuth (read-only) → classify each new message from a   │
│  known company/ATS domain → match to ApplicationRecord →       │
│  update status. Low-confidence matches → review queue.         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Data model additions (pydantic, alongside `core/models.py`)

```python
class VaultEntry(BaseModel):
    id: str
    kind: Literal["experience", "project", "skill", "publication", "talk", "leadership", "conference"]
    title: str
    organization: str = ""
    start_date: date | None = None
    end_date: date | None = None
    description: str = ""          # bullets, prose — the raw reusable content
    tags: list[str] = []            # track relevance: swe/pm/quant/ib/fintech/data-ml
    source: Literal["uploaded_doc", "manual"]
    source_doc: str | None = None   # which uploaded file this was extracted from, if any
    verified: bool = False          # documents.py may ONLY read verified=True entries

class VoluntaryDisclosure(BaseModel):
    """Explicit, separately-consented values only. Never inferred."""
    question_pattern: str           # e.g. "veteran status", matched against form question text
    answer: str                     # or "decline to answer"

class ApplicationRecord(BaseModel):
    opportunity_id: str              # links to existing Notion Opportunities row
    portal: str                      # greenhouse | lever | workday | ashby | custom
    submission_tier: Literal["tier_a_direct", "tier_b_manual_click"]
    account_status: Literal["not_needed", "needs_account", "account_confirmed"]
    filled_at: datetime | None = None
    submitted_at: datetime | None = None
    submitted_by: Literal["system", "user"] | None = None
    blocked_reason: str | None = None   # e.g. "captcha_detected", "account_missing"

class InboundEmail(BaseModel):
    message_id: str
    received_at: datetime
    sender_domain: str
    matched_application_id: str | None = None
    classified_intent: Literal["rejection", "interview_invite", "oa_link", "offer", "other"] | None = None
    confidence: float = 0.0
    needs_review: bool = True
```

---

## 5. Agent catalog additions

### 5.1 Vault Intake Agent (new: `agents/vault.py`)
- Accepts uploaded resume/CV (.docx/.pdf) and optional LinkedIn export.
- LLM pass extracts candidate `VaultEntry` drafts (all `verified=False`) — one entry per experience/project/publication/talk/leadership role/conference, not one blob.
- Surfaces drafts in a review UI (onboarding "Vault" step, see §6) where the user edits and marks each `verified=True`.
- Manual "add entry" path bypasses extraction entirely for anything the documents didn't cover.

### 5.2 Document Generator (extends existing `agents/documents.py`)
- Same non-negotiable rule already in place today ("never fabricate; only rephrase/reorder existing bullets; quantify only with numbers already in the bank") — now scoped to `VaultEntry`s where `verified=True`, replacing the single hardcoded `_BASE_RESUME_PATH`/`_BANK_PATH` files.
- Selects entries by `tags` matching the opportunity's track, same as today's track→resume mapping.

### 5.3 Auto-Apply Agent (new: `agents/autoapply/` package, one recipe module per ATS)
- **Tier A (direct submit):** only for portals with a *confirmed, documented* application-submission API — this must be verified per company during implementation, never assumed from the ATS vendor name alone. Some Greenhouse/Lever boards expose this; most don't by default.
- **Tier B (fill, don't submit):** Playwright-driven form fill for Workday/Ashby/custom career pages. Requires `account_status == "account_confirmed"` first — if not, the run stops and surfaces "create an account at {company}" as a one-time task instead of attempting anything.
- Fills every ordinary field from the Vault + generated documents (uploads resume/cover letter as files), then stops one step before the submit control and marks the `ApplicationRecord` "ready to review."
- **Hard stops, no exceptions:** CAPTCHA/anti-bot challenge detected → `blocked_reason="captcha_detected"`, route to human queue. Voluntary-disclosure question encountered with no matching `VoluntaryDisclosure` on file → leave blank/decline, never guess.

### 5.4 Inbox Tracking Agent (new: `agents/inbox.py`)
- Per-user Gmail OAuth, read-only scope.
- Polls for new mail from domains associated with an open `ApplicationRecord`'s company.
- LLM classifies intent (`rejection` / `interview_invite` / `oa_link` / `offer` / `other`) with a confidence score.
- High-confidence matches auto-update the linked Opportunity/Application status in Notion. Low-confidence matches land in a "needs review" queue — never silently filed.

---

## 6. Frontend touchpoints (extends `pipeline-frontend/ARCHITECTURE.md`)

- **Onboarding** gains a new step between "Profile" and "Resume & API key": **Vault** — upload documents, review/edit LLM-extracted entries, mark verified.
- New **Vault** screen (distinct from the existing Documents screen: Vault is source-of-truth *inputs*, Documents is generated *outputs*) — add/edit/delete entries anytime, not just during onboarding.
- **Opportunities/Applications** screens: the "Apply" action now branches by tier —
  - Tier A → button reads "Apply" → instant "Submitted" status, no further action.
  - Tier B → button reads "Fill application" → once done, status shows "Ready — finish on {Company}'s site" with a link/handoff to the filled browser session.
- New **"Needs your attention"** queue (likely lives on the Dashboard) surfacing: portals needing an account created, CAPTCHA-blocked fills, low-confidence email matches.

---

## 7. Repository layout additions

```
job-pipeline/
├── agents/
│   ├── vault.py                # intake + extraction
│   ├── autoapply/
│   │   ├── base.py             # shared recipe interface, tier dispatch
│   │   ├── greenhouse.py       # tier A where confirmed, else falls to tier B
│   │   ├── lever.py
│   │   ├── workday.py          # tier B only
│   │   └── ashby.py
│   └── inbox.py
├── core/
│   └── vault_store.py          # VaultEntry persistence (Notion DB or own table, per §7 of frontend doc's open fork)
```

---

## 8. Roadmap (extends the phase table in `docs/ARCHITECTURE.md`)

| Phase | Deliverable | Usable when done? |
|---|---|---|
| **7. Vault** | Upload/extraction pipeline, review UI, verified-only enforcement in `documents.py` | Yes — resumes/cover letters generated from real structured history instead of one docx |
| **8. Auto-Apply Tier A** | Direct-submit recipes for confirmed API-capable portals only | Yes, narrow — most applications still land in Tier B until more portals are confirmed |
| **9. Auto-Apply Tier B** | Playwright fill-and-pause for Workday/Ashby/custom, account-detection gate, CAPTCHA/disclosure hard stops | Yes — this is where most real applications get automated |
| **10. Inbox Tracking** | Gmail OAuth, classification, review queue | Yes — dashboard finally updates itself |

---

## 9. Assumptions to confirm before building

1. Which portals actually support Tier A direct submission needs verification per company, not assumed from "uses Greenhouse" — this determines how much of the workload really ends up Tier A vs Tier B.
2. Vault persistence layer (Notion DB vs own table) depends on the same architecture fork already open in `pipeline-frontend/ARCHITECTURE.md` §7 — not re-litigated here.
3. Gmail OAuth scope and consent flow needs its own review before any inbox code is written, given the sensitivity noted in §2.
