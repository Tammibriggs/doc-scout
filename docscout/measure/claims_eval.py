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


# ---------------------------------------------------------------------- claims (step 6c)

# How a gap reads to Gemma in the test set, whose cases name only the keys.
GAP_TEXT = {
    "description": "12/40 operations have no summary or description", "parameters": "9/40 operations have parameters without descriptions",
    "fields": "120/300 fields have no description", "request_example": "18/20 operations that take a request body have no request example",
    "response_example": "38/40 operations have no example of a successful response", "success_schema": "10/40 operations have no schema for a successful response",
    "errors": "40/40 operations don't describe their error responses", "status_codes": "19/19 endpoints list no status or error codes",
    "auth": "16/19 endpoints don't say how to authenticate", "tags": "6 operation groups (tags) have no description",
    "security": "1/1 authentication schemes have no description", "overview": "The API overview (info.description) is missing or very short",
    "servers": "No server address is given, so readers can't tell where to send requests",
}  # fmt: skip


@dataclass
class ClaimResult:
    case: str  # what it is: the comment or PR, shortened
    source: str  # real | made up
    expected: list[str]  # the gaps it should be found to cover (empty: not a claim)
    found: list[str]  # the gaps Gemma said it covers
    model: str
    seconds: float


def _ask_one(client: LLMClient, gaps: list[str], issue: str | None, label: str, text: str, today: str) -> list[str]:
    from docscout.llm.base import ClaimContext

    lines = [f"[{k}] {GAP_TEXT[k]}" for k in gaps]
    ctx = ClaimContext(full_name="eval/case", today=today, gap=lines, issues=[issue] if issue else [], items=[(label, text)])
    found = set()
    for claim in client.claims(ctx).claims:
        if claim.item.strip() == label:
            found |= {g for g in claim.gaps if g in gaps}
    return sorted(found)


def measure_claims(client: LLMClient, data: dict[str, Any], today: str, clock: Callable[[], float] = time.monotonic) -> list[ClaimResult]:
    """Gemma's per-gap answers on the test set's comments and PRs on a generated spec. Bounty
    programs' comments and bots' are left out, as a run leaves them out before asking."""
    results = []
    for case in data["offers"]:
        if case["bounty"] or str(case["author"]).endswith("[bot]"):
            continue
        ctx = case["context"]
        role = " (a maintainer)" if case.get("association") in ("OWNER", "MEMBER", "COLLABORATOR") else ""
        text = f"On issue #1, by {case['author']}{role}, {case['date']}: {' '.join(str(case['text']).split())[:250]}"
        started = clock()
        try:
            found = _ask_one(client, ctx["gaps"], f"#1 {ctx['issue_title']}", "comment 1", text, today)
        except LLMUnavailable:
            raise
        except LLMError:
            found = ["error"]
        results.append(ClaimResult(" ".join(str(case["text"]).split())[:70], case["source"], case["label"]["gaps"], found, client.name, clock() - started))
    for case in data["generated_spec_prs"]:
        text = f"Title: {case['title']}\nChanged files: {', '.join(case['files'])}"
        started = clock()
        try:
            found = _ask_one(client, case["context"]["gaps"], None, "PR #1", text, today)
        except LLMUnavailable:
            raise
        except LLMError:
            found = ["error"]
        results.append(ClaimResult(f"PR: {case['title']}"[:70], case["source"], case["label"]["gaps"], found, client.name, clock() - started))
    return results


def claims_passed(results: list[ClaimResult]) -> bool:
    """Every real claim found (with at least one of its gaps), and at most one wrong claim."""
    missed = [r for r in results if r.expected and not set(r.found) & set(r.expected)]
    false = [r for r in results if not r.expected and r.found]
    return not missed and len(false) <= 1


def format_claims(results: list[ClaimResult]) -> str:
    lines = [f"Claims: {len(results)} comments and PRs on a generated spec, answered by {', '.join(sorted({r.model for r in results}))}", ""]
    for r in results:
        ok = (set(r.found) & set(r.expected)) if r.expected else not r.found
        exact = " (exactly)" if r.expected and set(r.found) == set(r.expected) else ""
        lines.append(f"  {'✓' if ok else '✗'} [{r.source}] {r.case}")
        lines.append(f"      expected {', '.join(r.expected) or 'no claim'}; Gemma: {', '.join(r.found) or 'no claim'}{exact}")
    positives = [r for r in results if r.expected]
    found = [r for r in positives if set(r.found) & set(r.expected)]
    false = [r for r in results if not r.expected and r.found]
    lines += [
        "",
        f"Real claims found: {len(found)} of {len(positives)} (needed: all) {'✅' if len(found) == len(positives) else '❌'}",
        f"  with exactly the right gaps: {sum(1 for r in positives if set(r.found) == set(r.expected))} of {len(positives)}",
        f"Claims Gemma made that aren't: {len(false)} (needed: at most 1) {'✅' if len(false) <= 1 else '❌'}",
    ]
    return "\n".join(lines)


def measure_flagged_prs(gh: Any, data: dict[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    """The PRs Gemma flagged as claims on 6 Nov, measured under the current rules on GitHub as it is now."""
    from docscout.analyze import pr_measure

    results = []
    for flagged in data["flagged"]:
        for item in flagged["items"]:
            if item["kind"] != "pr":
                continue
            pr = gh.get_json(f"/repos/{flagged['repo']}/pulls/{item['number']}")
            shaped = {"number": pr.get("number"), "head": {"sha": (pr.get("head") or {}).get("sha")}, "base": {"sha": (pr.get("base") or {}).get("sha")},
                      "files": [], "changed_files": None}  # fmt: skip
            results.append((flagged["repo"], item["number"], {**pr_measure.measure(gh, flagged["repo"], flagged["gap"], shaped), "state": pr.get("state")}))
    return results


def format_flagged_prs(results: list[tuple[str, int, dict[str, Any]]]) -> str:
    lines = [f"The {len(results)} PRs flagged as claims on 6 Nov, measured under the current rules:", ""]
    for repo, number, r in results:
        fixed = {k: len(v) for k, v in (r.get("fixed") or {}).items()}
        what = ("fixes " + ", ".join(f"{k} for {n}" for k, n in fixed.items())) if fixed else ("changes the measured file but fixes none of its gaps" if r["touches"] else "doesn't change the measured file")
        if r.get("fixed_fields"):
            what += f"; describes {len(r['fixed_fields'])} fields"
        lines.append(f"  {repo}#{number} ({r.get('state')}): {what if r['readable'] else 'couldn\'t be measured'}")
    claiming = sum(1 for _, _, r in results if r.get("fixed") or r.get("fixed_fields"))
    lines += ["", f"PRs that fix a measured gap: {claiming} of {len(results)}"]
    return "\n".join(lines)
