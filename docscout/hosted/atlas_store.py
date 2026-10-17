"""DocScout's memory in MongoDB Atlas collections, for the hosted version.

It has the same methods as :class:`docscout.run.db.Store`, the SQLite file the command-line
tool keeps on your laptop, so the pipeline, the daily checks and the website don't change.
Render's cron jobs start on an empty machine each day, and with this store everything
DocScout remembers lives in Atlas:

- ``repos``: one document per repo checked; ``_id`` is the lowercase owner/name;
- ``findings``: the docs gaps found, each with its details as an embedded document;
- ``runs``: one document per run;
- ``run_state`` and ``sweep``: small facts for the daily schedule, and where each search slice stopped;
- ``counters``: the next run and finding numbers.

"The latest finding of each repo" is an aggregation pipeline (sort, group, lookup), so the
queries run in Atlas. Times are ISO 8601 strings in UTC, as in the SQLite store, so they
compare the same way.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pymongo
from pymongo import ReturnDocument

from docscout.run.db import FINAL_STATUSES, PENDING_MAX_AGE_DAYS, REPO_FIELDS, Store, StoredFinding, _iso

REPO_COLUMNS = ("full_name", "source", "stars", "language", "api_type", "type_conf", "health", "rejected",
                "status", "status_reason", "first_seen", "last_checked", "last_reported")  # fmt: skip
STALE_RUN = "stopped before finishing (the computer shut down or the process was stopped)"


def _plain(details: dict[str, Any]) -> dict[str, Any]:
    """Details as the SQLite store keeps them (JSON), so both stores hold the same values."""
    return json.loads(json.dumps(details))


class AtlasStore:
    def __init__(self, db: Any) -> None:
        self.db = db
        self._client: Any = None
        self.db.findings.create_index([("repo_key", pymongo.ASCENDING), ("_id", pymongo.DESCENDING)])
        self.db.findings.create_index("run_id")
        self.db.repos.create_index([("status", pymongo.ASCENDING), ("last_reported", pymongo.ASCENDING)])

    @classmethod
    def connect(cls, uri: str, database: str = "docscout") -> AtlasStore:
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000, appname="docscout")
        store = cls(client[database])
        store._client = client
        return store

    def close(self) -> None:
        if self._client is not None:
            self._client.close()

    def is_empty(self) -> bool:
        return self.db.runs.count_documents({}, limit=1) == 0 and self.db.repos.count_documents({}, limit=1) == 0

    def _next_id(self, name: str) -> int:
        doc = self.db.counters.find_one_and_update({"_id": name}, {"$inc": {"seq": 1}}, upsert=True, return_document=ReturnDocument.AFTER)
        return int(doc["seq"])

    # ------------------------------------------------------------------ runs

    def start_run(self, now: datetime, *, run_limit: int | None = None, started_by: str = "you") -> int:
        run_id = self._next_id("runs")
        self.db.runs.insert_one({
            "_id": run_id, "started": _iso(now), "finished": None, "status": "running", "analyzed": 0, "new_items": 0,
            "api_calls": 0, "report_path": None, "error": None, "run_limit": run_limit, "started_by": started_by,
            "resume_after": None, "reviewed": 0,
        })  # fmt: skip
        return run_id

    def finish_run(self, run_id: int, now: datetime, *, status: str, analyzed: int, new_items: int, api_calls: int,
                   report_path: str | None = None, error: str | None = None,
                   resume_after: datetime | None = None, reviewed: int = 0) -> None:  # fmt: skip
        self.db.runs.update_one({"_id": run_id}, {"$set": {
            "finished": _iso(now), "status": status, "analyzed": analyzed, "new_items": new_items, "api_calls": api_calls,
            "report_path": report_path, "error": error, "resume_after": _iso(resume_after) if resume_after else None, "reviewed": reviewed,
        }})  # fmt: skip

    def update_progress(self, run_id: int, analyzed: int) -> None:
        self.db.runs.update_one({"_id": run_id}, {"$set": {"analyzed": analyzed}})

    def close_stale_runs(self, now: datetime) -> int:
        result = self.db.runs.update_many({"status": "running"}, {"$set": {"status": "partial", "finished": _iso(now), "error": STALE_RUN}})
        return int(result.modified_count)

    @staticmethod
    def _run(doc: dict[str, Any]) -> dict[str, Any]:
        return {**doc, "id": doc["_id"]}

    def runs_since(self, since: datetime) -> list[dict[str, Any]]:
        runs = [self._run(d) for d in self.db.runs.find().sort("_id", pymongo.ASCENDING)]
        return [r for r in runs if datetime.fromisoformat(r["started"]) >= since]

    def recent_runs(self, limit: int) -> list[dict[str, Any]]:
        return [self._run(d) for d in self.db.runs.find().sort("_id", pymongo.DESCENDING).limit(limit)]

    # ------------------------------------------------------------------ state

    def get_state(self, key: str) -> str | None:
        doc = self.db.run_state.find_one({"_id": key})
        return doc["value"] if doc else None

    def set_state(self, key: str, value: str, now: datetime) -> None:
        self.db.run_state.update_one({"_id": key}, {"$set": {"value": value, "updated": _iso(now)}}, upsert=True)

    # ------------------------------------------------------------------ search cursor

    def slice_position(self, key: str) -> tuple[int, int, str | None]:
        doc = self.db.sweep.find_one({"_id": key})
        return (int(doc.get("page", 1)), int(doc.get("cycle", 0)), doc.get("last_used")) if doc else (1, 0, None)

    def save_slice(self, key: str, *, page: int, cycle: int) -> None:
        self.db.sweep.update_one({"_id": key}, {"$set": {"page": page, "cycle": cycle}}, upsert=True)

    def touch_slice(self, key: str, now: datetime) -> None:
        self.db.sweep.update_one({"_id": key}, {"$set": {"last_used": _iso(now)}}, upsert=True)

    # ------------------------------------------------------------------ repos

    @staticmethod
    def _repo(doc: dict[str, Any]) -> dict[str, Any]:
        row = {"key": doc["_id"], **{c: doc.get(c) for c in REPO_COLUMNS}}
        row["status"] = row["status"] or "new"
        return row

    def repo(self, full_name: str) -> dict[str, Any] | None:
        doc = self.db.repos.find_one({"_id": full_name.lower()})
        return self._repo(doc) if doc else None

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
        unknown = set(fields) - REPO_FIELDS
        if unknown:
            raise ValueError(f"unknown repo fields: {sorted(unknown)}")
        self.db.repos.update_one(
            {"_id": full_name.lower()},
            {"$setOnInsert": {"first_seen": _iso(now), "status": "new"}, "$set": {"full_name": full_name, "last_checked": _iso(now), **fields}},
            upsert=True,
        )

    def set_status(self, full_name: str, status: str, now: datetime, reason: str | None = None) -> None:
        if status not in ("new", "reported", *FINAL_STATUSES):
            raise ValueError(status)
        changes: dict[str, Any] = {"status": status, "status_reason": reason}
        if status == "reported":
            changes["last_reported"] = _iso(now)
        self.db.repos.update_one(
            {"_id": full_name.lower()}, {"$setOnInsert": {"full_name": full_name, "first_seen": _iso(now)}, "$set": changes}, upsert=True
        )

    # ------------------------------------------------------------------ findings

    def save_finding(self, run_id: int, full_name: str, now: datetime, *, api_type: str, kind: str, gap: float,
                     score: float, effort: str, details: dict[str, Any]) -> None:  # fmt: skip
        self.db.findings.insert_one({
            "_id": self._next_id("findings"), "run_id": run_id, "repo_key": full_name.lower(), "api_type": api_type,
            "kind": kind, "gap": gap, "score": score, "effort": effort, "details": _plain(details), "created": _iso(now), "review": None,
        })  # fmt: skip

    def update_details(self, run_id: int, full_name: str, details: dict[str, Any]) -> None:
        self.db.findings.update_many({"run_id": run_id, "repo_key": full_name.lower()}, {"$set": {"details": _plain(details)}})

    def _latest(self, finding: dict[str, Any], repo: dict[str, Any], limit: int | None = None) -> list[dict[str, Any]]:
        """The latest finding of each repo, when that finding matches ``finding`` and its repo
        matches ``repo`` (fields prefixed ``repo.``), best score first, with the repo joined in."""
        pipeline: list[dict[str, Any]] = [
            {"$sort": {"_id": -1}},
            {"$group": {"_id": "$repo_key", "latest": {"$first": "$$ROOT"}}},
            {"$replaceRoot": {"newRoot": "$latest"}},
            {"$match": finding},
            {"$lookup": {"from": "repos", "localField": "repo_key", "foreignField": "_id", "as": "repo"}},
            {"$unwind": "$repo"},
            {"$match": repo},
            {"$sort": {"score": -1, "_id": -1}},
        ]
        if limit is not None:
            pipeline.append({"$limit": limit})
        return list(self.db.findings.aggregate(pipeline))

    @staticmethod
    def _finding(doc: dict[str, Any], with_id: bool = True, reported: bool = False) -> StoredFinding:
        return StoredFinding(
            doc["repo"]["full_name"], doc["score"], doc["details"], doc["run_id"],
            doc["_id"] if with_id else None, doc["repo"].get("last_reported") if reported else None,
        )  # fmt: skip

    def _pending(self, now: datetime, min_score: float, max_age_days: int, review: str | None) -> dict[str, Any]:
        return {"created": {"$gte": _iso(now - timedelta(days=max_age_days))}, "review": review, "score": {"$gte": min_score}}

    def pending_findings(self, now: datetime, min_score: float, limit: int, max_age_days: int = PENDING_MAX_AGE_DAYS) -> list[StoredFinding]:
        docs = self._latest(self._pending(now, min_score, max_age_days, "accepted"), {"repo.status": "new"}, limit)
        return [self._finding(d) for d in docs]

    def findings_to_review(self, now: datetime, min_score: float, limit: int, max_age_days: int = PENDING_MAX_AGE_DAYS) -> list[StoredFinding]:
        docs = self._latest(self._pending(now, min_score, max_age_days, None), {"repo.status": "new"}, limit)
        return [self._finding(d) for d in docs]

    def count_waiting(self, now: datetime, min_score: float, max_age_days: int = PENDING_MAX_AGE_DAYS) -> int:
        return len(self._latest(self._pending(now, min_score, max_age_days, None), {"repo.status": "new"}))

    def set_review(self, finding_id: int, review: str | None, score: float, details: dict[str, Any]) -> None:
        self.db.findings.update_one({"_id": finding_id}, {"$set": {"review": review, "score": score, "details": _plain(details)}})

    def latest_finding(self, full_name: str) -> StoredFinding | None:
        key = full_name.lower()
        repo = self.db.repos.find_one({"_id": key})
        doc = next(iter(self.db.findings.find({"repo_key": key}).sort("_id", pymongo.DESCENDING).limit(1)), None)
        return self._finding({**doc, "repo": repo}) if doc and repo else None

    def reviewed_since(self, since: datetime) -> int:
        return sum(r["reviewed"] or 0 for r in self.runs_since(since))

    def still_open(self, before_run: int, limit: int) -> list[StoredFinding]:
        docs = self._latest({"run_id": {"$lt": before_run}}, {"repo.status": "reported"}, limit)
        return [self._finding(d, with_id=False) for d in docs]

    def reported_since(self, since: datetime) -> list[StoredFinding]:
        docs = self._latest({}, {"repo.status": "reported", "repo.last_reported": {"$gte": _iso(since)}})
        return [self._finding(d, with_id=False, reported=True) for d in docs]

    # ------------------------------------------------------------------ moving from SQLite

    def import_sqlite(self, path: Path) -> dict[str, int]:
        """Copy a SQLite store (the hosted job's memory until 18 Oct) into these collections,
        keeping its numbers, so nothing it remembered is lost. Returns the count per collection."""
        old = Store(path)
        try:
            rows = {table: [dict(r) for r in old.conn.execute(f"SELECT * FROM {table}")] for table in ("repos", "runs", "findings", "state", "sweep")}
        finally:
            old.close()
        docs = {
            "repos": [{"_id": r.pop("key"), **r} for r in rows["repos"]],
            "runs": [{"_id": r.pop("id"), **r} for r in rows["runs"]],
            "findings": [{"_id": r.pop("id"), **r, "details": json.loads(r["details"])} for r in rows["findings"]],
            "run_state": [{"_id": r.pop("key"), **r} for r in rows["state"]],
            "sweep": [{"_id": r.pop("slice_key"), **r} for r in rows["sweep"]],
        }
        for name, items in docs.items():
            if items:
                self.db[name].insert_many(items)
        for name in ("runs", "findings"):
            top = max((d["_id"] for d in docs[name]), default=0)
            self.db.counters.update_one({"_id": name}, {"$max": {"seq": top}}, upsert=True)
        return {name: len(items) for name, items in docs.items()}
