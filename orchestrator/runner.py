"""CLI entry point for the job-pipeline orchestrator.

Run with: python -m orchestrator.runner <command>

Each subcommand imports its target agent module inside the function body
(not at module scope) and guards the import with try/except ImportError.
Sibling agent modules are being built in parallel and may be missing or
broken at any given time; this file must stay import-safe and `--help`
must always work regardless of their state.
"""
from __future__ import annotations

import argparse
import subprocess
import time

from core.alerts import notify


def cmd_discover(_args: argparse.Namespace | None) -> None:
    try:
        from agents.pipeline import run_discovery_pipeline
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"discover: agents.pipeline unavailable ({exc})")
        return
    print(run_discovery_pipeline())


def cmd_open_jobs(args: argparse.Namespace) -> None:
    """Open a bounded batch of job URLs in the user's default browser."""
    import core.notion_store as notion_store

    rows = notion_store.query_database(
        notion_store.db_id("opportunities"),
        sorts=[{"property": "Date Found", "direction": "descending"}],
    )
    urls = []
    for row in rows:
        url = notion_store.plain(row["properties"].get("Job Posting URL", {}))
        if url and url not in urls:
            urls.append(url)
    batch = urls[args.offset:args.offset + args.limit]
    for url in batch:
        subprocess.Popen(["open", url])
        time.sleep(0.15)
    print(f"Opened {len(batch)} job URLs (offset={args.offset}, next offset={args.offset + len(batch)})")


def cmd_resolve(_args: argparse.Namespace | None) -> None:
    try:
        from agents.discovery.resolver import run
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"resolve: agents.discovery.resolver unavailable ({exc})")
        return
    print(run())


def cmd_track(_args: argparse.Namespace | None) -> None:
    try:
        from agents.tracking import run
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"track: agents.tracking unavailable ({exc})")
        return
    print(run())


def cmd_crm(_args: argparse.Namespace | None) -> None:
    try:
        from agents.crm import run
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"crm: agents.crm unavailable ({exc})")
        return
    print(run())


def cmd_analytics(_args: argparse.Namespace | None) -> None:
    try:
        from agents.analytics import run
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"analytics: agents.analytics unavailable ({exc})")
        return
    print(run())


def _digest_due_contacts() -> list[dict]:
    try:
        from agents.crm import due_contacts
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"digest: agents.crm unavailable ({exc})")
        return []
    return due_contacts()


def _digest_shortlisted() -> list[dict]:
    try:
        import core.notion_store as notion_store
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"digest: core.notion_store unavailable ({exc})")
        return []
    try:
        return notion_store.query_database(
            notion_store.db_id("opportunities"),
            filter={"property": "Status", "select": {"equals": "Shortlisted"}},
        )
    except Exception as exc:
        notify("Pipeline Orchestrator", f"digest: opportunities query failed ({exc})")
        return []


def _digest_needs_attention() -> list:
    try:
        from agents.tracking import run
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"digest: agents.tracking unavailable ({exc})")
        return []
    try:
        result = run() or {}
    except Exception as exc:
        notify("Pipeline Orchestrator", f"digest: tracking run failed ({exc})")
        return []
    return result.get("needs_attention", [])


def cmd_digest(_args: argparse.Namespace | None) -> None:
    try:
        import core.notion_store as notion_store
        from core.config import notion_ids
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"digest: core modules unavailable ({exc})")
        return

    due = _digest_due_contacts()
    shortlisted = _digest_shortlisted()
    needs_attention = _digest_needs_attention()

    lines: list[str] = ["## Due Follow-ups"]
    if due:
        for contact in due:
            name = contact.get("name") or contact.get("Name") or "Unknown contact"
            company = contact.get("company") or contact.get("Company") or ""
            lines.append(f"- {name} ({company})" if company else f"- {name}")
    else:
        lines.append("- None due.")

    lines.append("## Shortlisted Opportunities")
    if shortlisted:
        for row in shortlisted:
            props = row.get("properties", {})
            title = notion_store.plain(props.get("Role", {})) or "Untitled"
            lines.append(f"- {title}")
    else:
        lines.append("- None shortlisted.")

    lines.append("## Needs Attention")
    if needs_attention:
        for item in needs_attention:
            lines.append(f"- {item}")
    else:
        lines.append("- Nothing flagged.")

    notion_store.replace_page_content(notion_ids()["digest_page"], lines)
    print({"due": len(due), "shortlisted": len(shortlisted), "needs_attention": len(needs_attention)})


def cmd_health(_args: argparse.Namespace | None) -> None:
    try:
        from core.local_store import connect
        from core.config import notion_ids
        import core.notion_store as notion_store
    except ImportError as exc:
        notify("Pipeline Orchestrator", f"health: core modules unavailable ({exc})")
        return

    conn = connect()
    rows = conn.execute(
        "SELECT agent, started, finished, status, items, error FROM runs ORDER BY id DESC LIMIT 50"
    ).fetchall()
    conn.close()

    # First row seen per agent is the most recent one, since we sorted by id DESC.
    latest_by_agent: dict[str, tuple] = {}
    recent_errors: list[tuple] = []
    for agent, started, finished, status, items, error in rows:
        latest_by_agent.setdefault(agent, (started, finished, status, items, error))
        if status == "error":
            recent_errors.append((agent, started, error))

    lines: list[str] = ["## Agent Status"]
    if latest_by_agent:
        for agent, (started, _finished, status, items, _error) in sorted(latest_by_agent.items()):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(started))
            lines.append(f"- {agent}: {status} @ {ts} ({items} items)")
    else:
        lines.append("- No runs recorded yet.")

    lines.append("## Recent Errors")
    if recent_errors:
        for agent, started, error in recent_errors[:20]:
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(started))
            lines.append(f"- {agent} @ {ts}: {error}")
    else:
        lines.append("- None.")

    notion_store.replace_page_content(notion_ids()["health_page"], lines)

    for agent, (_started, _finished, status, _items, error) in latest_by_agent.items():
        if status == "error":
            notify("Pipeline Health", f"{agent} failed: {error}")

    print({"agents": len(latest_by_agent), "errors": len(recent_errors)})


def cmd_full(_args: argparse.Namespace | None) -> None:
    steps = (
        ("resolve", cmd_resolve),
        ("discover", cmd_discover),
        ("track", cmd_track),
        ("crm", cmd_crm),
        ("digest", cmd_digest),
        ("health", cmd_health),
    )
    for name, fn in steps:
        print(f"=== {name} ===", flush=True)
        # Agents are owned/built independently; a bug in one (e.g. resolver)
        # must never prevent later steps (e.g. digest, health) from running
        # in a scheduled cron-style invocation.
        try:
            fn(None)
        except Exception as exc:
            notify("Pipeline Orchestrator", f"full: {name} step failed ({exc})")
            continue


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orchestrator.runner", description="Job pipeline orchestrator CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover", help="Run discovery + dedup + scoring pipeline").set_defaults(func=cmd_discover)
    open_jobs = sub.add_parser("open-jobs", help="Open a batch of Notion job URLs in the default browser")
    open_jobs.add_argument("--limit", type=int, default=20, help="URLs to open (default: 20)")
    open_jobs.add_argument("--offset", type=int, default=0, help="How many URLs to skip (default: 0)")
    open_jobs.set_defaults(func=cmd_open_jobs)
    sub.add_parser("resolve", help="Run the ATS resolver").set_defaults(func=cmd_resolve)
    sub.add_parser("track", help="Run application tracking").set_defaults(func=cmd_track)
    sub.add_parser("crm", help="Run CRM due-contact check").set_defaults(func=cmd_crm)
    sub.add_parser("analytics", help="Run weekly analytics").set_defaults(func=cmd_analytics)
    sub.add_parser("digest", help="Build and publish the Daily Digest to Notion").set_defaults(func=cmd_digest)
    sub.add_parser("health", help="Build and publish the System Health report to Notion").set_defaults(func=cmd_health)
    sub.add_parser("full", help="Run resolve, discover, track, crm, digest, health in sequence").set_defaults(func=cmd_full)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
