# AI-Powered Job Application Pipeline — Architecture Plan

**Owner:** James Lako
**Status:** DRAFT — awaiting approval before implementation
**Date:** 2026-07-08

---

## 1. Goals

Reduce manual work across the full job-search lifecycle:

1. **Discover** — continuously pull postings from company career pages and major ATS platforms.
2. **Evaluate** — dedupe, score fit against James's background, categorize by career track.
3. **Track** — single Notion dashboard from discovery → applied → interview → offer/rejection.
4. **Prepare** — recommend the right resume version; generate tailored resumes and cover letters on request.
5. **Network** — CRM for recruiters/alumni/referrals with automated follow-up reminders.
6. **Learn** — analytics on volume, response rate, interview rate, offer rate.

**Design principles:** modular agents, each independently runnable and testable; Notion is the single source of truth; automation and reliability over cleverness; every agent idempotent so re-runs are always safe.

---

## 2. Honest Constraints (read before approving)

| Constraint | Impact | Mitigation |
|---|---|---|
| **LinkedIn has no public jobs API** and scraping violates its ToS; accounts get banned. | Can't reliably automate LinkedIn as a source. | Treat LinkedIn as a *manual-capture* source: a "quick add" CLI/shortcut that takes a pasted URL and auto-enriches it. Cover the same postings via ATS APIs (most LinkedIn postings mirror a Greenhouse/Lever/Workday posting) and aggregator APIs (Adzuna, Google Jobs via SerpAPI — both have legitimate APIs with free tiers). |
| **Workday has no official public API.** Each company exposes a semi-public `/wday/cxs/.../jobs` JSON endpoint with a per-company URL. | Works well but needs a per-company config entry and occasionally breaks. | Config-driven adapter with per-company entries; failures alert but never block other sources. |
| **Greenhouse & Lever have official public job-board JSON APIs.** | Best sources — stable, legal, no auth. | Build these first. |
| **Notion API rate limit** is ~3 requests/sec; queries paginate at 100 rows. | Bulk writes are slow. | Local SQLite mirror for dedup/lookups; only deltas are written to Notion. |
| **LLM scoring costs money.** | ~200 new jobs/day scored with Claude ≈ a few dollars/day if naive. | Two-stage funnel: cheap keyword/embedding pre-filter kills obvious non-fits; only survivors get full LLM scoring with Haiku; borderline/high scores optionally re-scored with a stronger model. Est. **< $10/month**. |
| Only one resume version exists today (`James_Lako_SWE.docx`). | Resume recommender needs PM / Quant / IB variants. | Phase 4 generates the missing base variants from `Final_Experience_Bank.docx` for your review; recommender then maps track → variant. |

---

## 3. System Overview

```
                        ┌─────────────────────────────────────────────┐
                        │                ORCHESTRATOR                  │
                        │   (scheduler + run ledger + error alerts)    │
                        └─────┬───────┬───────┬───────┬───────┬───────┘
                              │       │       │       │       │
   ┌──────────────┐     ┌────▼───┐ ┌─▼────┐ ┌▼─────┐ ┌▼─────┐ ┌▼────────┐
   │  SOURCES     │     │Discovery│ │Dedup │ │Score │ │Track │ │Analytics│
   │ Greenhouse   │────▶│ Agents  │▶│Agent │▶│Agent │ │Agent │ │ Agent   │
   │ Lever        │     └────────┘ └──────┘ └──┬───┘ └──▲───┘ └─────────┘
   │ Workday      │                            │        │
   │ Careers pages│     ┌─────────────┐   ┌────▼────┐   │   ┌───────────┐
   │ Adzuna/SerpAPI│    │ CRM +       │   │ Resume  │   │   │ Document  │
   │ Manual capture│    │ Follow-up   │   │Recommend│   │   │ Generator │
   └──────────────┘     │ Agent       │   └─────────┘   │   │(on demand)│
                        └──────┬──────┘                 │   └─────┬─────┘
                               │        ┌───────────────┴─────────▼──┐
                               └───────▶│      NOTION WORKSPACE       │
                                        │ Opportunities · Companies · │
                                        │ Contacts · Interactions ·   │
                                        │ Documents · Metrics ·       │
                                        │ Dashboard views             │
                                        └────────────────────────────┘
                        Local: SQLite mirror (dedup index, run ledger, cache)
```

---

## 4. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | Best library ecosystem for scraping, Notion, docx, LLMs; easy to maintain. |
| Notion | `notion-client` (official SDK) | Primary DB + dashboard per requirement. |
| HTTP | `httpx` + `tenacity` (retries) | Async-capable, robust retry/backoff. |
| Parsing | `selectolax`/`BeautifulSoup`, `playwright` only where a careers page is JS-rendered | Keep the heavy browser dependency isolated to one adapter. |
| LLM | **Claude API** (`anthropic` SDK) — Haiku for bulk scoring, Sonnet for document generation | Cost-tiered by task difficulty. |
| Local state | **SQLite** (stdlib) | Dedup index + run ledger without adding infra. |
| Documents | `python-docx` + docx templates | Generates .docx resumes/cover letters matching your existing format. |
| Validation | `pydantic` v2 models | One `JobPosting` schema every adapter must emit — this is what makes agents modular. |
| Scheduling | **launchd** on your Mac (Phase 1) → optional **GitHub Actions cron** (later) | Start with zero infra; migrate to cloud only if you want it running while the laptop is closed. |
| Config | `config/*.yaml` + `.env` for secrets | Adding a company = one YAML line, no code. |

---

## 5. Notion Workspace Design

Six databases plus dashboard pages. All created programmatically by a one-time `setup_notion.py` script.

### 5.1 Opportunities (core DB)
| Property | Type | Notes |
|---|---|---|
| Title | title | `{Company} — {Role}` |
| Company | relation → Companies | |
| Role Title | text | raw title from posting |
| Track | select | SWE · Product · Quant Finance · Investment Banking · Data/ML · Other |
| Fit Score | number (0–100) | from Scoring Agent |
| Score Rationale | text | 2–3 bullet LLM explanation |
| Status | status | Discovered → Screened Out / Shortlisted → Applied → OA/Phone → Interview → Final → Offer / Rejected / Ghosted / Withdrawn |
| Recommended Resume | select | SWE · PM · Quant · IB · Custom |
| Location | text | + `Remote?` checkbox |
| Salary Range | text | when posted |
| Source | select | Greenhouse · Lever · Workday · Careers Page · Adzuna · Google Jobs · Manual |
| URL | url | canonical application link |
| Posted / Discovered / Applied / Closed dates | date | |
| Deadline | date | drives reminder agent |
| Dedup Key | text | hidden; canonical hash |
| JD Summary | text | LLM 3-line summary |
| Contacts | relation → Contacts | referrals/recruiters attached to this role |
| Documents | relation → Documents | |

### 5.2 Companies — **this is the list you maintain**
Add a row with just a **Name** and the system handles the rest (see §6.1 ATS Resolver).
Name · Tier (Target/Reach/Backup) · Industry · **Resolution Status** (Pending → Resolved / Needs manual recipe) · ATS type + endpoint (auto-filled by Resolver) · Careers URL (optional hint) · Active? (uncheck to pause polling) · Notes · Alumni present? · relations to Opportunities/Contacts.

### 5.3 Contacts (CRM)
Name · Type (Recruiter / Alumni / Referral / Hiring Manager / Peer) · Company relation · Email/LinkedIn · Relationship Strength (1–5) · Last Contacted · **Next Follow-up (date — drives reminders)** · Cadence (e.g., every 3 weeks) · Intro Source · Notes · relations to Opportunities/Interactions.

### 5.4 Interactions
Log of every touch: Contact relation · Date · Channel (Email/LinkedIn/Call/Coffee) · Direction · Summary · Outcome · Next Action. The Follow-up Agent reads this to compute nudges.

### 5.5 Documents
Name · Type (Resume/Cover Letter) · Opportunity relation · Version · File link (local path + optional Notion file upload) · Generated date · Model used.

### 5.6 Metrics (analytics rollup)
One row per week, written by the Analytics Agent: discovered · shortlisted · applied · responses · interviews · offers · response rate · interview rate · offer rate · median days-to-response. Powers a trends dashboard without fighting Notion formula limits.

### 5.7 Dashboard pages (Notion views)
- **Mission Control:** Shortlisted (score ≥ 70, not applied) sorted by score/deadline; This Week's Applications; Follow-ups due; Upcoming deadlines.
- **Pipeline board:** Opportunities grouped by Status (kanban).
- **By Track:** galleries filtered per career path.
- **Networking:** Contacts due for follow-up; recent interactions.
- **Analytics:** Metrics DB views + weekly summary page the agent writes.

---

## 6. Agent Catalog

Every agent is a standalone module with a CLI entry point (`python -m agents.discovery run`), shared `core/` utilities, structured JSON logging, and a row in the run ledger. Agents communicate **only through Notion + SQLite** — no in-memory coupling, so each can run, fail, and be replaced independently.

### 6.1 Company-List Discovery Model

**The user-facing input is a single list of company names** — rows in the Notion Companies DB (add from anywhere, even your phone). Everything else is automatic.

**ATS Resolver agent** (runs when a company has no resolved endpoint, or its endpoint starts failing):
1. Probes predictable ATS API URLs with normalized slug variants, cheapest first:
   - Greenhouse: `boards-api.greenhouse.io/v1/boards/{slug}/jobs`
   - Lever: `api.lever.co/v0/postings/{slug}?mode=json`
   - Ashby: `api.ashbyhq.com/posting-api/job-board/{slug}`
2. If no probe hits: fetches the company's careers page and fingerprints the ATS from the HTML (links/embeds to `greenhouse.io`, `lever.co`, `ashbyhq.com`, `myworkdayjobs.com` → derives the Workday CXS JSON endpoint from the tenant URL).
3. Writes the resolution (ATS type + endpoint) back to the company's Notion row and caches it in SQLite — **detection runs once per company, ever**, then re-runs only if the endpoint 404s (e.g., ATS migration).
4. Unresolvable companies (fully custom careers site) are flagged **"Needs manual recipe"** in Notion — never a silent failure; a per-company scrape recipe (CSS selectors in YAML, Playwright fallback for JS-rendered pages) covers these.

**Discovery adapters** (one per ATS) then poll each company's resolved JSON endpoint every cycle — one request returns all open jobs for that company, no scraping. ~100 companies ≈ ~100 HTTP requests ≈ seconds per cycle.

**Supplementary sources:**
- **Aggregator adapter** — Adzuna API + Google Jobs (SerpAPI free tier), keyed by per-track search terms; catches postings at companies not on your list.
- **Manual capture** — `jobadd <url>` CLI: paste any URL (incl. LinkedIn), it fetches/asks-for the JD, enriches, and inserts. Keeps LinkedIn in-scope without ToS violation.

All adapters emit the same pydantic `JobPosting` model → **adding a new source in the future = one new adapter file.** Per-company results are filtered by track keyword sets (SWE, PM, quant, IB in config) before scoring.

### 6.2 Dedup Agent
Runs on every new batch before anything hits Notion:
1. **Canonical key:** `normalize(company) + normalize(title) + normalize(location)` — catches the same job from two sources.
2. **URL canonicalization** — strips tracking params, resolves redirects.
3. **Fuzzy pass:** `rapidfuzz` title similarity ≥ 92 within same company → duplicate.
4. Duplicates merge (keep earliest, union sources) rather than delete, so source coverage stats stay accurate.
SQLite holds the index; Notion never sees a duplicate.

### 6.3 Scoring & Categorization Agent
- **Profile:** `config/profile.yaml` — skills, experience summary, target tracks, seniority, location/comp preferences — seeded from your Experience Bank and Projects Bank docs (I'll extract this during implementation and you review it).
- **Stage 1 (free):** rule-based filter — wrong seniority, hard location mismatch, excluded keywords → `Screened Out`, no LLM call.
- **Stage 2 (Claude Haiku):** rubric scoring → subscores (skills match, experience level, track alignment, company tier, growth) → weighted 0–100 + 3-bullet rationale + **Track** classification + **Recommended Resume** (track → resume variant map, with `Custom` flagged when the JD straddles tracks).
- Thresholds: ≥ 70 auto-`Shortlisted`, 40–69 stays `Discovered` for manual triage, < 40 `Screened Out`.

### 6.4 Document Generator (on demand, never automatic)
- `generate --opportunity <id> [--resume] [--cover-letter]` or by ticking a "Generate Docs" checkbox in Notion that the agent polls.
- Pulls JD + your Experience/Projects Bank content → Claude Sonnet selects and rewrites the most relevant bullets under strict rules: **never fabricate; only rephrase/reorder existing bullets; quantify only with numbers already in the bank.**
- Outputs `.docx` from a template matching your current resume format → saved to `output/{company}_{role}/`, logged in the Documents DB, linked to the Opportunity.
- Phase 4 also produces the missing PM / Quant / IB **base** resume variants for your one-time review.

### 6.5 Tracking Agent
- Status lives in Notion (you drag cards); the agent handles hygiene: stamps `Applied date` when status → Applied, flags `Ghosted` after N days of silence, closes out expired postings (checks if the posting URL is still live), and detects postings that disappeared (likely filled).

### 6.6 CRM & Follow-up Agent
- Daily scan of Contacts + Interactions: computes who's due (per-contact cadence or explicit Next Follow-up date), post-application nudges ("applied 7 days ago, no response — ping the recruiter"), pre-deadline warnings, thank-you-note reminders after logged interviews.
- Reminders land as: items on the Mission Control "Due Today" view + a **daily digest** (macOS notification + a Notion "Today" page; email optional later).

### 6.7 Analytics Agent
- Weekly (and on demand): computes funnel metrics overall and per Track/Source/Resume version → writes a Metrics row + a short written summary ("Your response rate on Quant roles is 2× SWE; Greenhouse sources convert best").

### 6.8 Orchestrator
- Thin scheduler (launchd plists) + shared run ledger in SQLite: every run records start/end/status/error/items processed.
- Failure policy: per-adapter isolation (one broken source never blocks the pipeline), exponential backoff via `tenacity`, alert into a Notion "System Health" page + macOS notification after repeated failures.
- Everything idempotent: re-running any agent is always safe.

**Schedule:** Discovery + Dedup + Scoring every 4 hours · Tracking + CRM daily 8am · Analytics weekly Sunday · Document generation on demand.

---

## 7. Repository Layout

```
job-pipeline/
├── README.md                  # setup + operations guide
├── pyproject.toml
├── .env.example               # NOTION_TOKEN, ANTHROPIC_API_KEY, ADZUNA_*, SERPAPI_KEY
├── config/
│   ├── profile.yaml           # your background, tracks, preferences, scoring weights
│   ├── recipes.yaml           # scrape recipes ONLY for "Needs manual recipe" companies
│   ├── search_terms.yaml      # per-track keyword sets
│   └── settings.yaml          # thresholds, schedules, model choices
│   # NOTE: the company list itself lives in the Notion Companies DB, not in config —
│   # the ATS Resolver auto-detects each company's job board endpoint from its name
├── core/
│   ├── models.py              # JobPosting, Contact, ScoreResult (pydantic)
│   ├── notion_store.py        # all Notion I/O (single choke point, rate-limited)
│   ├── local_store.py         # SQLite: dedup index, run ledger, cache
│   ├── llm.py                 # Claude client, prompt templates, cost tracking
│   └── alerts.py
├── agents/
│   ├── discovery/             # base.py + greenhouse.py, lever.py, workday.py,
│   │                          #   careers_page.py, aggregators.py, manual.py
│   ├── dedup.py
│   ├── scoring.py
│   ├── documents.py
│   ├── tracking.py
│   ├── crm.py
│   └── analytics.py
├── orchestrator/
│   ├── runner.py              # CLI: run any agent or full pipeline
│   └── launchd/               # plist templates + install script
├── templates/                 # resume_swe.docx, resume_pm.docx, ..., cover_letter.docx
├── scripts/
│   ├── setup_notion.py        # one-time: creates all 6 DBs + dashboard pages
│   └── build_profile.py       # extracts profile.yaml from your Experience Bank docx
├── tests/                     # per-agent unit tests w/ fixture payloads
└── output/                    # generated documents (gitignored)
```

---

## 8. Implementation Roadmap

| Phase | Deliverable | You can start using it when done? |
|---|---|---|
| **0. Foundation** (½ day) | Repo scaffold, pydantic models, Notion + SQLite stores, `setup_notion.py` creates all databases and dashboard shells, `.env` wiring. | Notion workspace exists. |
| **1. Discovery + Dedup** (1–1.5 days) | **ATS Resolver** (auto-detects Greenhouse/Lever/Ashby/Workday from a company name), Greenhouse + Lever + Ashby adapters, dedup agent, manual-capture CLI, orchestrator + launchd schedule, run ledger + alerts. You seed the Companies DB with names. | **Yes — add a company name in Notion, jobs flow in automatically.** |
| **2. Scoring & Categorization** (1 day) | `build_profile.py` (you review the extracted profile), two-stage scoring, track classification, resume recommendation, Mission Control views become meaningful. | **Yes — ranked shortlist daily.** |
| **3. Tracking + CRM + Reminders** (1 day) | Tracking hygiene agent, Contacts/Interactions workflows, follow-up engine, daily digest. | **Yes — full lifecycle tracking.** |
| **4. Document Generation** (1 day) | docx templates from your current resume; generate PM/Quant/IB base variants for your review; on-demand tailored resume + cover letter generation. | **Yes — tailored docs on request.** |
| **5. Analytics** (½ day) | Metrics DB rollups, weekly summary, per-track/source/resume conversion analysis. | Yes. |
| **6. Extended sources** (1 day) | Workday adapter (+ your target companies configured), careers-page scraper w/ Playwright fallback, Adzuna/SerpAPI aggregators. | Yes — broader coverage. |

Each phase ends with its tests passing and a short usage note added to README. Phases 5 and 6 can swap depending on what you want sooner.

---

## 9. Assumptions to Confirm

1. **Runs locally on your Mac** via launchd (no cloud infra to start). If you want 24/7 discovery independent of your laptop, we add a GitHub Actions cron variant in Phase 6 — the code is structured to support both.
2. **LinkedIn via manual capture + ATS/aggregator mirrors**, not scraping (ToS). 
3. **API keys you'll need:** Notion integration token, Anthropic API key; optional free-tier Adzuna and SerpAPI keys for Phase 6.
4. **Estimated running cost:** < $10/month in LLM usage at ~100–200 discovered jobs/day (most filtered before any LLM call); document generation pennies per doc.
5. Generated documents **never fabricate experience** — they only reselect/rephrase content from your Experience & Projects Banks.
6. Target companies list: lives in the Notion Companies DB — you add a row with just a company name and the ATS Resolver does the rest. I'll seed a starter set per track; you add/remove/pause companies anytime from Notion.
