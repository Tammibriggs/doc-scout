"""``docscout draft owner/repo``: a first message to the maintainers of a project you've picked.

Written by the model from what DocScout found (the docs gaps, any open docs issue),
for you to edit and post yourself; DocScout never posts anything. The claim check runs
again first, so you know if someone started on it since the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from docscout.analyze.checks import Checks, paid_checks
from docscout.db import StoredFinding
from docscout.github import GitHub, GitHubError
from docscout.llm import LLMClient
from docscout.review import context_for
from docscout.sanitize import block, clean, repo_url

NEW_ISSUE = "new issue"


@dataclass
class DraftResult:
    where: str  # "comment on #12 Document the API" or "new issue"
    url: str  # where to post it
    title: str  # for a new issue
    message: str
    warnings: list[str] = field(default_factory=list)  # someone else is on it, CLA, AI policy


def pick_issue(issues: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The open docs issue to reply on: one labeled "help wanted" or "good first issue" first."""
    return next((i for i in issues if i.get("outreach")), issues[0] if issues else None)


def write_draft(client: LLMClient, gh: GitHub | None, finding: StoredFinding, api_label: str) -> DraftResult:
    d = finding.details
    issue = pick_issue(d.get("issues") or [])
    warnings: list[str] = []
    if gh is not None:
        checks = Checks(**(d.get("checks") or {}))
        checks.claimed, checks.requirements = [], []
        try:
            paid_checks(gh, finding.full_name, checks, d.get("check_paths") or {}, d.get("issues") or [], d.get("head_sha"))
        except GitHubError:
            pass
        warnings = [clean(w, 220) for w in checks.claimed + checks.requirements]
    issue_label = f"#{issue.get('number')} {clean(issue.get('title', ''), 120)}" if issue else None
    draft = client.draft(context_for(finding, [api_label]), issue_label)
    if issue:
        where, url = f"comment on {issue_label}", f"{repo_url(finding.full_name)}/issues/{int(issue['number'])}"
    else:
        where, url = NEW_ISSUE, f"{repo_url(finding.full_name)}/issues/new"
    return DraftResult(where, url, clean(draft.title, 120), block(draft.message), warnings)
