# Job Application Pipeline

Automated, agent-based job discovery, scoring, tracking, and document generation,
built on top of the **Career Command Center** Notion workspace.

You maintain one thing: a list of company names in Notion. Everything else —
finding their open roles, deduping, scoring fit, categorizing by career track,
recommending a resume, tracking your pipeline, nudging you on follow-ups, and
generating tailored documents — is handled by independent agents in this repo.

See `docs/ARCHITECTURE.md` for the full design rationale. This file is the
practical setup + operations guide.
## How it works, in one paragraph

Add a company name to the **Companies** database in Notion. The **ATS
Resolver** figures out where that company posts jobs (Greenhouse, Lever,
Ashby, or Workday) and caches it. Every 4 hours, the **discovery** agents
pull that company's open roles, a **dedup** pass drops anything already
seen, and a **scoring** pass rates fit against your profile, assigns a
career track, and recommends a resume — writing the survivors into the
**Opportunities** database. Daily, a **tracking** pass flags stale
applications, a **CRM** pass surfaces contacts due for follow-up, and a
**Daily Digest** page in Notion is rebuilt with what needs your attention.
Weekly, an **analytics** pass writes funnel metrics (response/interview/offer
rate). Tailored resumes and cover letters are generated **on demand only**,
never automatically.

## Prerequisites

- Python 3.12+ (repo was built/tested against 3.13)
- A Notion integration token with access to the Career Command Center workspace
- (Optional, but needed for real scoring/document generation) an Anthropic API key

## Setup

```bash
cd ~/Desktop/roadmap/job-pipeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Create `.env` in the repo root (never commit this file):

```
NOTION_TOKEN=ntn_...
OPENAI_API_KEY=sk-...
```

- **NOTION_TOKEN**: from [notion.so/profile/integrations](https://www.notion.so/profile/integrations).
  The integration must be connected to the Career Command Center page (page
  `•••` menu → Connections → add your integration).
- **OPENAI_API_KEY**: from the OpenAI API dashboard. Without this, scoring
  falls back to a flat rule-based score (55/100, no real fit analysis) and
  document generation (`agents/documents.py`) will refuse to run.

Then run the one-time schema upgrade (idempotent — safe to re-run anytime):

```bash
.venv/bin/python scripts/upgrade_notion_schema.py
```

This adds the automation fields the template didn't already have (ATS
resolution fields on Companies, a Track field on Opportunities, proper date
fields on the CRM, a `Pipeline Metrics` database, and `Daily Digest` /
`System Health` pages), without touching your existing data.

## Configuration

All tunable behavior lives in `config/*.yaml` — no code changes needed to adjust:

| File | Controls |
|---|---|
| `config/settings.yaml` | Notion database IDs, LLM model choice, scoring thresholds, schedule-adjacent settings |
| `config/profile.yaml` | Your background/skills/preferences — what the scoring agent measures fit against. **Review and correct this** — it was auto-extracted from your Experience Bank and may need adjustment. |
| `config/search_terms.yaml` | Per-track title keywords (Software Engineering, Product, Quant, IB, FinTech, Data/ML) and global seniority-exclusion terms (e.g. "Senior", "Director") |
| `config/recipes.yaml` | Manual scrape recipes for companies the ATS Resolver can't auto-detect (flagged "Needs Manual Recipe" in Notion) |

The **company list is not a config file** — it lives entirely in the Notion
Companies database, by design, so you can add one from your phone.

## Running it

Everything goes through `orchestrator/runner.py`:

```bash
.venv/bin/python -m orchestrator.runner <subcommand>
```

| Subcommand | What it does |
|---|---|
| `resolve` | ATS Resolver: detect each new/unresolved company's job board |
| `discover` | Pull jobs from resolved companies → dedup → score → write to Opportunities |
| `track` | Flag stale/ghosted applications (additive Notes flag, never auto-changes Status) |
| `crm` | List contacts due for a follow-up (read-only) |
| `digest` | Rebuild the "Daily Digest" Notion page (due follow-ups, shortlisted roles, flags) |
| `health` | Rebuild the "System Health" Notion page from the local run ledger; alerts on failures |
| `analytics` | Compute and write one weekly funnel-metrics row |
| `full` | Run `resolve` → `discover` → `track` → `crm` → `digest` → `health`, isolating failures per step |

On-demand document generation (never runs automatically):

```bash
.venv/bin/python -m agents.documents <opportunity_page_id> [--resume-only|--cover-letter-only]
```
Pass the Notion page ID of a row in the Opportunities database (the last
segment of its Notion URL). Output lands in `output/{company}_{role}/`.

### Automating the schedule

```bash
chmod +x orchestrator/launchd/install.sh orchestrator/launchd/uninstall.sh
./orchestrator/launchd/install.sh
```

Installs three `launchd` jobs (macOS): discovery every 4 hours, the daily
track→crm→digest→health chain at 8am, and analytics weekly on Sundays at
9am. Logs go to `logs/`. Run `uninstall.sh` to remove them.

Without this step, nothing runs unless you invoke `orchestrator.runner`
yourself — that's a fine way to operate too if you'd rather stay hands-on.

## Adding companies

In Notion, add a row to **Companies** with just a `Company Name`. Nothing
else is required. On the next `resolve` run:

- **Resolved** — the ATS Resolver found a Greenhouse/Lever/Ashby board (or
  fingerprinted a Workday tenant from the company's careers page). Its
  `Resolution Status`, `ATS Type`, and `ATS Endpoint` fields get filled in
  automatically, and `discover` will start pulling its jobs every cycle.
- **Needs Manual Recipe** — none of the above worked (usually a fully custom
  careers site). Add an entry to `config/recipes.yaml` with CSS selectors
  for that company's job listings; see the example schema in that file.

Check the `Paused` checkbox on a company to stop polling it without deleting it.

## Architecture notes

- **Modular agents, Notion as the only shared state.** Every agent
  (`agents/*.py`) reads/writes only through `core/notion_store.py` and a
  local SQLite mirror (`core/local_store.py`, dedup index + run ledger) —
  never through in-memory coupling to another agent. Any agent can be run,
  fail, or be replaced independently.
- **Cost-tiered LLM usage.** A free rule-based filter
  (`config/search_terms.yaml`) screens out obvious non-fits before any LLM
  call. Bulk fit-scoring uses Claude Haiku (cheap); document generation uses
  a stronger model. See `settings.yaml` → `llm` to change models.
- **Notion I/O uses raw HTTP, not the `notion-client` SDK.** The installed
  SDK version (3.x) targets Notion's newer multi-data-source API and
  silently drops database properties on `update`/`create` calls against
  this workspace's schema. `core/notion_store.py` talks to the REST API
  directly, pinned to `Notion-Version: 2022-06-28`, which the workspace
  supports correctly. If you see property-related failures after a `pip`
  upgrade, this is the first thing to check.
- **Documents never fabricate.** `agents/documents.py` only reselects and
  rephrases content already present in your Experience Bank
  (`Final_Experience_Bank.docx`) — it will not invent employers, metrics, or
  skills.

## Troubleshooting

- **`RuntimeError: NOTION_TOKEN not set`** — add it to `.env` in the repo root.
- **A company stays "Pending" after `resolve`** — check `logs/` (if launchd
  is installed) or stderr for a `notify()` message; it likely needs a manual
  recipe (see above).
- **Scores are all a flat 55** — no `ANTHROPIC_API_KEY` is set, or
  `settings.yaml` → `scoring.llm_batch_limit` was hit for that run. Add the
  key and re-run `discover`, or increase the batch limit.
- **Check what actually ran and when** — `python -m orchestrator.runner health`
  rebuilds the System Health Notion page from the local run ledger
  (`data/pipeline.db`, `runs` table).
- **Something looks wrong in Notion and you want to inspect raw data** —
  `core/notion_store.py` exposes `query_database`, `get_database`, and
  `plain()` for quick one-off scripts; see `scripts/upgrade_notion_schema.py`
  for usage examples.

## Repository layout

```
job-pipeline/
├── README.md                  # this file
├── requirements.txt
├── .env                        # secrets (gitignored) — NOTION_TOKEN, OPENAI_API_KEY
├── config/
│   ├── settings.yaml           # DB IDs, model choice, thresholds
│   ├── profile.yaml            # your background — scoring measures fit against this
│   ├── search_terms.yaml       # per-track keywords + seniority excludes
│   ├── recipes.yaml            # manual scrape recipes (unresolved companies)
│   └── notion_ids.yaml         # generated by upgrade_notion_schema.py — do not hand-edit
├── core/
│   ├── config.py                # settings/profile/search_terms loaders, .env
│   ├── models.py                 # JobPosting, ScoreResult, Company (pydantic)
│   ├── notion_store.py           # all Notion I/O (raw HTTP, rate-limited)
│   ├── local_store.py            # SQLite: dedup index, ATS resolution cache, run ledger
│   ├── llm.py                    # Claude client: score_job(), generate_document()
│   └── alerts.py                 # notify() — log + macOS notification
├── agents/
│   ├── discovery/
│   │   ├── base.py                # shared HTTP client, slug generation
│   │   ├── resolver.py            # ATS Resolver agent
│   │   ├── greenhouse.py, lever.py, ashby.py, workday.py   # per-ATS adapters
│   │   ├── careers_page.py        # manual-recipe scraper
│   │   └── runner.py              # discover_all() — orchestrates all adapters
│   ├── dedup.py                   # cross-source + fuzzy duplicate detection
│   ├── scoring.py                 # two-stage rule+LLM scoring, track + resume assignment
│   ├── pipeline.py                # glue: discover_all → dedupe → score_and_publish
│   ├── tracking.py                # application status hygiene
│   ├── crm.py                     # follow-up due-date surfacing
│   ├── analytics.py               # weekly funnel metrics
│   └── documents.py               # on-demand tailored resume/cover letter generation
├── orchestrator/
│   ├── runner.py                  # CLI entry point (all subcommands)
│   └── launchd/
│       ├── install.sh / uninstall.sh
├── scripts/
│   └── upgrade_notion_schema.py   # one-time (idempotent) Notion schema setup
├── templates/                     # resume/cover-letter docx templates (future use)
├── tests/
├── data/                          # SQLite mirror (gitignored)
├── logs/                          # launchd job output (gitignored)
└── output/                        # generated documents (gitignored)
```
