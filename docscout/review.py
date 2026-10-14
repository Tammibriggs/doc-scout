"""The model's review: the step that decides which projects are reported.

Code finds candidates, checks their health and measures their docs gaps. The model
(Gemma by default, running locally) then reads each one: the README, description and
topics, the gaps code found, and any docs issues. It decides whether the project really
has an API worth documenting, why its docs matter, and where to start. Only projects it
has reviewed are reported; the rest wait for a later run.

Code keeps the model in bounds: it only sees repos that passed the health checks, it
can raise confidence to at most ``[classify] llm_raise_cap``, and what it writes is
sanitized in the report.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from docscout.apitypes import ApiType
from docscout.config import Config
from docscout.db import Store, StoredFinding
from docscout.llm import LLMClient, LLMError, LLMUnavailable, RepoContext, apply_review, make_client
from docscout.llm import memory
from docscout.llm.base import review_with_retry
from docscout.scoring import opportunity_score

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # a project the model can't give a valid answer for is dropped after this many runs

Reviewer = Callable[[], LLMClient]


@dataclass
class ReviewOutcome:
    reviewed: int = 0
    accepted: int = 0
    rejected: int = 0
    seconds: float = 0.0
    skipped: str | None = None  # why reviews didn't run: low memory, model not available
    waiting: int = 0  # projects still waiting for the model after this run


def open_reviewer(cfg: Config) -> LLMClient:
    llm = cfg["llm"]
    return make_client(llm, api_key=cfg.secret(llm["api_key_env"]))


def model_label(name: str) -> str:
    """'ollama:gemma4:e2b' -> 'Gemma'; other models by name."""
    return "Gemma" if "gemma" in name.lower() else name.split(":", 1)[-1]


def potential_confidence(code_confidence: float, cap: float) -> float:
    """The type confidence a finding gets if the model confirms it (see :func:`apply_review`)."""
    return max(code_confidence, cap)


def think_for(mode: str, code_confidence: float, min_confidence: float) -> bool:
    """[llm] think: off, on, or borderline (only where the code classifier is unsure)."""
    return mode == "on" or (mode == "borderline" and code_confidence < min_confidence)


_GUESSES = ("app words", "tool words", "library words", "spam")


def factual_checks(reasons: list[str]) -> list[str]:
    """The classifier's evidence that was measured from files, without its keyword guesses
    ("app words: ...") and weights, so the model judges the wording independently."""
    checks = []
    for reason in reasons:
        if not reason or reason.lower().startswith(_GUESSES):
            continue
        if reason.lower().startswith("curated source"):
            reason = "listed in awesome-selfhosted, a curated list of self-hosted apps"
        checks.append(re.sub(r"\s*\([+-]?\d[\d.]*\)", "", reason).strip())
    return checks


def context_for(finding: StoredFinding, wanted: list[str]) -> RepoContext:
    d = finding.details
    gap: dict[str, Any] = d.get("gap") or {}
    repo: dict[str, Any] = d.get("repo") or {}
    findings = [gap.get("summary", "")] + [f.get("text", "") for f in gap.get("findings") or []] + list(gap.get("check_manually") or [])
    issues = [
        f"#{i.get('number')} {i.get('title', '')}" + (f" ({', '.join(i['outreach'])})" if i.get("outreach") else "")
        for i in d.get("issues") or []
    ]
    return RepoContext(
        full_name=finding.full_name,
        description=repo.get("description") or "",
        topics=list(repo.get("topics") or []),
        language=repo.get("language"),
        readme_excerpt=d.get("readme_excerpt") or "",
        findings=[f for f in findings if f],
        issues=issues,
        wanted_api_types=wanted,
        checks=factual_checks(list(d.get("reasons") or [])),
    )


def review_waiting(
    store: Store,
    cfg: Config,
    now: datetime,
    types_by_key: dict[str, ApiType],
    *,
    limit: int,
    reviewer: Reviewer,
    progress: Callable[[str], None] = lambda message: None,
    clock: Callable[[], float] = time.monotonic,
) -> ReviewOutcome:
    """Review up to ``limit`` waiting findings, most promising first."""
    outcome = ReviewOutcome()
    min_score = float(cfg["report"]["min_score"])
    todo = store.findings_to_review(now, min_score, limit) if limit > 0 else []
    if todo:
        outcome.skipped = memory.shortage(cfg["llm"])
        if outcome.skipped is None:
            client = None
            try:
                client = reviewer()
                for finding in todo:
                    _review_one(client, store, cfg, finding, types_by_key, outcome, progress, clock)
            except LLMUnavailable as exc:
                outcome.skipped = str(exc)
            finally:
                if client is not None:
                    client.unload()
                    client.close()
    outcome.waiting = store.count_waiting(now, min_score)
    return outcome


@dataclass
class Assessment:
    accepted: bool
    score: float
    details: dict[str, Any]  # with "review", and the score recomputed from the final confidence


def assess(
    client: LLMClient, cfg: Config, finding: StoredFinding, api_type: ApiType, clock: Callable[[], float] = time.monotonic
) -> Assessment:
    """The model's verdict on one finding, combined with the code's. Raises LLMError."""
    d = dict(finding.details)
    classify, llm = cfg["classify"], cfg["llm"]
    min_confidence = float(classify["min_confidence"])
    code_confidence = float(d.get("code_confidence", (d.get("score") or {}).get("type_confidence", 0)))
    think = think_for(str(llm.get("think", "off")), code_confidence, min_confidence)
    started = clock()
    review = review_with_retry(client, context_for(finding, [api_type.label]), int(llm.get("readme_chars", 1500)), think)
    seconds = clock() - started
    verdict = api_type.llm_verdict(review, float(classify["llm_veto_confidence"]))
    final = apply_review(code_confidence, review, verdict=verdict, raise_cap=float(classify["llm_raise_cap"]))
    accepted = final >= min_confidence
    score_parts = d.get("score") or {}
    score = opportunity_score(
        float((d.get("gap") or {}).get("score", 0)),
        float(score_parts.get("health", 0)),
        final,
        d.get("issues") or [],
        (d.get("repo") or {}).get("language_match"),
        int(cfg["scoring"]["language_bonus"]),
    )
    d["score"], d["breakdown"] = score.as_dict(), score.breakdown()
    d["review"] = {
        "model": client.name,
        "project_type": review.project_type,
        "api_style": review.api_style,
        "confidence": review.confidence,
        "evidence": review.evidence,
        "why": review.why,
        "first_steps": review.first_steps,
        "verdict": verdict,
        "code_confidence": code_confidence,
        "final_confidence": final,
        "thinking": think,
        "seconds": round(seconds, 1),
    }
    return Assessment(accepted, score.total, d)


def _review_one(
    client: LLMClient,
    store: Store,
    cfg: Config,
    finding: StoredFinding,
    types_by_key: dict[str, ApiType],
    outcome: ReviewOutcome,
    progress: Callable[[str], None],
    clock: Callable[[], float],
) -> None:
    api_type = types_by_key.get(finding.details.get("api_type", ""))
    if api_type is None or finding.finding_id is None:  # its API type was switched off since
        return
    try:
        result = assess(client, cfg, finding, api_type, clock)
    except LLMUnavailable:
        raise
    except LLMError as exc:
        d = finding.details
        attempts = int(d.get("review_attempts", 0)) + 1
        d["review_attempts"] = attempts
        log.warning("the model couldn't review %s (attempt %d): %s", finding.full_name, attempts, exc)
        store.set_review(finding.finding_id, "error" if attempts >= MAX_ATTEMPTS else None, finding.score, d)
        return
    store.set_review(finding.finding_id, "accepted" if result.accepted else "rejected", result.score, result.details)
    r = result.details["review"]
    outcome.reviewed += 1
    outcome.seconds += r["seconds"]
    if result.accepted:
        outcome.accepted += 1
    else:
        outcome.rejected += 1
    verdict = "reported" if result.accepted else "not reported"
    progress(
        f"{model_label(client.name)}: {finding.full_name} is {r['project_type']}/{r['api_style']} "
        f"({r['code_confidence']:.2f} -> {r['final_confidence']:.2f}), {verdict} ({r['seconds']:.0f}s)"
    )
