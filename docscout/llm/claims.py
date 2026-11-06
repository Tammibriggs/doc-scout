"""Is someone already on it? Claims per gap (M6 step 6c).

A claim covers only the gaps it would close, so a pick moves down only when the work left is
under the size cutoff, not whenever someone touches the docs:

- **An open PR that changes the measured docs file is measured** (:mod:`docscout.analyze.pr_measure`):
  what it claims is what needs work before it and not after. On 6 Nov, Gemma had flagged 14 PRs as
  claims; measured, none fixed a gap.
- **A PR that doesn't change the measured file claims nothing**, unless the spec is generated:
  then the docs work happens in code annotations, so Gemma judges the PR, one gap at a time.
- **Comments are judged by Gemma, one gap at a time**, and only on help requests that ask for
  this work (:mod:`docscout.llm.help_requests`). An offer counts for 30 days from the person's
  last comment on the issue; once their PR appears, the PR is measured instead.

Code checks every answer names an item it was given and a gap the pick has, and skips asking
when nothing changed since the last answer.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from docscout.analyze import pr_measure
from docscout.analyze.checks import claim_signals
from docscout.analyze.gaps import finding_key
from docscout.find.github import GitHub, GitHubError
from docscout.find.health import parse_time
from docscout.llm import help_requests
from docscout.llm.base import ClaimContext, LLMClient, LLMError, LLMUnavailable
from docscout.run.db import StoredFinding
from docscout.run.sanitize import clean

log = logging.getLogger(__name__)

MAX_PULLS = 15  # the most recently updated open PRs
MAX_COMMENTS = 8  # the latest comments on the docs issues
EXCERPT = 250  # characters of each description or comment
OFFER_DAYS = 30  # an offer without a PR counts this long after the person's last comment
INSIDERS = {"OWNER", "MEMBER", "COLLABORATOR"}

# "adds response examples to 12 operations"
PHRASES = {
    "description": "descriptions", "parameters": "parameter descriptions", "request_example": "request examples",
    "response_example": "response examples", "success_schema": "success schemas", "errors": "error responses",
    "status_codes": "status codes", "auth": "auth notes",
}  # fmt: skip
SPEC_PHRASES = {"overview": "an API overview", "security": "authentication descriptions", "tags": "tag descriptions", "servers": "a server address"}
GAP_NAMES = {**PHRASES, **SPEC_PHRASES, "fields": "field descriptions"}


def counted_issues(details: dict[str, Any]) -> list[dict[str, Any]]:
    """The help requests whose comments can hold a claim: only ones asking for this work (an
    offer on an issue about a licence badge isn't an offer to write the API docs)."""
    return [i for i in details.get("issues") or [] if help_requests.counts(i)]


def signature(pulls: list[dict[str, Any]], comments: list[dict[str, Any]]) -> str:
    """Changes when a PR or comment is added, edited, pushed to or closed, so a project whose PRs
    and comments are unchanged isn't asked about again."""
    key = [(p.get("number"), p.get("updated_at") or p.get("created_at"), p.get("title"), (p.get("head") or {}).get("sha")) for p in pulls[:MAX_PULLS]]
    key += [(c.get("id"), c.get("updated_at") or c.get("created_at")) for c in comments[-MAX_COMMENTS:]]
    return hashlib.sha256(json.dumps(key, default=str).encode()).hexdigest()[:16]


def _day(iso: str | None) -> str:
    return (iso or "")[:10] or "unknown date"


def _excerpt(text: Any, limit: int = EXCERPT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _login(item: dict[str, Any]) -> str:
    return str((item.get("user") or {}).get("login") or "unknown")


def _is_bot(item: dict[str, Any]) -> bool:
    user = item.get("user") or {}
    return user.get("type") == "Bot" or str(user.get("login") or "").endswith("[bot]")


def gap_lines(details: dict[str, Any]) -> tuple[list[str], set[str]]:
    """The pick's gaps as Gemma reads them ("[errors] 9/9 operations ..."), and their keys."""
    lines, keys = [], set()
    for finding in (details.get("gap") or {}).get("findings") or []:
        key = finding_key(finding)
        if key:
            lines.append(f"[{key}] {finding.get('text', '')}")
            keys.add(key)
    return lines, keys


def _fix_phrase(fixed: dict[str, list[str]], fields: list[str], noun: str) -> str:
    parts = [f"{PHRASES[k]} to {len(ops)} {noun if len(ops) != 1 else noun[:-1]}" for k, ops in fixed.items() if k in PHRASES]
    if fields:
        parts.append(f"descriptions to {len(fields)} field{'s' if len(fields) != 1 else ''}")
    parts += [SPEC_PHRASES[k] for k in fixed if k in SPEC_PHRASES]
    if not parts:
        return "describes more of the operations' fields"
    return "adds " + (", ".join(parts[:-1]) + " and " + parts[-1] if len(parts) > 1 else parts[0])


def measure_pulls(gh: GitHub, full_name: str, details: dict[str, Any], pulls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Each open PR's measured result, reusing a stored one while the PR's head commit is the same."""
    gap = details.get("gap") or {}
    earlier = {p.get("number"): p for p in (details.get("claims") or {}).get("prs") or []}
    results = []
    for pr in pulls[:MAX_PULLS]:
        if _is_bot(pr):
            continue
        head = (pr.get("head") or {}).get("sha")
        stored = earlier.get(pr.get("number"))
        if stored and head and stored.get("head") == head:
            results.append(stored)
            continue
        try:
            result = pr_measure.measure(gh, full_name, gap, pr)
        except GitHubError as exc:
            log.info("couldn't measure PR #%s of %s: %s", pr.get("number"), full_name, exc)
            result = {"number": pr.get("number"), "head": None, "touches": False, "readable": False, "fixed": {}, "fixed_fields": []}
        results.append({**result, "title": clean(pr.get("title", ""), 120), "author": _login(pr)})
    return results


def judge(client: LLMClient, details: dict[str, Any], full_name: str, items: list[tuple[str, str]], now: datetime) -> list[dict[str, Any]]:
    """Gemma's claims among ``items`` (comments, and PRs on a generated spec): each with the keys of
    the gaps it covers. Only items it was given, and only gaps the pick has. Raises LLMError."""
    if not items:
        return []
    lines, keys = gap_lines(details)
    issues = [f"#{i.get('number')} {i.get('title', '')}: {_excerpt(i.get('text'), 300)}" for i in counted_issues(details)[:2]]
    ctx = ClaimContext(full_name=full_name, today=now.date().isoformat(), gap=lines, issues=issues, items=items)
    labels = {label for label, _ in items}
    claims: dict[str, dict[str, Any]] = {}
    for claim in client.claims(ctx).claims:
        item = claim.item.strip()
        gaps = sorted({g for g in claim.gaps if g in keys})
        if item in labels and gaps and item not in claims:
            claims[item] = {"item": item, "gaps": gaps, "reason": clean(claim.reason, 200)}
    return list(claims.values())


def _offer_state(comment: dict[str, Any], comments: list[dict[str, Any]], pulls: list[dict[str, Any]], now: datetime) -> tuple[str, str]:
    """("live", "stale" or "pr", the person's last comment on the issue). An offer counts for 30
    days after the person's last comment there; once they have an open PR, the PR is measured
    instead ("pr")."""
    login, issue = _login(comment), (comment.get("issue") or {}).get("number")
    times = [parse_time(c.get("created_at")) for c in comments if _login(c) == login and (c.get("issue") or {}).get("number") == issue]
    last = max((t for t in times if t), default=parse_time(comment.get("created_at")))
    when = last.isoformat(timespec="seconds") if last else ""
    if any(_login(p) == login for p in pulls):
        return "pr", when
    return ("live" if last and now - last <= timedelta(days=OFFER_DAYS) else "stale"), when


def check(gh: GitHub, client: LLMClient, finding: StoredFinding, now: datetime, min_units: int = 5) -> bool:
    """Work out who is on which of the pick's gaps, and record it in the finding's details:
    ``details["claims"]`` (measured PRs, offers, the work left) and the lines a card shows.
    Skips asking when the open PRs and comments haven't changed since the last answer. False
    when GitHub or Gemma failed: the answer stays as it was and a later run tries again.
    LLMUnavailable is raised: stop asking this run."""
    d = finding.details
    try:
        pulls, comments = claim_signals(gh, finding.full_name, counted_issues(d))
    except GitHubError as exc:
        log.info("couldn't read the open PRs and comments of %s: %s", finding.full_name, exc)
        return False
    checks = d.get("checks") or {}
    key = signature(pulls, comments)
    if checks.get("claim_checked") and d.get("claims_signature") == key and "claims" in d:
        d["claims_checked"] = now.isoformat(timespec="seconds")
        return True

    gap = d.get("gap") or {}
    measured = measure_pulls(gh, finding.full_name, d, pulls)
    by_number = {m.get("number"): m for m in measured}
    # Gemma reads the comments (not bots'), and the PRs on a generated spec that don't change it.
    items: list[tuple[str, str]] = []
    said: dict[str, dict[str, Any]] = {}
    for i, comment in enumerate([c for c in comments if not _is_bot(c)][-MAX_COMMENTS:], 1):
        role = " (a maintainer)" if comment.get("author_association") in INSIDERS else ""
        issue = (comment.get("issue") or {}).get("number")
        items.append((f"comment {i}", f"On issue #{issue}, by {_login(comment)}{role}, {_day(comment.get('created_at'))}: {_excerpt(comment.get('body'))}"))
        said[f"comment {i}"] = comment
    if gap.get("generated"):
        for pr in pulls[:MAX_PULLS]:
            if _is_bot(pr) or (by_number.get(pr.get("number")) or {}).get("touches"):
                continue
            lines = [f"Title: {pr.get('title', '')}", f"By {_login(pr)}, opened {_day(pr.get('created_at'))}, last updated {_day(pr.get('updated_at'))}"]
            if pr.get("files"):
                lines.append("Changed files: " + ", ".join(str(f) for f in pr["files"][:10]))
            if _excerpt(pr.get("body")):
                lines.append("Description: " + _excerpt(pr.get("body")))
            items.append((f"PR #{pr.get('number')}", "\n".join(lines)))
            said[f"PR #{pr.get('number')}"] = pr
    try:
        judged = judge(client, d, finding.full_name, items, now)
    except LLMUnavailable:
        raise
    except LLMError as exc:
        log.info("%s couldn't judge the claims on %s: %s", client.name, finding.full_name, exc)
        return False

    noun = "operations" if gap.get("kind") == "spec" else "endpoints"
    claimed: list[str] = []
    stale: list[str] = []
    covered: dict[str, set[str]] = {}
    whole: set[str] = set()
    for m in measured:
        if m.get("fixed") or m.get("fixed_fields"):
            claimed.append(f'Open PR #{m["number"]} "{m.get("title", "")}" {_fix_phrase(m.get("fixed") or {}, m.get("fixed_fields") or [], noun)}')
            for k, ops in (m.get("fixed") or {}).items():
                covered.setdefault(k, set()).update(ops)
    offers = []
    for answer in judged:
        item = said[answer["item"]]
        names = ", ".join(GAP_NAMES.get(g, g) for g in answer["gaps"])
        if answer["item"].startswith("PR #"):
            claimed.append(f'Open PR #{item.get("number")} "{clean(item.get("title", ""), 120)}" ({names}): {answer["reason"]}')
            whole.update(answer["gaps"])
            continue
        state, last = _offer_state(item, comments, pulls, now)
        issue, day = (item.get("issue") or {}).get("number"), _day(item.get("created_at"))
        offers.append({"issue": issue, "author": _login(item), "date": day, "last": last, "gaps": answer["gaps"], "reason": answer["reason"],
                       "live": state == "live", "state": state})  # fmt: skip
        if state == "live":
            claimed.append(f"{clean(_login(item), 40)} on #{issue} ({day}) offered to work on {names}: {answer['reason']}")
            whole.update(answer["gaps"])
        elif state == "stale":
            stale.append(f"{clean(_login(item), 40)} offered on #{issue} ({day}) to work on {names}, with no PR or comment since: ask whether they're still on it")

    left = total = None
    if covered or whole:
        failing = pr_measure.main_failing(gh, finding.full_name, gap)
        if failing is not None:
            left, total = pr_measure.work_left(failing, covered, whole)
    d["claims"] = {"prs": measured, "offers": offers, "work_left": left, "work": total, "noun": noun}
    d["checks"] = {**checks, "claimed": claimed, "stale_offers": stale, "claim_checked": True,
                   "claimed_out": left is not None and left < min_units}  # fmt: skip
    d["claims_signature"] = key
    d["claims_model"] = client.name if items else None
    d["claims_checked"] = now.isoformat(timespec="seconds")
    return True
