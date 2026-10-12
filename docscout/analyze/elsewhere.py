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


def _name_tokens(full_name: str) -> set[str]:
    """'Bubka/2FAuth' -> {'bubka', '2fauth'}: names a project's own docs address would contain."""
    tokens = set()
    for part in full_name.lower().split("/"):
        tokens.add(re.sub(r"[^a-z0-9]", "", part))
        tokens.update(t for t in re.split(r"[^a-z0-9]+", part) if len(t) >= 4)
    return {t for t in tokens if len(t) >= 3}


def doc_links(readme: str, full_name: str, limit: int = 2) -> list[str]:
    """Websites the README links to for this project's docs (one entry per host).

    Only addresses that mention the project or its owner count, so links to the docs of
    a framework or library it uses (e.g. laravel.com/docs) are ignored.
    """
    tokens = _name_tokens(full_name)
    found: list[str] = []
    for text, url in _MD_LINK.findall(readme):
        host = _host(url)
        parts = urlsplit(url)
        # Leave out the domain ending, so an owner named "org" doesn't match every .org site.
        haystack = re.sub(r"[^a-z0-9]", "", "".join(host.split(".")[:-1]) + parts.path.lower())
        if not any(token in haystack for token in tokens):
            continue
        if host in ("github.com", "www.github.com"):
            continue  # same-repo files are analyzed directly; other repos are found by sibling_repos
        if host.endswith(("shields.io", "img.shields.io", "badgen.net", "codecov.io", "travis-ci.org", "travis-ci.com")):
            continue
        if (_DOC_WORDS.search(text) or _DOC_WORDS.search(parts.path) or _DOC_HOSTS.search(host)) and host not in found:
            found.append(host)
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
    home_host = _host(homepage) if homepage.startswith(("http://", "https://")) else ""
    if home_host and home_host not in ("github.com", "www.github.com"):
        reasons.append(f"Project website: {home_host}")
    reasons += [f"Docs link in the README: {host}" for host in doc_links(readme or "", full_name) if host != home_host]
    reasons += [f"Separate docs repo: {name}" for name in sibling_repos(owner_repos, full_name)]
    return reasons
