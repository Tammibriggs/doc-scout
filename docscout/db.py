"""SQLite storage: which repos were checked, what was found, and what you've dealt with.

The schema is versioned with ``PRAGMA user_version``; :data:`MIGRATIONS` upgrades older
databases in order, so updating DocScout never loses your history.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

MIGRATIONS = [
    """
    CREATE TABLE repos (
        key TEXT PRIMARY KEY,            -- lowercase owner/name
        full_name TEXT NOT NULL,
        source TEXT,
        stars INTEGER,
        language TEXT,
        api_type TEXT,
        type_conf REAL,
        health REAL,
        rejected TEXT,                   -- why it failed a check, if it did
        status TEXT NOT NULL DEFAULT 'new',  -- new | reported | ignored | done
        status_reason TEXT,
        first_seen TEXT NOT NULL,
        last_checked TEXT,
        last_reported TEXT
    );
    CREATE TABLE runs (
        id INTEGER PRIMARY KEY,
        started TEXT NOT NULL,
        finished TEXT,
        status TEXT,                     -- running | ok | partial | empty | failed
        analyzed INTEGER DEFAULT 0,
        new_items INTEGER DEFAULT 0,
        api_calls INTEGER DEFAULT 0,
        report_path TEXT,
        error TEXT
    );
    CREATE TABLE findings (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES runs(id),
        repo_key TEXT NOT NULL REFERENCES repos(key),
        api_type TEXT NOT NULL,
        kind TEXT NOT NULL,
        gap REAL NOT NULL,
        score REAL NOT NULL,
        effort TEXT,
        details TEXT NOT NULL,           -- JSON: gap, score breakdown, repo snapshot, issues
        created TEXT NOT NULL
    );
    CREATE INDEX findings_run ON findings(run_id);
    CREATE INDEX findings_repo ON findings(repo_key);
    """,
]
FINAL_STATUSES = ("ignored", "done")
REPO_FIELDS = {"source", "stars", "language", "api_type", "type_conf", "health", "rejected"}


def _iso(when: datetime) -> str:
    return when.isoformat(timespec="seconds")


@dataclass
class StoredFinding:
    full_name: str
    score: float
    details: dict[str, Any]
    run_id: int


class Store:
    def __init__(self, path: Path | str) -> None:
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            with self.conn:
                self.conn.executescript(script)
                self.conn.execute(f"PRAGMA user_version = {number}")

    def close(self) -> None:
        self.conn.close()

    # ------------------------------------------------------------------ runs

    def start_run(self, now: datetime) -> int:
        with self.conn:
            cur = self.conn.execute("INSERT INTO runs (started, status) VALUES (?, 'running')", (_iso(now),))
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, now: datetime, *, status: str, analyzed: int, new_items: int, api_calls: int,
                   report_path: str | None = None, error: str | None = None) -> None:  # fmt: skip
        with self.conn:
            self.conn.execute(
                "UPDATE runs SET finished=?, status=?, analyzed=?, new_items=?, api_calls=?, report_path=?, error=? WHERE id=?",
                (_iso(now), status, analyzed, new_items, api_calls, report_path, error, run_id),
            )

    # ------------------------------------------------------------------ repos

    def repo(self, full_name: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM repos WHERE key=?", (full_name.lower(),)).fetchone()

    def skip_reason(self, full_name: str, now: datetime, recheck_after_days: int) -> str | None:
        """Why a repo shouldn't be checked again now, or None if it should."""
        row = self.repo(full_name)
        if row is None:
            return None
        if row["status"] in FINAL_STATUSES:
            return row["status"]
        if row["status"] == "reported":
            return "already reported"
        if row["last_checked"] and now - datetime.fromisoformat(row["last_checked"]) < timedelta(days=recheck_after_days):
            return "checked recently"
        return None

    def save_repo(self, full_name: str, now: datetime, **fields: Any) -> None:
        """Insert or update a repo's latest check; ``fields`` are repos columns."""
        unknown = set(fields) - REPO_FIELDS
        if unknown:
            raise ValueError(f"unknown repo fields: {sorted(unknown)}")
        key = full_name.lower()
        columns = {"full_name": full_name, "last_checked": _iso(now), **fields}
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO repos (key, full_name, first_seen) VALUES (?, ?, ?)", (key, full_name, _iso(now)))
            assignments = ", ".join(f"{name}=?" for name in columns)
            self.conn.execute(f"UPDATE repos SET {assignments} WHERE key=?", (*columns.values(), key))

    def set_status(self, full_name: str, status: str, now: datetime, reason: str | None = None) -> None:
        if status not in ("new", "reported", *FINAL_STATUSES):
            raise ValueError(status)
        key = full_name.lower()
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO repos (key, full_name, first_seen) VALUES (?, ?, ?)", (key, full_name, _iso(now)))
            extra = ", last_reported=?" if status == "reported" else ""
            params: tuple = (status, reason, _iso(now), key) if status == "reported" else (status, reason, key)
            self.conn.execute(f"UPDATE repos SET status=?, status_reason=?{extra} WHERE key=?", params)

    # ------------------------------------------------------------------ findings

    def save_finding(self, run_id: int, full_name: str, now: datetime, *, api_type: str, kind: str, gap: float,
                     score: float, effort: str, details: dict[str, Any]) -> None:  # fmt: skip
        with self.conn:
            self.conn.execute(
                "INSERT INTO findings (run_id, repo_key, api_type, kind, gap, score, effort, details, created) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, full_name.lower(), api_type, kind, gap, score, effort, json.dumps(details), _iso(now)),
            )

    def run_findings(self, run_id: int, min_score: float, limit: int) -> list[StoredFinding]:
        rows = self.conn.execute(
            """SELECT r.full_name, f.score, f.details, f.run_id FROM findings f JOIN repos r ON r.key = f.repo_key
               WHERE f.run_id=? AND f.score >= ? AND r.status NOT IN ('ignored', 'done')
               ORDER BY f.score DESC LIMIT ?""",
            (run_id, min_score, limit),
        ).fetchall()
        return [StoredFinding(r["full_name"], r["score"], json.loads(r["details"]), r["run_id"]) for r in rows]

    def still_open(self, before_run: int, limit: int) -> list[StoredFinding]:
        """The latest finding of each repo reported earlier and not yet marked done or ignored."""
        rows = self.conn.execute(
            """SELECT r.full_name, f.score, f.details, f.run_id FROM findings f JOIN repos r ON r.key = f.repo_key
               WHERE r.status = 'reported' AND f.run_id < ?
                 AND f.id = (SELECT MAX(id) FROM findings WHERE repo_key = f.repo_key)
               ORDER BY f.score DESC LIMIT ?""",
            (before_run, limit),
        ).fetchall()
        return [StoredFinding(r["full_name"], r["score"], json.loads(r["details"]), r["run_id"]) for r in rows]
