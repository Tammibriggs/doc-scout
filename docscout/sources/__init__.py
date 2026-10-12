"""Discovery sources. Each one yields :class:`Candidate` objects for the queue."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_GITHUB_REPO_URL = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+?)(?:\.git)?/?(?:[#?/].*)?$")


@dataclass
class Candidate:
    full_name: str
    source: str
    # Repo fields as GitHub's API returns them (may be partial until the repo is fetched).
    meta: dict[str, Any] = field(default_factory=dict)
    # Extra classifier prior, e.g. for curated sources that only list real apps.
    prior: float = 0.0
    issues: list[dict[str, Any]] = field(default_factory=list)


def github_full_name(url: str | None) -> str | None:
    """'https://github.com/Owner/Repo.git' -> 'Owner/Repo'; None for non-GitHub URLs."""
    if not url:
        return None
    match = _GITHUB_REPO_URL.match(url.strip())
    if not match:
        return None
    owner, repo = match.groups()
    return f"{owner}/{repo}"
