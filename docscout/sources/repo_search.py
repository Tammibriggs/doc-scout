"""Source: GitHub repository search, split into slices.

A slice is one configured query in one star band. Slicing keeps every query under
GitHub's 1000-result cap, and lets a daily run work through a few slices at a time.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

from docscout.github import GitHub
from docscout.sources import Candidate

SOURCE = "repo_search"


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
