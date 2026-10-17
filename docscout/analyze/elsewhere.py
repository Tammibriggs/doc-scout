"""Signs that a project's docs live outside the repo (website, docs host, separate repo).

Until DocScout can read external pages (stage M4), these only mark an item "check
manually" and cap its gap score, instead of claiming the project has no docs.

They're also good news: docs published as pages are what writers want to work on
(:func:`published_docs`), so they raise a project's score.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

_MD_LINK = re.compile(r"\[([^\]\n]{1,120})\]\((https?://[^\s)]{1,300})\)")
_DOC_WORDS = re.compile(r"\b(docs?|documentation|api|reference|swagger|redoc|developers?|guides?|manual|wiki)\b", re.IGNORECASE)
_DOC_HOSTS = re.compile(r"(^docs?\.|readthedocs\.io$|gitbook\.io$|\.github\.io$|^developers?\.)", re.IGNORECASE)
_SIBLING = re.compile(r"(^|[-_.])(docs?|documentation|website|site|api-docs|handbook)([-_.]|$)", re.IGNORECASE)
_SIBLING_WORDS = re.compile(r"documentation|handbook|website|github|docs?|site|api|io", re.IGNORECASE)  # longest first
# Name parts too common to tie a docs repo to one project ("apache/airflow-site" isn't OFBiz's).
_GENERIC_PARTS = {"app", "api", "core", "web", "server", "service", "backend", "frontend", "framework", "platform", "project"}
SMALL_OWNER = 10  # an owner with this many public repos or fewer is treated as one product
# Badges, package registries and code-reference sites: README links to them mention the
# project but aren't its docs (seen 16 Oct: zot's pkg.go.dev and app.fossa.com badges).
_NOT_DOCS_HOSTS = (
    "shields.io", "badgen.net", "codecov.io", "coveralls.io", "travis-ci.org", "travis-ci.com",
    "pkg.go.dev", "godoc.org", "goreportcard.com", "fossa.com", "bestpractices.dev",
    "bestpractices.coreinfrastructure.org", "securityscorecards.dev", "scorecard.dev", "artifacthub.io",
    "sonarcloud.io", "snyk.io", "hub.docker.com", "pypi.org", "npmjs.com", "crates.io", "docs.rs",
)
# Files that build a docs website from the repo. MkDocs, Read the Docs, Docusaurus, mdBook,
# Mintlify, Antora and VitePress count at the top level or in a docs folder; Sphinx's conf.py,
# Mintlify's docs.json and Jekyll's _config.yml only in a docs folder, where they can't mean anything else.
_SITE_CONFIG = re.compile(
    r"^((docs?|documentation|website|site)/)?(mkdocs\.ya?ml|\.?readthedocs\.ya?ml|docusaurus\.config\.[cm]?[jt]s"
    r"|book\.toml|mint\.json|antora\.ya?ml|\.vitepress/config\.[cm]?[jt]s)$"
    r"|^(docs?|documentation)/(source/)?(conf\.py|docs\.json|_config\.ya?ml)$",
    re.IGNORECASE,
)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _address(url: str) -> str:
    """The site and path, without the scheme, query or trailing slash: a bare host can be
    the wrong page (eikek.github.io returns 404; the docs are at eikek.github.io/sharry)."""
    parts = urlsplit(url)
    return ((parts.hostname or "").lower() + parts.path.rstrip("/"))[:100]


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _name_tokens(full_name: str) -> set[str]:
    """'Bubka/2FAuth' -> {'bubka', '2fauth'}: the full owner and repo names, which a project's own
    docs address would contain. Parts of a name don't count: "django" from django-crm would
    match Django's own docs."""
    return {t for t in (_squash(part) for part in full_name.split("/")) if len(t) >= 3}


def _repo_parts(name: str) -> set[str]:
    """'ofbiz-framework' -> {'ofbizframework', 'ofbiz'}: the distinctive parts of a repo name."""
    parts = {_squash(name)}
    parts.update(t for t in re.split(r"[^a-z0-9]+", name.lower()) if t not in _GENERIC_PARTS)
    return {t for t in parts if len(t) >= 3}


def doc_links(readme: str, full_name: str, limit: int = 2) -> list[str]:
    """Addresses the README links to for this project's docs, as site and path (one per site).

    Only addresses that mention the project or its owner count, so links to the docs of
    a framework or library it uses (e.g. laravel.com/docs) are ignored.
    """
    tokens = _name_tokens(full_name)
    found: list[str] = []
    sites: set[str] = set()
    for text, url in _MD_LINK.findall(readme):
        host = _host(url)
        parts = urlsplit(url)
        # Leave out the domain ending, so an owner named "org" doesn't match every .org site.
        haystack = re.sub(r"[^a-z0-9]", "", "".join(host.split(".")[:-1]) + parts.path.lower())
        if not any(token in haystack for token in tokens):
            continue
        if host in ("github.com", "www.github.com"):
            continue  # same-repo files are analyzed directly; other repos are found by sibling_repos
        if host.endswith(_NOT_DOCS_HOSTS):
            continue
        if (_DOC_WORDS.search(text) or _DOC_WORDS.search(parts.path) or _DOC_HOSTS.search(host)) and host not in sites:
            sites.add(host)
            found.append(_address(url))
        if len(found) >= limit:
            break
    return found


def sibling_repos(owner_repos: list[dict[str, Any]], full_name: str, limit: int = 2) -> list[str]:
    """Other repos from the same owner whose names suggest docs for this project, as 'owner/name'.

    A named docs repo must name the project ("mylar3-website"). A generic one ("docs",
    "website") counts only when the owner is essentially this one product: the owner's
    name contains the project's, or the owner has few repos. Big organizations host the
    sites of many projects (apache/airflow-site has nothing to do with OFBiz).
    """
    owner, _, repo_name = full_name.partition("/")
    parts = _repo_parts(repo_name)
    one_product = len(owner_repos) <= SMALL_OWNER or any(p in _squash(owner) for p in parts)
    names = []
    for repo in owner_repos:
        name = str(repo.get("full_name") or "")
        sibling = name.split("/")[-1]
        if name.lower() == full_name.lower() or repo.get("archived") or not _SIBLING.search(sibling):
            continue
        rest = _SIBLING_WORDS.sub("", _squash(sibling)).replace(_squash(owner), "")
        if (not rest and one_product) or any(p in _squash(sibling) for p in parts):
            names.append(name)
    return names[:limit]


def published_docs(repo: dict[str, Any], readme: str | None, tree: list[dict[str, Any]], owner_repos: list[dict[str, Any]], full_name: str) -> list[str]:
    """Where the project's docs are published as pages you can read without installing it.

    Graded on 16 Oct: all 6 projects the writer would act on had a docs site, while most
    "no"s showed their API reference only in the running app. Pages let you see the gap in
    a browser, and the fix is Markdown rather than code annotations. A plain project
    homepage doesn't count; a docs host, a docs link or a docs repo does.
    """
    found = []
    configs = sorted(e.get("path", "") for e in tree if e.get("type") == "blob" and _SITE_CONFIG.search(e.get("path", "")))
    if configs:
        found.append(f"Docs site built from this repo ({configs[0]})")
    homepage = str(repo.get("homepage") or "").strip()
    home_host = _host(homepage) if homepage.startswith(("http://", "https://")) else ""
    sites = [_address(homepage)] if home_host and _DOC_HOSTS.search(home_host) else []
    # A README link counts only when the site itself carries the project's or owner's name
    # (docs.churchcrm.io), not just the path (an article at smarthomescene.com/…/baby-buddy).
    tokens = _name_tokens(full_name)
    named = [
        address for address in doc_links(readme or "", full_name, limit=5)
        if address.split("/")[0] != home_host and any(t in _squash("".join(address.split("/")[0].split(".")[:-1])) for t in tokens)
    ]
    sites += named[:2]
    found += [f"Docs website: {site}" for site in sites]
    found += [f"Separate docs repo: {name}" for name in sibling_repos(owner_repos, full_name)]
    return found


def docs_elsewhere(repo: dict[str, Any], readme: str | None, owner_repos: list[dict[str, Any]], full_name: str) -> list[str]:
    reasons = []
    homepage = str(repo.get("homepage") or "").strip()
    home_host = _host(homepage) if homepage.startswith(("http://", "https://")) else ""
    if home_host and home_host not in ("github.com", "www.github.com"):
        reasons.append(f"Project website: {_address(homepage)}")
    reasons += [f"Docs link in the README: {address}" for address in doc_links(readme or "", full_name) if address.split("/")[0] != home_host]
    reasons += [f"Separate docs repo: {name}" for name in sibling_repos(owner_repos, full_name)]
    return reasons
