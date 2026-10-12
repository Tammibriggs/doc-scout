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
from pathlib import Path

from docscout.github import GitHub
from docscout.safe_yaml import UnsafeYAML, load_untrusted
from docscout.sources import Candidate, github_full_name

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


def load_seed(gh: GitHub, cache_file: Path, max_age_days: float) -> list[Candidate]:
    """Seed candidates, downloading a fresh archive when the cache is older than ``max_age_days``."""
    if cache_file.is_file() and time.time() - cache_file.stat().st_mtime < max_age_days * 86400:
        rows = json.loads(cache_file.read_text(encoding="utf-8"))
        return [Candidate(full_name=r["full_name"], source=SOURCE, meta=r["meta"], prior=PRIOR) for r in rows]
    log.info("downloading %s", REPO)
    candidates = parse_archive(gh.download_tarball(REPO))
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(
        json.dumps([{"full_name": c.full_name, "meta": c.meta} for c in candidates]), encoding="utf-8"
    )
    return candidates
