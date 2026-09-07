# How to Run This Thing

A plain-English walkthrough. If you just want to *use* the pipeline day-to-day,
you mostly need the "Everyday commands" and "Generate a resume" sections below.

## 0. One-time setup (skip if you've already done this)

Open Terminal and run:

```bash
cd ~/Desktop/roadmap/job-pipeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

You need a `.env` file in this folder with your secrets in it. Right now it
only has `NOTION_TOKEN` — **you also need to add `ANTHROPIC_API_KEY`**, or
scoring will just give every job a flat, meaningless 55/100, and resume/cover
letter generation will refuse to run entirely. Open `.env` and make it look
like:

```
NOTION_TOKEN=ntn_your_token_here
ANTHROPIC_API_KEY=sk-ant_your_key_here
```

Then, once ever (safe to re-run if you're not sure you did it):

```bash
.venv/bin/python scripts/upgrade_notion_schema.py
```

This just adds a few fields/pages to your Notion workspace that the
automation needs. It doesn't touch any of your existing data.

## 1. The one command you run for everything

All the day-to-day automation goes through one file, `orchestrator/runner.py`,
using this pattern:

```bash
.venv/bin/python -m orchestrator.runner <word>
```

You swap `<word>` for whatever step you want to run. Here's what each one does:

| Type this | What actually happens |
|---|---|
| `resolve` | Looks at any new company names you added in Notion and figures out where they post jobs |
| `discover` | Goes and grabs open roles from all your companies, removes duplicates, and scores each one for fit — the results show up in your Notion "Opportunities" table |
| `track` | Checks your existing applications and flags ones that have gone quiet |
| `crm` | Shows you which contacts you're overdue to follow up with |
| `digest` | Rebuilds the "Daily Digest" page in Notion — your one-stop "what needs my attention today" page |
| `health` | Rebuilds a "System Health" page in Notion so you can see what ran and what failed |
| `analytics` | Updates your weekly stats (response rate, interview rate, etc.) |
| `full` | Runs resolve → discover → track → crm → digest → health, all in one go, back to back |

**If you want to just run the whole thing manually right now and see what
happens**, this is the command:

```bash
.venv/bin/python -m orchestrator.runner full
```

That's the entire pipeline in one shot — new companies get resolved, new jobs
get pulled and scored, your applications get checked for staleness, and your
Notion Daily Digest gets refreshed.

## 2. How to generate a tailored resume / cover letter

This step is **never automatic on purpose** — you have to explicitly ask for
it, because it costs API money and you should decide when it's worth it.

Steps:

1. Open the job in your Notion "Opportunities" table.
2. Look at the URL in your browser's address bar. It'll end in a long string
   of letters/numbers — that's the page ID. Example:
   `https://notion.so/Some-Job-Title-**3710eeb6e01a8014abcd1234...**`
   Copy that last chunk (the ID).
3. Run:

```bash
.venv/bin/python -m agents.documents <paste the page ID here>
```

That generates **both** a resume and a cover letter. If you only want one:

```bash
.venv/bin/python -m agents.documents <page ID> --resume-only
.venv/bin/python -m agents.documents <page ID> --cover-letter-only
```

The finished files show up as plain markdown (`.md`) files in:

```
output/<Company>_<Role>/resume.md
output/<Company>_<Role>/cover_letter.md
```

Open those in any text editor, or paste into Word/Google Docs to format.

It writes content **only** from your real background — it pulls from two
files on your computer and never invents experience, employers, or numbers:

- Experience source: `~/Desktop/roadmap/Final_Experience_Bank.docx`
- Resume formatting reference: `~/Desktop/roadmap/Resume/James_Lako_SWE.docx`

If you ever move or rename either of those two files, resume generation will
break until you update the paths hardcoded near the top of
`agents/documents.py`.

## 3. Making it run by itself on a schedule (optional)

If you don't do this step, nothing runs unless you personally type a command
— which is a completely fine way to use this. But if you want it to run in
the background automatically (Mac only, using macOS's built-in scheduler
called `launchd`):

```bash
chmod +x orchestrator/launchd/install.sh orchestrator/launchd/uninstall.sh
./orchestrator/launchd/install.sh
```

This sets up three automatic schedules:

- **Every 4 hours** → pulls new jobs and scores them (`discover`)
- **Every day at 8:00am** → checks stale applications, follow-ups, and
  rebuilds your Daily Digest (`track` → `crm` → `digest` → `health`)
- **Every Sunday at 9:00am** → updates your weekly stats (`analytics`)

You don't need to keep Terminal open or your laptop plugged in at those exact
times for this to work — `launchd` is a background service macOS runs for you.
(Your Mac does need to be turned on / awake, though — it won't fire while it's
fully asleep.)

Logs of what ran (and any errors) get written to the `logs/` folder — check
there first if something seems off, or just run:

```bash
.venv/bin/python -m orchestrator.runner health
```

which rebuilds a "System Health" page in Notion summarizing recent runs.

**To turn the automatic schedule off:**

```bash
./orchestrator/launchd/uninstall.sh
```

Resume/cover letter generation is **never** part of the automatic schedule —
that always has to be triggered manually via the `agents.documents` command
above, on purpose.

## Quick troubleshooting

- **"NOTION_TOKEN not set"** → you forgot to fill in `.env`.
- **Every job scores exactly 55** → `ANTHROPIC_API_KEY` is missing from `.env`,
  or you've hit your scoring budget for the run (`config/settings.yaml` →
  `scoring.llm_batch_limit`).
- **A company just sits at "Pending" in Notion** → check the `logs/` folder
  (or your terminal output) — it usually means that company needs a manual
  recipe added to `config/recipes.yaml` because its careers site couldn't be
  auto-detected.
- **Not sure what's actually been running** → run
  `.venv/bin/python -m orchestrator.runner health` and check the Notion
  "System Health" page it builds.
