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
    """
    ALTER TABLE runs ADD COLUMN run_limit INTEGER;                     -- repos this run was allowed to check
    ALTER TABLE runs ADD COLUMN started_by TEXT NOT NULL DEFAULT 'you';  -- you | schedule
    ALTER TABLE runs ADD COLUMN resume_after TEXT;                     -- rate limited: continue after this time
    CREATE TABLE state (                 -- small facts the daily schedule needs, e.g. the last check
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated TEXT NOT NULL
    );
    CREATE TABLE sweep (                 -- where each repo-search slice stopped, so days don't repeat page 1
        slice_key TEXT PRIMARY KEY,
        page INTEGER NOT NULL DEFAULT 1,
        cycle INTEGER NOT NULL DEFAULT 0,  -- how many times the slice has been worked through
        last_used TEXT
    );
    """,
]
FINAL_STATUSES = ("ignored", "done")
PENDING_MAX_AGE_DAYS = 14  # findings not reported yet (an interrupted run, or past max_items) wait this long
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

    def start_run(self, now: datetime, *, run_limit: int | None = None, started_by: str = "you") -> int:
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO runs (started, status, run_limit, started_by) VALUES (?, 'running', ?, ?)",
                (_iso(now), run_limit, started_by),
            )
        return int(cur.lastrowid)

    def finish_run(self, run_id: int, now: datetime, *, status: str, analyzed: int, new_items: int, api_calls: int,
                   report_path: str | None = None, error: str | None = None,
                   resume_after: datetime | None = None) -> None:  # fmt: skip
        with self.conn:
            self.conn.execute(
                """UPDATE runs SET finished=?, status=?, analyzed=?, new_items=?, api_calls=?, report_path=?, error=?,
                   resume_after=? WHERE id=?""",
                (_iso(now), status, analyzed, new_items, api_calls, report_path, error,
                 _iso(resume_after) if resume_after else None, run_id),
            )  # fmt: skip

    def update_progress(self, run_id: int, analyzed: int) -> None:
        """Saved as the run goes, so a run that's cut off still counts toward today's budget."""
        with self.conn:
            self.conn.execute("UPDATE runs SET analyzed=? WHERE id=?", (analyzed, run_id))

    def close_stale_runs(self, now: datetime) -> int:
        """Mark runs still 'running' as stopped. Only call this while holding the run lock:
        then no run is active, so these were cut off by a shutdown or a killed process."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE runs SET status='partial', finished=?, error=? WHERE status='running'",
                (_iso(now), "stopped before finishing (the computer shut down or the process was stopped)"),
            )
        return cur.rowcount

    def runs_since(self, since: datetime) -> list[sqlite3.Row]:
        """Runs started at or after ``since``, oldest first. Times are compared in UTC."""
        rows = self.conn.execute("SELECT * FROM runs ORDER BY id").fetchall()
        return [r for r in rows if datetime.fromisoformat(r["started"]) >= since]

    def recent_runs(self, limit: int) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    # ------------------------------------------------------------------ state

    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO state (key, value, updated) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, value, _iso(now)),
            )

    # ------------------------------------------------------------------ search cursor

    def slice_position(self, key: str) -> tuple[int, int, str | None]:
        """(page to fetch next, times worked through, last used) for a repo-search slice."""
        row = self.conn.execute("SELECT page, cycle, last_used FROM sweep WHERE slice_key=?", (key,)).fetchone()
        return (row["page"], row["cycle"], row["last_used"]) if row else (1, 0, None)

    def save_slice(self, key: str, *, page: int, cycle: int) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO sweep (slice_key, page, cycle) VALUES (?, ?, ?) ON CONFLICT(slice_key) DO UPDATE SET page=excluded.page, cycle=excluded.cycle",
                (key, page, cycle),
            )

    def touch_slice(self, key: str, now: datetime) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO sweep (slice_key, last_used) VALUES (?, ?) ON CONFLICT(slice_key) DO UPDATE SET last_used=excluded.last_used",
                (key, _iso(now)),
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

    def update_details(self, run_id: int, full_name: str, details: dict[str, Any]) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE findings SET details=? WHERE run_id=? AND repo_key=?", (json.dumps(details), run_id, full_name.lower())
            )

    def pending_findings(self, now: datetime, min_score: float, limit: int, max_age_days: int = PENDING_MAX_AGE_DAYS) -> list[StoredFinding]:
        """Findings not reported yet: this run's, plus any left by a run that was cut off
        before writing its report, or that didn't fit in an earlier report."""
        rows = self.conn.execute(
            """SELECT r.full_name, f.score, f.details, f.run_id FROM findings f JOIN repos r ON r.key = f.repo_key
               WHERE r.status = 'new' AND f.score >= ? AND f.created >= ?
                 AND f.id = (SELECT MAX(id) FROM findings WHERE repo_key = f.repo_key)
               ORDER BY f.score DESC LIMIT ?""",
            (min_score, _iso(now - timedelta(days=max_age_days)), limit),
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
