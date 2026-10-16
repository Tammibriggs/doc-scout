"""MongoDB Atlas, the hosted version's data layer.

- **DocScout's memory.** Render cron jobs can't keep files between runs, so the SQLite file
  that remembers what was checked, shown and skipped is stored here (GridFS) and copied in
  and out around each run. The newest few versions are kept.
- **This week's picks:** one document, replaced after each run.
- **Subscriptions:** one document per completed Stripe Checkout. No names or email
  addresses are stored.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import gridfs
import pymongo

STATE_FILE = "docscout.db"
KEEP_STATE_VERSIONS = 3


class Atlas:
    def __init__(self, uri: str, database: str = "docscout", client: Any = None) -> None:
        self.client = client or pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000, appname="docscout")
        self.db = self.client[database]
        self.fs = gridfs.GridFSBucket(self.db, bucket_name="state")

    # ------------------------------------------------------------------ DocScout's memory

    def load_state(self, path: Path) -> bool:
        """Copy the newest database file to ``path``; False on the very first run."""
        try:
            with path.open("wb") as fh:
                self.fs.download_to_stream_by_name(STATE_FILE, fh)
            return True
        except gridfs.errors.NoFile:
            path.unlink(missing_ok=True)
            return False

    def save_state(self, path: Path) -> None:
        with path.open("rb") as fh:
            self.fs.upload_from_stream(STATE_FILE, fh)
        old = self.db["state.files"].find({"filename": STATE_FILE}, {"_id": 1}).sort("uploadDate", -1).skip(KEEP_STATE_VERSIONS)
        for doc in list(old):
            self.fs.delete(doc["_id"])

    # ------------------------------------------------------------------ picks

    def publish(self, picks: list[dict[str, Any]], now: datetime) -> None:
        self.db.picks.replace_one({"_id": "current"}, {"_id": "current", "updated": now, "picks": picks}, upsert=True)

    def current_picks(self) -> tuple[list[dict[str, Any]], datetime | None]:
        doc = self.db.picks.find_one({"_id": "current"}) or {}
        return list(doc.get("picks") or []), doc.get("updated")

    # ------------------------------------------------------------------ subscriptions

    def record_subscription(self, subscription: dict[str, Any]) -> None:
        self.db.subscriptions.update_one({"_id": subscription["_id"]}, {"$setOnInsert": subscription}, upsert=True)
