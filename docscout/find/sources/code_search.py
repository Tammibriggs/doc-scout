"""Source (optional): GitHub code search for OpenAPI/Swagger spec files.

Finds repos that ship a spec, whatever their topics say. Needs a token, and is limited to 10
requests a minute.

**Reaching every result.** A search returns at most its first 1,000 results: page 11 is refused
("Cannot access beyond the first 1000 results"), there's no cursor, and GraphQL can't search code
(all checked 10 Nov). Each of the 16 searches (4 file names in 4 size bands) had 6,000-42,000
results, so most were out of reach. Code search can narrow by file size to the byte, so daily runs
split a band that has more than 1,000 results into two halves by size, and again, until each band
can be read to its end (``size:1000..1100`` had 942 ``openapi.yaml`` files; files under 5 KB took
7 splits). The bands are kept in a queue in DocScout's memory, the largest files first: runs work
through it in order, a band being read stays at the front until it's finished, and a finished band
goes to the back, so after the last band the search starts over.

**The cheap checks for free.** Code search returns only a few repo fields, without stars, and most
repos it finds are small or unlicensed: of 1,436 new ones on the first pages on 10 Nov, 1,245
failed the cheap checks (672 under 20 stars, 352 without a licence, 215 without a recent push), and
deeper in the results 92-96% do. So each page's repos are
looked up together, 50 to a GraphQL request (stars, licence, archived, fork, last push), and those
that fail the cheap checks are turned away without fetching each repo or counting toward the run's
budget.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from docscout.find.github import AuthError, GitHub, GitHubError
from docscout.find.sources import Candidate

log = logging.getLogger(__name__)

SOURCE = "code_search"
PER_PAGE = 100
MAX_RESULTS = 1000  # GitHub returns at most this many results per search
MAX_INDEXED = 384 * 1024  # code search only indexes files smaller than 384 KB
BATCH = 50  # repos per GraphQL request for their basic facts
KEY_PREFIX = "code:"  # cursor keys, kept apart from repo search's slices
STATE_KEY = "code_search_bands"


class Cursor(Protocol):
    """Where each band stopped, and the queue of bands; :class:`docscout.run.db.Store` provides it."""

    def slice_position(self, key: str) -> tuple[int, int, str | None]: ...
    def save_slice(self, key: str, *, page: int, cycle: int) -> None: ...
    def get_state(self, key: str) -> str | None: ...
    def set_state(self, key: str, value: str, now: datetime) -> None: ...


def queries(filenames: list[str], size_bands: list[str]) -> list[str]:
    return [f"filename:{name} size:{band}" for name in filenames for band in size_bands]


@dataclass(frozen=True)
class Band:
    """One file name in one range of file sizes, in bytes (both ends included)."""

    filename: str
    low: int
    high: int

    @property
    def query(self) -> str:
        return f"filename:{self.filename} size:{self.low}..{self.high}"

    @property
    def key(self) -> str:
        return KEY_PREFIX + self.query

    def halves(self) -> tuple[Band, Band]:
        middle = (self.low + self.high) // 2
        return Band(self.filename, self.low, middle), Band(self.filename, middle + 1, self.high)


def size_range(text: str) -> tuple[int, int]:
    """A size band as written in the settings ("<5000", "5000..20000", ">100000") -> (low, high)."""
    text = text.strip()
    if text.startswith("<="):
        return 0, int(text[2:])
    if text.startswith("<"):
        return 0, int(text[1:]) - 1
    if text.startswith(">="):
        return int(text[2:]), MAX_INDEXED
    if text.startswith(">"):
        return int(text[1:]) + 1, MAX_INDEXED
    low, _, high = text.partition("..")
    return int(low), int(high)


def start_bands(filenames: list[str], size_bands: list[str]) -> list[Band]:
    """The bands the queue starts from, the largest files first and the file names taking turns.
    Checked 10 Nov on ``openapi.yaml``: 8% of new repos passed the cheap checks at 2 KB and at
    20 KB, 4-5% under 1 KB, where many files are stubs."""
    bands = [Band(name, *size_range(band)) for band in size_bands for name in filenames]
    return sorted(bands, key=lambda b: -b.low)


class _Queue:
    """The bands in the order runs work through them, saved after every change. A change to the
    file names or size bands in the settings starts the queue again from them."""

    def __init__(self, cursor: Cursor, start: list[Band], now: datetime) -> None:
        self.cursor, self.now = cursor, now
        self.start = [[b.filename, b.low, b.high] for b in start]
        saved = _load(cursor.get_state(STATE_KEY))
        if saved.get("start") == self.start:
            self.bands = [Band(str(f), int(lo), int(hi)) for f, lo, hi in saved.get("bands") or []]
        else:
            self.bands = list(start)

    def split(self, band: Band) -> Band:
        """Replace ``band`` with its two halves, in its place; returns the lower half."""
        at = self.bands.index(band)
        self.bands[at : at + 1] = band.halves()
        self._save()
        return self.bands[at]

    def finished(self, band: Band) -> None:
        self.bands.remove(band)
        self.bands.append(band)
        self._save()

    def _save(self) -> None:
        value = {"start": self.start, "bands": [[b.filename, b.low, b.high] for b in self.bands]}
        self.cursor.set_state(STATE_KEY, json.dumps(value, separators=(",", ":")), self.now)


def _load(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _block(alias: str, full_name: str) -> str:
    owner, name = full_name.split("/", 1)
    fields = "stargazerCount isArchived isFork pushedAt licenseInfo { spdxId }"
    return f"{alias}: repository(owner: {json.dumps(owner)}, name: {json.dumps(name)}) {{ {fields} }}"


def with_basics(gh: GitHub, candidates: list[Candidate]) -> list[Candidate]:
    """The candidates with their stars, licence, archived and fork flags and last push added to
    ``meta`` under REST's field names, so the cheap checks need no request of their own. A repo
    GitHub can't find (deleted or made private since it was indexed) is dropped. When GitHub
    can't answer a batch, its repos go on without the facts and are fetched one by one, as before."""
    found: list[Candidate] = []
    for start in range(0, len(candidates), BATCH):
        chunk = candidates[start : start + BATCH]
        aliases = {f"r{k}": c for k, c in enumerate(chunk)}
        try:
            data, missing = gh.graphql_batch("query { " + " ".join(_block(a, c.full_name) for a, c in aliases.items()) + " }")
        except AuthError:
            raise
        except GitHubError as exc:
            log.info("couldn't look up %d code-search repos together (%s); fetching them one by one", len(chunk), exc)
            found.extend(chunk)
            continue
        for alias, cand in aliases.items():
            node = data.get(alias)
            if node is None or alias in missing:
                continue
            licence = node.get("licenseInfo")
            cand.meta.update(
                {
                    "stargazers_count": node.get("stargazerCount"),
                    "archived": bool(node.get("isArchived")),
                    "fork": bool(node.get("isFork")),
                    "pushed_at": node.get("pushedAt"),
                    "license": {"spdx_id": licence.get("spdxId")} if licence else None,
                }
            )
            found.append(cand)
    return found


def _candidates(items: list[dict[str, Any]]) -> list[Candidate]:
    """A page's repos, each once, without forks."""
    by_name: dict[str, Candidate] = {}
    for item in items:
        repo = item.get("repository") or {}
        full_name = repo.get("full_name")
        if not full_name or "/" not in full_name or repo.get("fork"):
            continue
        by_name.setdefault(full_name.lower(), Candidate(full_name=full_name, source=SOURCE, meta=dict(repo)))
    return list(by_name.values())


def _page(gh: GitHub, query: str, page: int) -> tuple[int, int, list[Candidate]]:
    """(total results, items on this page, the page's repos with their basic facts)."""
    total, items = gh.search_code(query, page=page, per_page=PER_PAGE)
    return total, len(items), with_basics(gh, _candidates(items))


def fetch(gh: GitHub, query: str, *, max_pages: int = 10) -> Iterator[Candidate]:
    """One search's first pages, for ``docscout discover`` samples."""
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        total, count, found = _page(gh, query, page)
        for cand in found:
            if cand.full_name.lower() not in seen:
                seen.add(cand.full_name.lower())
                yield cand
        if not count or page * PER_PAGE >= min(total, MAX_RESULTS):
            return


def sweep(
    gh: GitHub, filenames: list[str], size_bands: list[str], cursor: Cursor, *, per_run: int, now: datetime
) -> Iterator[Candidate]:
    """Candidates from the first ``per_run`` bands of the queue, one band after another.

    Each band continues from the page where it stopped; a page counts as done once all of it has
    been handed out. A band with more than 1,000 results is split until its parts can be read to
    their end. A finished band goes to the back of the queue and starts again from page 1.
    """
    queue = _Queue(cursor, start_bands(filenames, size_bands), now)
    for band in queue.bands[: max(1, per_run)]:
        yield from _walk(gh, band, queue)


def _walk(gh: GitHub, band: Band, queue: _Queue) -> Iterator[Candidate]:
    page, cycle, _ = queue.cursor.slice_position(band.key)
    while True:
        total, items = gh.search_code(band.query, page=page, per_page=PER_PAGE)
        if total > MAX_RESULTS and band.high > band.low:
            # More than a search can return: go on with the lower half; the upper one waits its turn
            yield from _walk(gh, queue.split(band), queue)
            return
        yield from with_basics(gh, _candidates(items))
        if not items or page * PER_PAGE >= min(total, MAX_RESULTS):
            queue.cursor.save_slice(band.key, page=1, cycle=cycle + 1)
            queue.finished(band)
            return
        page += 1
        queue.cursor.save_slice(band.key, page=page, cycle=cycle)
