"""SQLite mirror: dedup index, ATS resolution cache, run ledger."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from core.config import ROOT, settings

_SCHEMA = """
CREATE TABLE IF NOT EXISTS postings (
    dedup_key TEXT PRIMARY KEY,
    notion_id TEXT,
    company TEXT, title TEXT, url TEXT,
    sources TEXT,
    first_seen REAL
);
CREATE TABLE IF NOT EXISTS resolutions (
    company TEXT PRIMARY KEY,
    ats_type TEXT, endpoint TEXT, resolved_at REAL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent TEXT, started REAL, finished REAL,
    status TEXT, items INTEGER, error TEXT
);
"""


def connect() -> sqlite3.Connection:
    path = ROOT / settings()["paths"]["db"]
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    return conn


class RunLedger:
    """Context manager recording one agent run."""

    def __init__(self, agent: str):
        self.agent = agent
        self.items = 0

    def __enter__(self):
        self.conn = connect()
        cur = self.conn.execute(
            "INSERT INTO runs (agent, started, status) VALUES (?, ?, 'running')",
            (self.agent, time.time()),
        )
        self.run_id = cur.lastrowid
        self.conn.commit()
        return self

    def __exit__(self, exc_type, exc, tb):
        status = "ok" if exc is None else "error"
        self.conn.execute(
            "UPDATE runs SET finished=?, status=?, items=?, error=? WHERE id=?",
            (time.time(), status, self.items, repr(exc) if exc else None, self.run_id),
        )
        self.conn.commit()
        self.conn.close()
        return False  # propagate exceptions


def known_keys(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT dedup_key FROM postings")}


def record_posting(conn, key: str, notion_id: str, company: str, title: str, url: str, source: str):
    row = conn.execute("SELECT sources FROM postings WHERE dedup_key=?", (key,)).fetchone()
    if row:
        sources = set(json.loads(row[0])) | {source}
        conn.execute("UPDATE postings SET sources=? WHERE dedup_key=?", (json.dumps(sorted(sources)), key))
    else:
        conn.execute(
            "INSERT INTO postings (dedup_key, notion_id, company, title, url, sources, first_seen) VALUES (?,?,?,?,?,?,?)",
            (key, notion_id, company, title, url, json.dumps([source]), time.time()),
        )
    conn.commit()


def cached_resolution(conn, company: str):
    return conn.execute(
        "SELECT ats_type, endpoint FROM resolutions WHERE company=?", (company,)
    ).fetchone()


def cache_resolution(conn, company: str, ats_type: str, endpoint: str):
    conn.execute(
        "INSERT OR REPLACE INTO resolutions (company, ats_type, endpoint, resolved_at) VALUES (?,?,?,?)",
        (company, ats_type, endpoint, time.time()),
    )
    conn.commit()
