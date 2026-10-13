"""Source: GitHub repository search, split into slices.

A slice is one configured query in one star band. Slicing keeps every query under
GitHub's 1000-result cap, and lets a daily run work through a few slices at a time.

Daily runs use :func:`sweep`: a cursor remembers which page each slice reached, so
day after day the search moves on through the results instead of repeating page 1.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Protocol

from docscout.github import GitHub
from docscout.sources import Candidate, interleave

SOURCE = "repo_search"
PER_PAGE = 100
MAX_RESULTS = 1000  # GitHub returns at most this many results per query


class Cursor(Protocol):
    """Where each slice stopped; :class:`docscout.db.Store` provides it."""

    def slice_position(self, key: str) -> tuple[int, int, str | None]: ...
    def save_slice(self, key: str, *, page: int, cycle: int) -> None: ...
    def touch_slice(self, key: str, now: datetime) -> None: ...


@dataclass(frozen=True)
class Slice:
    query: str
    stars: tuple[int, int | None]  # None: no upper limit
    qualifiers: str = ""  # e.g. "language:python language:go" (repeated qualifiers mean "any of")

    @property
    def star_range(self) -> str:
        low, high = self.stars
        return f"{low}..{'*' if high is None else high}"

    @property
    def key(self) -> str:
        return f"{self.query}|{self.star_range}|{self.qualifiers}"

    def search_query(self, pushed_since: date) -> str:
        parts = [self.query, f"stars:{self.star_range}", "archived:false fork:false", f"pushed:>{pushed_since.isoformat()}"]
        if self.qualifiers:
            parts.append(self.qualifiers)
        return " ".join(parts)


def all_slices(queries: list[str], star_bands: list, qualifiers: str = "") -> list[Slice]:
    return [Slice(q, (band[0], band[1]), qualifiers) for q in queries for band in star_bands]


def fetch_slice(
    gh: GitHub, slice_: Slice, *, pushed_within_days: int, max_pages: int = 10, today: date | None = None
) -> Iterator[Candidate]:
    pushed_since = (today or date.today()) - timedelta(days=pushed_within_days)
    query = slice_.search_query(pushed_since)
    for page in range(1, max_pages + 1):
        total, items = gh.search_repos(query, page=page)
        for item in items:
            yield Candidate(full_name=item["full_name"], source=SOURCE, meta=item)
        if not items or page * 100 >= min(total, 1000):
            return


def sweep(
    gh: GitHub, slices: list[Slice], cursor: Cursor, *, per_run: int, pushed_within_days: int, today: date, now: datetime
) -> Iterator[Candidate]:
    """Candidates from the ``per_run`` least recently used slices, taking turns between them.

    Each slice continues from the page where it stopped. A page counts as done once all
    of it has been handed out (repos already checked are skipped later at no cost), and
    after the last page the slice starts again from page 1.
    """
    positions = {s.key: cursor.slice_position(s.key) for s in slices}
    chosen = sorted(slices, key=lambda s: (positions[s.key][2] or "", s.key))[: max(1, per_run)]
    for s in chosen:
        cursor.touch_slice(s.key, now)
    since = today - timedelta(days=pushed_within_days)
    yield from interleave(_walk(gh, s, positions[s.key], cursor, since) for s in chosen)


def _walk(gh: GitHub, slice_: Slice, position: tuple[int, int, str | None], cursor: Cursor, since: date) -> Iterator[Candidate]:
    page, cycle, _ = position
    query = slice_.search_query(since)
    while True:
        # Sorted by stars, which change slowly, so pages stay stable from one day to the next.
        total, items = gh.search_repos(query, page=page, per_page=PER_PAGE, sort="stars")
        for item in items:
            yield Candidate(full_name=item["full_name"], source=SOURCE, meta=item)
        if not items or page * PER_PAGE >= min(total, MAX_RESULTS):
            cursor.save_slice(slice_.key, page=1, cycle=cycle + 1)
            return
        page += 1
        cursor.save_slice(slice_.key, page=page, cycle=cycle)
