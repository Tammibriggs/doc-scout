"""Source (optional): GitHub code search for OpenAPI/Swagger spec files.

Finds repos that ship a spec but have no useful topics. Needs a token, is limited to
10 requests per minute, and caps each query at 1000 results, so queries are sliced by
file size. Results carry only basic repo fields, so the repo is fetched later.
"""

from __future__ import annotations

from collections.abc import Iterator

from docscout.find.github import GitHub
from docscout.find.sources import Candidate

SOURCE = "code_search"


def queries(filenames: list[str], size_bands: list[str]) -> list[str]:
    return [f"filename:{name} size:{band}" for name in filenames for band in size_bands]


def fetch(gh: GitHub, query: str, *, max_pages: int = 10) -> Iterator[Candidate]:
    seen: set[str] = set()
    for page in range(1, max_pages + 1):
        total, items = gh.search_code(query, page=page)
        for item in items:
            repo = item.get("repository") or {}
            full_name = repo.get("full_name")
            if not full_name or full_name in seen or repo.get("fork"):
                continue
            seen.add(full_name)
            yield Candidate(full_name=full_name, source=SOURCE, meta=repo)
        if not items or page * 100 >= min(total, 1000):
            return
