"""Signs that a project's docs live outside the repo (website, docs host, separate repo).

Until DocScout can read external pages (stage M4), these only mark an item "check
manually" and cap its gap score, instead of claiming the project has no docs.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_MD_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((https?://[^\s)]{1,300})\)")
_DOC_WORDS = re.compile(r"\b(docs?|documentation|api|reference|swagger|redoc|developers?|guides?|manual|wiki)\b", re.IGNORECASE)
_DOC_HOSTS = re.compile(r"(^docs?\.|readthedocs\.io$|gitbook\.io$|\.github\.io$|^developers?\.)", re.IGNORECASE)
_SIBLING = re.compile(r"(^|[-_.])(docs?|documentation|website|site|api-docs|handbook)([-_.]|$)", re.IGNORECASE)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def doc_links(readme: str, full_name: str, limit: int = 2) -> list[str]:
    """README links that look like documentation outside this repo, as 'host/path'."""
    found = []
    for text, url in _MD_LINK.findall(readme):
        host = _host(url)
        parts = urlsplit(url)
        if host in ("github.com", "www.github.com"):
            continue  # same-repo files are analyzed directly; other repos are found by sibling_repos
        if host.endswith(("shields.io", "img.shields.io", "badgen.net", "codecov.io", "travis-ci.org", "travis-ci.com")):
            continue
        if _DOC_WORDS.search(text) or _DOC_WORDS.search(parts.path) or _DOC_HOSTS.search(host):
            label = f"{host}{parts.path.rstrip('/')}"[:60]
            if label not in found:
                found.append(label)
        if len(found) >= limit:
            break
    return found


def sibling_repos(owner_repos: list[dict[str, Any]], full_name: str, limit: int = 2) -> list[str]:
    """Other repos from the same owner whose names suggest docs, as 'owner/name'."""
    own = full_name.lower()
    names = []
    for repo in owner_repos:
        name = str(repo.get("full_name") or "")
        if name.lower() != own and not repo.get("archived") and _SIBLING.search(name.split("/")[-1]):
            names.append(name)
    return names[:limit]


def docs_elsewhere(repo: dict[str, Any], readme: str | None, owner_repos: list[dict[str, Any]], full_name: str) -> list[str]:
    reasons = []
    homepage = str(repo.get("homepage") or "").strip()
    if homepage.startswith(("http://", "https://")) and _host(homepage) not in ("github.com", "www.github.com"):
        reasons.append(f"Project website: {_host(homepage)}")
    reasons += [f"Docs link in the README: {link}" for link in doc_links(readme or "", full_name)]
    reasons += [f"Separate docs repo: {name}" for name in sibling_repos(owner_repos, full_name)]
    return reasons
