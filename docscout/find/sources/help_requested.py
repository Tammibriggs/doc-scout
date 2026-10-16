"""Source: repos whose maintainers are asking for help with API docs.

This is the language- and framework-agnostic discovery route: an open, unassigned docs
issue is direct evidence that the project wants the contribution. Each enabled API
type adds its own title keywords (``issue_keywords``) to the generic ones.

Live testing showed raw issue search is mostly noise (owners tracking their own plans
in one-person repos, bounty farms, bot dashboards), so an issue only counts if it has
an outreach label or was opened by someone outside the project. Repos found this way
still go through the code-only health gate, with a looser activity check when a
maintainer has explicitly labeled an issue "help wanted" or "good first issue".

Query rules learned from testing: ``label:a,b`` means a OR b (``label:a OR label:b``
returns nothing), and ``OR`` combined with ``in:title`` stops narrowing results, so
there is one query per label family and keyword.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date
from typing import Any

from docscout.find.github import GitHub
from docscout.analyze.scoring import is_docs_label
from docscout.find.sources import Candidate

SOURCE = "help_requested"
INSIDERS = {"OWNER", "MEMBER", "COLLABORATOR"}
OUTREACH_LABELS = ("help wanted", "good first issue")
# An outreach label plus "api" in the title also finds bugs and feature requests (seen 15 Oct:
# "OpenAPI DecimalValue rejects canonical negative fractions", "Accept Claude Platform
# OpenTelemetry export"), so without a docs label the title must be about docs.
_DOCS_TITLE = re.compile(
    r"\b(docs?|documentation|document(ed|ing|s)?|undocumented|readme|guides?|tutorials?|examples?|reference|describe|descriptions?|wiki)\b",
    re.IGNORECASE,
)


def queries(label_families: list[str], keywords: list[str], since: date, qualifiers: str = "") -> list[str]:
    base = f"is:issue is:open no:assignee -linked:pr archived:false updated:>{since.isoformat()}"
    if qualifiers:
        base = f"{base} {qualifiers}"
    return [f"{base} label:{family} {keyword} in:title" for family in label_families for keyword in keywords]


def _norm_label(name: str) -> str:
    return re.sub(r"[-_:]+", " ", name.lower()).strip()


def outreach_labels(issue: dict[str, Any]) -> list[str]:
    found = []
    for label in issue.get("labels") or []:
        name = _norm_label(label.get("name", ""))
        found.extend(o for o in OUTREACH_LABELS if o in name)
    return sorted(set(found))


def is_bot(user: dict[str, Any] | None) -> bool:
    if not user:
        return True
    return user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]")


def is_docs_request(issue: dict[str, Any]) -> bool:
    """A docs label, or a title about docs."""
    if any(is_docs_label(str(label.get("name", ""))) for label in issue.get("labels") or []):
        return True
    return bool(_DOCS_TITLE.search(str(issue.get("title", ""))))


def issue_counts(issue: dict[str, Any], *, label_denylist: list[str], title_denylist: list[str]) -> bool:
    """True if the issue is a real, open invitation to help with docs."""
    if is_bot(issue.get("user")) or not is_docs_request(issue):
        return False
    title = str(issue.get("title", "")).lower()
    if any(term in title for term in title_denylist):
        return False
    labels = [str(label.get("name", "")).lower() for label in issue.get("labels") or []]
    if any(bad in label for label in labels for bad in label_denylist):
        return False
    return bool(outreach_labels(issue)) or issue.get("author_association") not in INSIDERS


def repo_full_name(issue: dict[str, Any]) -> str:
    return issue["repository_url"].split("/repos/", 1)[1]


def fetch(
    gh: GitHub,
    query_list: list[str],
    *,
    label_denylist: list[str],
    title_denylist: list[str],
    max_pages: int = 1,
) -> Iterator[Candidate]:
    """One candidate per repo, carrying every qualifying issue found for it."""
    by_repo: dict[str, Candidate] = {}
    for query in query_list:
        for page in range(1, max_pages + 1):
            total, items = gh.search_issues(query, page=page)
            for issue in items:
                if issue.get("pull_request") or not issue_counts(
                    issue, label_denylist=label_denylist, title_denylist=title_denylist
                ):
                    continue
                name = repo_full_name(issue)
                cand = by_repo.setdefault(name, Candidate(full_name=name, source=SOURCE, meta={"full_name": name}))
                if all(i["html_url"] != issue["html_url"] for i in cand.issues):
                    cand.issues.append(
                        {
                            "html_url": issue["html_url"],
                            "number": issue["number"],
                            "title": issue["title"],
                            "labels": [label.get("name", "") for label in issue.get("labels") or []],
                            "author_association": issue.get("author_association"),
                            "outreach": outreach_labels(issue),
                        }
                    )
            if not items or page * 100 >= min(total, 1000):
                break
    yield from by_repo.values()
