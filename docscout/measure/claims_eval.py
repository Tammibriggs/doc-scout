"""``docscout eval-claims``: measure Gemma's M6 questions on the labeled test set (docs/PLAN.md
section 21, steps 6a and 6b).

For now, the help-request question. Each issue in tests/fixtures/m6/help_requests.json is asked
about the way a run asks: with the pick's gaps, the issue's title, labels and the start of its
text. Your labels are A (asks for the work DocScout found), B (other API-docs work) and C (not API
docs). Per pick, Gemma's best answer is compared with the best label. The exit check: at least 21
of the 23 picks agree, and no pick labeled C ends up counted as a help request.

Bounty-program issues are filtered by code before Gemma ever sees them in a run; they're asked
about here anyway, so all 23 picks are measured, and reported apart.

Live: it asks the configured model. It never runs in the test suite.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from docscout.llm import help_requests
from docscout.llm.base import LLMClient, LLMError, LLMUnavailable

LETTER = {"this_work": "A", "other_api_docs": "B", "not_api_docs": "C"}
RANK = {"A": 0, "B": 1, "C": 2}
MIN_AGREE = 21  # of the 23 picks
NEEDED_PICKS = 23


@dataclass
class HelpResult:
    repo: str
    number: int
    label: str  # yours: A, B or C
    answer: str  # Gemma's: A, B or C, or "error"
    counted: bool  # whether a run would count it: an A whose quote is really in the issue, and not a bounty
    verified: bool
    bounty: bool
    quote: str
    reason: str
    model: str
    seconds: float


def measure_help(client: LLMClient, data: dict[str, Any], label_denylist: list[str], clock: Callable[[], float] = time.monotonic) -> list[HelpResult]:
    results = []
    for case in data["issues"]:
        pick = case.get("pick") or {}
        details = {"gap": {"kind": pick.get("kind"), "summary": pick.get("summary") or "", "location": pick.get("location"),
                           "findings": [{"text": g} for g in pick.get("gaps") or []], "check_manually": pick.get("check_manually") or []}}  # fmt: skip
        issue = {"number": case["number"], "title": case["title"], "labels": case.get("labels") or [], "text": case.get("text") or ""}
        bounty = help_requests.is_bounty(issue, label_denylist)
        started = clock()
        try:
            answer = help_requests.ask(client, details, case["repo"], issue)
        except LLMUnavailable:
            raise
        except LLMError as exc:
            results.append(HelpResult(case["repo"], case["number"], case["label"], "error", False, False, bounty, "", str(exc)[:200], client.name, clock() - started))
            continue
        letter = LETTER[answer["verdict"]]
        counted = letter == "A" and bool(answer["verified"]) and not bounty
        results.append(HelpResult(case["repo"], case["number"], case["label"], letter, counted, bool(answer["verified"]), bounty,
                                  answer["quote"], answer["reason"], answer["model"], clock() - started))  # fmt: skip
    return results


def per_pick(results: list[HelpResult]) -> dict[str, tuple[str, str, bool]]:
    """repo -> (your best label, Gemma's best answer, counted by a run)."""
    picks: dict[str, tuple[str, str, bool]] = {}
    for r in results:
        label, answer, counted = picks.get(r.repo, ("C", "C", False))
        best = min(answer, r.answer, key=lambda a: RANK.get(a, 3)) if r.answer in RANK else answer
        picks[r.repo] = (min(label, r.label, key=RANK.get), best, counted or r.counted)
    return picks


def passed(results: list[HelpResult]) -> bool:
    picks = per_pick(results)
    agree = sum(1 for label, answer, _ in picks.values() if label == answer)
    wrongly_counted = sum(1 for label, _, counted in picks.values() if label == "C" and counted)
    return agree >= MIN_AGREE and wrongly_counted == 0 and len(picks) == NEEDED_PICKS


def format_help(results: list[HelpResult]) -> str:
    picks = per_pick(results)
    models = sorted({r.model for r in results})
    lines = [f"Help requests: {len(results)} issues on {len(picks)} picks, answered by {', '.join(models)}", ""]
    for r in results:
        mark = "✓" if r.answer == r.label else "✗"
        quote = ("quote found" if r.verified else "quote NOT found") if r.answer == "A" else ""
        extra = ", ".join(x for x in ("bounty: filtered by code in a run" if r.bounty else "", quote) if x)
        lines.append(f"  {mark} {r.repo}#{r.number}: yours {r.label}, Gemma {r.answer}{f' ({extra})' if extra else ''}")
        lines.append(f"      {r.reason}")
    agree = sum(1 for label, answer, _ in picks.values() if label == answer)
    wrongly_counted = [repo for repo, (label, _, counted) in picks.items() if label == "C" and counted]
    seconds = [r.seconds for r in results if r.answer != "error"]
    lines += [
        "",
        f"Picks that agree with your labels: {agree} of {len(picks)} (needed: {MIN_AGREE} of {NEEDED_PICKS}) {'✅' if agree >= MIN_AGREE else '❌'}",
        f"Picks labeled C that a run would count: {len(wrongly_counted)}{' (' + ', '.join(wrongly_counted) + ')' if wrongly_counted else ''} (needed: 0) {'✅' if not wrongly_counted else '❌'}",
        f"A answers whose quote isn't in the issue (so they don't count): {sum(1 for r in results if r.answer == 'A' and not r.verified)}",
        f"Bounty-program issues, filtered by code in a run: {sum(1 for r in results if r.bounty)}",
        f"Questions that failed: {sum(1 for r in results if r.answer == 'error')}",
    ]
    if seconds:
        lines.append(f"Seconds per question: {sum(seconds) / len(seconds):.1f} on average, {max(seconds):.1f} at most")
    return "\n".join(lines)
