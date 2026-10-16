"""Seed source: the curated awesome-selfhosted dataset.

https://github.com/awesome-selfhosted/awesome-selfhosted-data lists ~1,350 self-hosted
apps as one YAML file each under ``software/``. The whole repo is downloaded as one
archive and read in memory; nothing is extracted to disk.
"""

from __future__ import annotations

import io
import json
import logging
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from docscout.find.github import AuthError, GitHub, GitHubError, RateLimited
from docscout.find.health import parse_time
from docscout.analyze.safe_yaml import UnsafeYAML, load_untrusted
from docscout.find.sources import Candidate, SourceUnavailable, github_full_name

log = logging.getLogger(__name__)

REPO = "awesome-selfhosted/awesome-selfhosted-data"
SOURCE = "awesome_selfhosted"
PRIOR = 0.2  # the list only contains real, deployable apps
_MAX_ENTRY_BYTES = 256 * 1024


def parse_archive(data: bytes) -> list[Candidate]:
    candidates: dict[str, Candidate] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive:
            parts = member.name.split("/")
            if not member.isfile() or len(parts) != 3 or parts[1] != "software" or not parts[2].endswith(".yml"):
                continue
            if member.size > _MAX_ENTRY_BYTES:
                continue
            fh = archive.extractfile(member)
            if fh is None:
                continue
            try:
                entry = load_untrusted(fh.read())
            except UnsafeYAML as exc:
                log.debug("skipping %s: %s", member.name, exc)
                continue
            candidate = _candidate(entry)
            if candidate:
                candidates.setdefault(candidate.full_name.lower(), candidate)
    return list(candidates.values())


def _candidate(entry: object) -> Candidate | None:
    if not isinstance(entry, dict) or entry.get("archived"):
        return None
    full_name = github_full_name(entry.get("source_code_url"))
    if not full_name:
        return None
    meta = {
        "full_name": full_name,
        "description": str(entry.get("description") or ""),
        "stargazers_count": entry.get("stargazers_count"),
        "homepage": entry.get("website_url"),
        "seed_tags": [str(t) for t in entry.get("tags") or []],
    }
    return Candidate(full_name=full_name, source=SOURCE, meta=meta, prior=PRIOR)


STALE_AFTER_DAYS = 180


def _read_cache(cache_file: Path) -> dict[str, Any] | None:
    if not cache_file.is_file():
        return None
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    if isinstance(data, list):  # cache written by an older version: rows only
        data = {"rows": data}
    data.setdefault("fetched_at", cache_file.stat().st_mtime)
    return data


def _candidates(data: dict[str, Any]) -> list[Candidate]:
    return [Candidate(full_name=r["full_name"], source=SOURCE, meta=r["meta"], prior=PRIOR) for r in data["rows"]]


def load_seed(gh: GitHub, cache_file: Path, max_age_days: float) -> list[Candidate]:
    """Seed candidates, downloading a fresh archive when the cache is older than ``max_age_days``.

    If the download fails (the list moved, was deleted, or GitHub is down), the last
    downloaded copy is used; with no copy at all, :class:`SourceUnavailable` is raised so
    the other sources carry on without this one.
    """
    cached = _read_cache(cache_file)
    if cached and time.time() - cached["fetched_at"] < max_age_days * 86400:
        return _candidates(cached)
    log.info("downloading %s", REPO)
    try:
        info = gh.get_repo(REPO)
        candidates = parse_archive(gh.download_tarball(REPO))
    except (AuthError, RateLimited):
        raise
    except (GitHubError, httpx.HTTPError, tarfile.TarError) as exc:
        if cached:
            log.warning("couldn't refresh the curated list (%s); using the copy downloaded earlier", exc)
            return _candidates(cached)
        raise SourceUnavailable(f"couldn't download the curated list {REPO}: {exc}") from exc
    if not candidates:
        if cached:
            return _candidates(cached)
        raise SourceUnavailable(f"the curated list {REPO} no longer has entries in the expected format")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "fetched_at": time.time(),
        "list_pushed_at": info.get("pushed_at"),
        "list_archived": bool(info.get("archived")),
        "rows": [{"full_name": c.full_name, "meta": c.meta} for c in candidates],
    }
    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return candidates


def staleness_note(cache_file: Path, now: datetime) -> str | None:
    """A note for the report when the curated list is archived or no longer updated."""
    data = _read_cache(cache_file)
    if not data:
        return None
    how_to_stop = "Other sources aren't affected. To stop using it, remove awesome_selfhosted from [discovery] sources."
    if data.get("list_archived"):
        return f"The awesome-selfhosted list is archived, so no new apps will appear from it. {how_to_stop}"
    pushed = parse_time(data.get("list_pushed_at"))
    if pushed and (now - pushed).days > STALE_AFTER_DAYS:
        return f"The awesome-selfhosted list hasn't been updated since {pushed:%d %b %Y}, so new apps won't appear from it. {how_to_stop}"
    age_days = (now.timestamp() - data["fetched_at"]) / 86400
    if age_days > 30:
        return f"DocScout couldn't refresh the awesome-selfhosted list for {int(age_days)} days and is using an older copy."
    return None
