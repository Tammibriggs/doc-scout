"""MongoDB Atlas, the hosted version's data layer.

- **DocScout's memory:** what it has checked, reported and skipped, in collections of their
  own (:mod:`docscout.hosted.atlas_store`). Until 18 Oct it was a SQLite file in GridFS, copied
  in and out around each run; :meth:`Atlas.load_state` reads that file for the one-time move.
- **The open picks** (since 10 Nov), for the website. Each pick is kept in two parts:

  - ``pick_content``: everything its card shows except the parts below, stored once under a key
    made from the content itself, and shared by every version of the list until it changes;
  - ``open_picks``: for each version of the list, one small document per pick: its rank, its
    places best first and newest first, when it was last checked, its free and New labels, the
    fields the filters use, and the key of its content.

  At every run nearly every pick's rank or "checked" time changes, but its content rarely does.
  So a publish writes every small part (about 280 bytes a pick) and only the content that changed
  (about 2.6 KB a pick), then points ``picks.published`` at the new version in one write, so a
  visitor never sees two versions mixed. The version it replaces stays until the next publish,
  for pages being read at that moment; older ones are deleted. Content no version uses is marked,
  and deleted at a later publish if it's still unused and still marked; a publish that uses it
  again unmarks it first, so a publish running at the same moment never loses content it relies
  on. Nothing outside these two collections is ever deleted.

  A page asks only for what it shows: the free picks, a page of 10, a count, or the four fields
  the search reads. The small parts are joined to their content inside Atlas (``$lookup``).

  Until 10 Nov the list was one document, ``picks.current``, which every page view loaded whole
  (216 KB at 93 picks; MongoDB's 16 MB limit would come at about 7,000). It's kept as it was. If
  it's ever newer than the published version (code from before 10 Nov wrote it, as after a
  rollback), :meth:`Atlas.listing` publishes it, so the website shows it.
- **Subscriptions:** one document per completed Stripe Checkout. No names or email
  addresses are stored.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import gridfs
import pymongo
from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import BulkWriteError

STATE_FILE = "docscout.db"  # the SQLite memory kept in GridFS until 18 Oct
PICKS = "open_picks"  # the small part of each pick: one document per pick, per version
CONTENT = "pick_content"  # the rest of each pick: one document per distinct content, shared by versions
POINTER = "published"  # in the picks collection: the version the website shows
LEGACY = "current"  # in the picks collection: the list as one document, until 10 Nov (kept)
ORDERS = {"best": {"position": 1}, "latest": {"newest_position": 1}}
SEARCHED = ("full_name", "description", "topics", "language")  # what hosted.search reads
PER_VERSION = ("rank", "checked", "free", "new")  # a pick's fields that change while its content doesn't
UNUSED = "unused_since"  # on content no version used at a publish: that publish's version
DUPLICATE_KEY = 11000


@dataclass(frozen=True)
class Listing:
    """One published version of the list: its id, when it was published and how many picks."""

    version: str | None
    updated: datetime | None
    count: int


def _newest_positions(picks: list[dict[str, Any]]) -> dict[int, int]:
    """Each pick's place newest first (the day it was found, then the best score), the website's
    "newest first"; equal picks keep their published order."""
    order = sorted(range(len(picks)), key=lambda i: (str(picks[i].get("reported") or ""), picks[i].get("score") or 0), reverse=True)
    return {i: place for place, i in enumerate(order)}


def _content_key(content: dict[str, Any]) -> str:
    """The key of a pick's content, made from the content itself: the same content, the same key."""
    text = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def _parts(picks: list[dict[str, Any]], version: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Each pick split in two: its small part for this version, and its content by key."""
    newest = _newest_positions(picks)
    small, contents = [], {}
    for i, pick in enumerate(picks):
        content = {k: v for k, v in pick.items() if k not in PER_VERSION}
        key = _content_key(content)
        contents.setdefault(key, content)
        small.append({
            "version": version, "content": key, "full_name": pick.get("full_name"), "position": i, "newest_position": newest[i],
            "effort": pick.get("effort"), "asked_for_help": bool(pick.get("issues")),  # what the filters ask for
            **{k: pick[k] for k in PER_VERSION if k in pick},
        })  # fmt: skip
    return small, contents


def _pick(doc: dict[str, Any]) -> dict[str, Any]:
    """A pick as it was published: its content with its small part's fields."""
    pick = {k: v for k, v in doc["c"].items() if k not in ("_id", UNUSED)}
    pick.update({k: doc[k] for k in PER_VERSION if k in doc})
    return pick


def _newer(this: Any, than: Any) -> bool:
    """True when ``this`` time is later than ``than``; Atlas returns times without a timezone (UTC)."""

    def utc(value: Any) -> Any:
        return value.replace(tzinfo=timezone.utc) if isinstance(value, datetime) and value.tzinfo is None else value

    if not isinstance(this, datetime):
        return False
    return not isinstance(than, datetime) or utc(this) > utc(than)


class Atlas:
    def __init__(self, uri: str, database: str = "docscout", client: Any = None) -> None:
        self.client = client or pymongo.MongoClient(uri, serverSelectionTimeoutMS=15000, appname="docscout")
        self.db = self.client[database]

    # ------------------------------------------------------------------ DocScout's memory

    @property
    def fs(self) -> gridfs.GridFSBucket:
        return gridfs.GridFSBucket(self.db, bucket_name="state")

    def load_state(self, path: Path) -> bool:
        """Copy the newest SQLite memory kept in GridFS to ``path``; False if there is none."""
        try:
            with path.open("wb") as fh:
                self.fs.download_to_stream_by_name(STATE_FILE, fh)
            return True
        except gridfs.errors.NoFile:
            path.unlink(missing_ok=True)
            return False

    # ------------------------------------------------------------------ publishing the picks

    def publish(self, picks: list[dict[str, Any]], now: datetime | None) -> str:
        """Publish ``picks``, in the order the website shows them best first, as a new version,
        and point the website at it. Returns the version."""
        version = str(ObjectId())  # in time order, so "older than" is a comparison
        small, contents = _parts(picks, version)
        parts = self.db[PICKS]
        for order in ORDERS.values():
            parts.create_index([("version", pymongo.ASCENDING), *order.items()])
        parts.create_index("content")  # the clean-up looks content up by key
        if small:  # first, so a clean-up running at this moment sees the content they use
            parts.insert_many(small)
        self._store_content(contents)
        replaced = self.db.picks.find_one_and_update(
            {"_id": POINTER},
            {"$set": {"version": version, "updated": now, "count": len(small)}},
            upsert=True,
            return_document=ReturnDocument.BEFORE,
        )
        replaced_version = (replaced or {}).get("version")
        if replaced_version:
            # Versions older than the one just replaced, which stays until the next publish for
            # pages being read now; never the one just published.
            parts.delete_many({"version": {"$lt": replaced_version, "$ne": version}})
            self._clean_up_content(version)
        return version

    def _store_content(self, contents: dict[str, dict[str, Any]]) -> None:
        """Store the content not stored yet: new picks, and picks whose content changed."""
        if not contents:
            return
        store = self.db[CONTENT]
        found = {d["_id"]: d for d in store.find({"_id": {"$in": list(contents)}}, {"_id": 1, UNUSED: 1})}
        marked = [key for key, doc in found.items() if UNUSED in doc]
        if marked:  # unused at an earlier publish and used again: unmarked, so no clean-up deletes it
            if store.update_many({"_id": {"$in": marked}}, {"$unset": {UNUSED: ""}}).matched_count < len(marked):
                still = {d["_id"] for d in store.find({"_id": {"$in": marked}}, {"_id": 1})}
                found = {key: doc for key, doc in found.items() if key in still}  # deleted just before: stored again below
        new = [{"_id": key, **content} for key, content in contents.items() if key not in found]
        if not new:
            return
        try:
            store.insert_many(new, ordered=False)
        except BulkWriteError as exc:  # stored by another publish at the same moment: the same content
            if any(error.get("code") != DUPLICATE_KEY for error in exc.details.get("writeErrors", [])):
                raise

    def _clean_up_content(self, version: str) -> None:
        """Content no version uses is marked; content still unused and still marked at a later
        publish is deleted. Content in use that was marked is unmarked."""
        store = self.db[CONTENT]
        found = list(store.aggregate([
            {"$lookup": {"from": PICKS, "localField": "_id", "foreignField": "content", "as": "used"}},
            {"$match": {"$or": [{"used": {"$size": 0}}, {UNUSED: {"$exists": True}}]}},
            {"$project": {UNUSED: 1, "used": {"$size": "$used"}}},
        ]))  # fmt: skip
        in_use = [d["_id"] for d in found if d["used"]]
        earlier = [d["_id"] for d in found if not d["used"] and UNUSED in d]
        now_unused = [d["_id"] for d in found if not d["used"] and UNUSED not in d]
        if in_use:
            store.update_many({"_id": {"$in": in_use}}, {"$unset": {UNUSED: ""}})
        if earlier:  # only while still marked: a publish that uses it again unmarks it first
            store.delete_many({"_id": {"$in": earlier}, UNUSED: {"$lt": version}})
        if now_unused:
            store.update_many({"_id": {"$in": now_unused}, UNUSED: {"$exists": False}}, {"$set": {UNUSED: version}})

    # ------------------------------------------------------------------ reading the picks

    def listing(self) -> Listing:
        """The version the website shows. Two small reads: the pointer, and the old single
        document's date, without its picks. The old document is published when it's the newer of
        the two (it's never changed or deleted)."""
        found = {d["_id"]: d for d in self.db.picks.find({"_id": {"$in": [POINTER, LEGACY]}}, {"version": 1, "updated": 1, "count": 1})}
        pointer, legacy = found.get(POINTER), found.get(LEGACY)
        if legacy is not None and (pointer is None or _newer(legacy.get("updated"), pointer.get("updated"))):
            whole = self.db.picks.find_one({"_id": LEGACY}) or {}
            self.publish(list(whole.get("picks") or []), whole.get("updated"))
            pointer = self.db.picks.find_one({"_id": POINTER})
        if pointer is None:
            return Listing(None, None, 0)
        return Listing(pointer.get("version"), pointer.get("updated"), int(pointer.get("count") or 0))

    def _joined(self, match: dict[str, Any], order: str | None = None, *, skip: int = 0, limit: int = 0,
                fields: Iterable[str] | None = None) -> list[dict[str, Any]]:  # fmt: skip
        """The small parts matching ``match``, in ``order``, each with its content as ``c``
        (only ``fields`` of it, when given). Joined inside Atlas, after the page is cut."""
        pipeline: list[dict[str, Any]] = [{"$match": match}]
        if order:
            pipeline.append({"$sort": ORDERS[order]})
        if skip:
            pipeline.append({"$skip": skip})
        if limit:
            pipeline.append({"$limit": limit})
        pipeline += [{"$lookup": {"from": CONTENT, "localField": "content", "foreignField": "_id", "as": "c"}}, {"$unwind": "$c"}]
        if fields is None:
            pipeline.append({"$project": {"_id": 0, "c": 1, **{k: 1 for k in PER_VERSION}}})
        else:
            pipeline.append({"$project": {"_id": 0, **{f"c.{name}": 1 for name in fields}}})
        return list(self.db[PICKS].aggregate(pipeline))

    def list_picks(
        self,
        listing: Listing,
        where: dict[str, Any] | None = None,
        order: str = "best",
        *,
        skip: int = 0,
        limit: int = 0,
        searched_only: bool = False,
    ) -> list[dict[str, Any]]:
        """The picks of ``listing`` that match ``where``, best or newest first. With
        ``searched_only``, only the fields the search reads (about a seventh of a pick)."""
        if not listing.version:
            return []
        match = {**(where or {}), "version": listing.version}
        if searched_only:
            return [d.get("c") or {} for d in self._joined(match, order, fields=SEARCHED)]
        return [_pick(d) for d in self._joined(match, order, skip=skip, limit=limit)]

    def count_picks(self, listing: Listing, where: dict[str, Any] | None = None) -> int:
        if not listing.version:
            return 0
        if not where:
            return listing.count
        return self.db[PICKS].count_documents({**where, "version": listing.version})

    def picks_named(self, listing: Listing, names: list[str]) -> list[dict[str, Any]]:
        """The picks with these names, in this order (a page of search results)."""
        if not listing.version or not names:
            return []
        found = {p["full_name"]: p for p in map(_pick, self._joined({"version": listing.version, "full_name": {"$in": list(names)}}))}
        return [found[name] for name in names if name in found]

    def free_picks(self, listing: Listing, limit: int) -> list[dict[str, Any]]:
        """The free picks, flagged when published; the first ones for a list published without flags."""
        return self.list_picks(listing, {"free": True}, limit=limit) or self.list_picks(listing, limit=limit)

    def current_picks(self) -> tuple[list[dict[str, Any]], datetime | None]:
        """Every published pick, best first, and when they were published (for scripts and tests)."""
        listing = self.listing()
        return self.list_picks(listing), listing.updated

    # ------------------------------------------------------------------ subscriptions

    def record_subscription(self, subscription: dict[str, Any]) -> None:
        self.db.subscriptions.update_one({"_id": subscription["_id"]}, {"$setOnInsert": subscription}, upsert=True)
