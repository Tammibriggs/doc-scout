"""Is someone already on it? Gemma decides.

DocScout gathers a project's open pull requests and the comments on its docs issues
(:func:`docscout.analyze.checks.claim_signals`). Gemma reads them next to the gap DocScout
found and lists the ones that overlap it, each with a reason. Code only checks that every
answer names an item it was given, and skips asking when there's nothing to read.

Word matching on titles wasn't enough: on 17 Oct it flagged an offer to fix a licence badge,
a rework of how a docs site deploys, and an install-guide PR left open for 11 months, while
the gaps themselves were untouched.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

import logging

from docscout.analyze.checks import claim_signals
from docscout.find.github import GitHub, GitHubError
from docscout.llm.base import ClaimContext, LLMClient, LLMError, LLMUnavailable
from docscout.run.db import StoredFinding
from docscout.run.sanitize import clean

log = logging.getLogger(__name__)

MAX_PULLS = 15  # the most recently updated open PRs
MAX_COMMENTS = 8  # the latest comments on the docs issues
EXCERPT = 250  # characters of each description or comment


def signature(pulls: list[dict[str, Any]], comments: list[dict[str, Any]]) -> str:
    """Changes when a PR or comment is added, edited or closed, so a project whose PRs and
    comments are unchanged isn't asked about again."""
    key = [(p.get("number"), p.get("updated_at") or p.get("created_at"), p.get("title")) for p in pulls[:MAX_PULLS]]
    key += [(c.get("id"), c.get("updated_at") or c.get("created_at")) for c in comments[-MAX_COMMENTS:]]
    return hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()[:16]


def _day(iso: str | None) -> str:
    return (iso or "")[:10] or "unknown date"


def _excerpt(text: Any) -> str:
    return " ".join(str(text or "").split())[:EXCERPT]


def judge(client: LLMClient, details: dict[str, Any], full_name: str, pulls: list[dict[str, Any]], comments: list[dict[str, Any]], now: datetime) -> list[str]:
    """The PRs and comments the model says overlap the gap, as "what: why" lines. Returns []
    without asking when there are none to read. Raises LLMError."""
    items: list[tuple[str, str]] = []
    described: dict[str, str] = {}
    for pr in pulls[:MAX_PULLS]:
        number = int(pr["number"])
        user = pr.get("user") or {}
        login = str(user.get("login") or "unknown")
        bot = " (a bot)" if user.get("type") == "Bot" or login.endswith("[bot]") else ""
        when = f"opened {_day(pr.get('created_at'))}, last updated {_day(pr.get('updated_at') or pr.get('created_at'))}"
        lines = [
            f"Title: {pr.get('title', '')}",
            f"Branch: {(pr.get('head') or {}).get('ref', '')}",
            f"By {login}{bot}, {when}{', draft' if pr.get('draft') else ''}",
        ]
        if pr.get("files"):
            lines.append("Changed files: " + ", ".join(str(f) for f in pr["files"][:10]))
        if _excerpt(pr.get("body")):
            lines.append("Description: " + _excerpt(pr.get("body")))
        items.append((f"PR #{number}", "\n".join(lines)))
        described[f"PR #{number}"] = f'Open PR #{number} "{clean(pr.get("title", ""), 80)}"'
    for i, comment in enumerate(comments[-MAX_COMMENTS:], 1):
        issue = comment.get("issue") or {}
        login = str((comment.get("user") or {}).get("login") or "unknown")
        day = _day(comment.get("created_at"))
        items.append((f"comment {i}", f"On issue #{issue.get('number')}, by {login}, {day}: {_excerpt(comment.get('body'))}"))
        described[f"comment {i}"] = f"{clean(login, 40)} on #{issue.get('number')} ({day})"
    if not items:
        return []

    gap = details.get("gap") or {}
    biggest = sorted(gap.get("findings") or [], key=lambda f: -(len(f.get("examples") or []) + int(f.get("more") or 0)))
    ctx = ClaimContext(
        full_name=full_name,
        today=now.date().isoformat(),
        gap=[gap.get("summary", "")] + [f.get("text", "") for f in biggest[:5]],
        issues=[f"#{i.get('number')} {i.get('title', '')}" for i in (details.get("issues") or [])[:2]],
        items=items,
    )
    claimed: dict[str, str] = {}
    for claim in client.claims(ctx).claims:
        what = described.get(claim.item.strip())
        if what is not None and what not in claimed:  # only items it was given, once each
            claimed[what] = f"{what}: {clean(claim.reason, 200)}" if claim.reason else what
    return list(claimed.values())


def check(gh: GitHub, client: LLMClient, finding: StoredFinding, now: datetime) -> bool:
    """Ask the model whether someone is already on the gap, and record the answer in the
    finding's details. Skips asking when the open PRs and comments haven't changed since its
    last answer. False when GitHub or the model failed: the answer stays as it was (or
    unchecked) and a later run asks again. LLMUnavailable is raised: stop asking this run."""
    d = finding.details
    try:
        pulls, comments = claim_signals(gh, finding.full_name, d.get("issues") or [])
    except GitHubError as exc:
        log.info("couldn't read the open PRs and comments of %s: %s", finding.full_name, exc)
        return False
    checks = d.get("checks") or {}
    key = signature(pulls, comments)
    if not (checks.get("claim_checked") and d.get("claims_signature") == key):
        try:
            claimed = judge(client, d, finding.full_name, pulls, comments, now)
        except LLMUnavailable:
            raise
        except LLMError as exc:
            log.info("%s couldn't judge the claims on %s: %s", client.name, finding.full_name, exc)
            return False
        d["checks"] = {**checks, "claimed": claimed, "claim_checked": True}
        d["claims_signature"] = key
        d["claims_model"] = client.name if (pulls or comments) else None
    d["claims_checked"] = now.isoformat(timespec="seconds")
    return True
