"""Glue for the orchestrator's discover -> dedup -> score leg. The discovery
runner belongs to a separate teammate's module; imported lazily so this file
(and anything that imports it) keeps working before that module lands.
"""
from __future__ import annotations

from agents.dedup import dedupe
from agents.scoring import score_and_publish
from core.alerts import notify


def run_discovery_pipeline() -> dict:
    try:
        from agents.discovery.runner import discover_all
    except ImportError:
        notify("Pipeline", "discovery runner not available yet — skipping discovery leg")
        return {}

    postings = discover_all()
    new_postings = dedupe(postings)
    return score_and_publish(new_postings)


if __name__ == "__main__":
    print(run_discovery_pipeline())
