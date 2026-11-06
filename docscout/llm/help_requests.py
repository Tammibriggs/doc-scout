"""Does a help request ask for the work DocScout found? Gemma decides (docs/PLAN.md section 21, step 6b).

A maintainer's "help wanted" or docs issue earns a project a score bonus, the "Maintainers
asked for help" line, a looser activity check, and, when DocScout can't measure the docs, a
place on the list at all. On 6 Nov only 5 of the 23 listed picks with one asked for the work
DocScout found; the others were about licence badges, code bugs, other APIs or copy buttons.

So Gemma reads each issue next to the gaps and answers one of three ways
(:data:`docscout.llm.base.HelpVerdict`); only "this_work" counts. Code keeps it in bounds:
bounty-program issues never reach it, a "this_work" answer counts only if its quote is really
in the issue, and an issue is asked about again only when its text changes.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from docscout.analyze.scoring import Score, opportunity_score
from docscout.find.github import GitHub, GitHubError
from docscout.find.health import PRStats, gate_activity
from docscout.llm.base import HelpContext, LLMClient

log = logging.getLogger(__name__)

TEXT_CHARS = 1500  # of each issue's text, as Gemma reads it
_COMMENT = re.compile(r"(?s)<!--.*?-->")
_QUOTES = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "`": ""})
NOT_ASKED = ("bounty", "closed", "deleted")  # verdicts code gives without asking


def issue_text(body: Any) -> str:
    """The start of an issue's text, without HTML comments (issue templates are full of them)."""
    text = _COMMENT.sub("", str(body or "")).replace("\r\n", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()[:TEXT_CHARS]


def fetch_text(gh: GitHub, full_name: str, issue: dict[str, Any]) -> bool:
    """Read the issue's state and the start of its text into ``issue``. A deleted or moved issue
    gets the state "deleted". False when GitHub failed: the issue keeps what it had."""
    try:
        data = gh.get_issue(full_name, int(issue["number"]))
    except GitHubError as exc:
        log.info("couldn't read %s#%s: %s", full_name, issue.get("number"), exc)
        return False
    if data is None:
        issue["state"], issue["text"] = "deleted", ""
        return True
    issue["state"] = data.get("state") or "open"
    issue["title"] = data.get("title") or issue.get("title", "")
    issue["text"] = issue_text(data.get("body"))
    issue["updated_at"] = data.get("updated_at")
    return True


def is_bounty(issue: dict[str, Any], label_denylist: list[str]) -> bool:
    labels = [str(label).lower() for label in issue.get("labels") or []]
    return any(bad.lower() in label for label in labels for bad in label_denylist)


def signature(issue: dict[str, Any]) -> str:
    """Changes when the issue's title or text changes, so it's asked about again."""
    key = f"{issue.get('title', '')}\n{issue.get('text', '')}"
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()[:16]


def _norm(text: str) -> str:
    return " ".join(text.translate(_QUOTES).lower().split()).strip(" '\".,;:!?()[]*_-")


def quote_found(quote: str, issue: dict[str, Any]) -> bool:
    """True if the quote really is in the issue's title or text (case and spacing aside)."""
    q = _norm(quote)
    return len(q) >= 3 and q in _norm(f"{issue.get('title', '')}\n{issue.get('text', '')}")


def counts(issue: dict[str, Any]) -> bool:
    """True if the issue counts as maintainers asking for this work. An issue Gemma hasn't been
    asked about yet counts, as before M6 (the setting is off, or a later run asks)."""
    answer = issue.get("help")
    if answer is None:
        return True
    return answer.get("verdict") == "this_work" and bool(answer.get("verified"))


def related(issue: dict[str, Any]) -> bool:
    """API-docs work, but not the gaps DocScout found: shown as a related issue."""
    return (issue.get("help") or {}).get("verdict") == "other_api_docs"


def _context(details: dict[str, Any], full_name: str, issue: dict[str, Any]) -> HelpContext:
    gap = details.get("gap") or {}
    findings = [f.get("text", "") for f in gap.get("findings") or []]
    measured = bool(findings)
    # What was measured and where, so an issue about another API (a library's functions, the app's
    # commands) isn't read as one about these gaps (PictoPy and holographic-memory, 6 Nov).
    where = [f"Measured in: {gap['location']}"] if measured and gap.get("location") else []
    lines = ([gap.get("summary", "")] + where + findings) if measured else list(gap.get("check_manually") or [])
    return HelpContext(
        full_name=full_name,
        gap=[line for line in lines if line],
        measured=measured,
        title=str(issue.get("title", "")),
        labels=[str(label) for label in issue.get("labels") or []],
        text=str(issue.get("text", "")),
    )


def ask(client: LLMClient, details: dict[str, Any], full_name: str, issue: dict[str, Any]) -> dict[str, Any]:
    """Gemma's answer about one issue, as kept in ``issue["help"]``. Raises LLMError."""
    answer = client.help_request(_context(details, full_name, issue))
    return {
        "verdict": answer.verdict,
        "quote": answer.quote,
        "reason": answer.reason,
        "verified": quote_found(answer.quote, issue),
        "model": client.name,
        "signature": signature(issue),
    }


def due(issue: dict[str, Any], label_denylist: list[str]) -> bool:
    """True if Gemma needs to be asked: never asked, or the text changed since."""
    if is_bounty(issue, label_denylist) or issue.get("state") in ("closed", "deleted"):
        return False
    answer = issue.get("help")
    return answer is None or answer.get("verdict") in NOT_ASKED or answer.get("signature") != signature(issue)


def check(client: LLMClient, details: dict[str, Any], full_name: str, label_denylist: list[str]) -> int:
    """Ask about each of the finding's help requests that's due, and mark bounty, closed and
    deleted ones without asking. Updates ``details`` in place; returns how many were asked.
    Raises LLMError, so a finding is never half checked."""
    asked = 0
    for issue in details.get("issues") or []:
        if is_bounty(issue, label_denylist):
            issue["help"] = {"verdict": "bounty"}
        elif issue.get("state") in ("closed", "deleted"):
            issue["help"] = {"verdict": issue["state"]}
        elif due(issue, label_denylist):
            issue["help"] = ask(client, details, full_name, issue)
            asked += 1
    return asked


def needs_check(details: dict[str, Any], label_denylist: list[str]) -> bool:
    return any(due(i, label_denylist) or (i.get("help") is None) for i in details.get("issues") or [])


def effects(details: dict[str, Any], health_cfg: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    """The issues that count as help requests, and why the finding can't be reported without
    one (None if it can). A project with no help requests at all is unaffected."""
    issues = details.get("issues") or []
    counted = [i for i in issues if counts(i)]
    if counted or not issues:
        return counted, None
    # Docs that may live elsewhere are listed only when maintainers asked for help with them
    # (pipeline.analyze, since 13 Oct), so a request that doesn't count leaves them unlisted.
    if (details.get("gap") or {}).get("check_manually"):
        return [], "its docs may be elsewhere, and no help request asks for API docs work"
    stats = details.get("stats") or {}
    known = {k: stats[k] for k in PRStats.__dataclass_fields__ if k in stats}
    if known and gate_activity(PRStats(**known), health_cfg):
        return [], "it passed the activity check only because of a help request that isn't about the API docs"
    return [], None


def rescore(details: dict[str, Any], cfg: Any, counted: list[dict[str, Any]]) -> Score:
    """The finding's score with only the help requests that count, everything else as it was."""
    parts = details.get("score") or {}
    score = opportunity_score(
        float((details.get("gap") or {}).get("score", 0)),
        float(parts.get("health", 0)),
        float(parts.get("type_confidence", details.get("code_confidence", 0))),
        counted,
        (details.get("repo") or {}).get("language_match"),
        int(cfg["scoring"]["language_bonus"]),
        int(parts.get("published_bonus", 0)),
    )
    details["score"], details["breakdown"] = score.as_dict(), score.breakdown()
    return score
