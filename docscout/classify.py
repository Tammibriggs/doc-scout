"""Project classifier: does this repo expose an API of an enabled type?

It uses only text and file names, so it treats every language and framework alike.
Stage 1 uses search metadata (free); stage 2 adds the file tree and README (costs API
calls, so it only runs on repos that pass the health gate). Issues where maintainers
ask for help count as evidence at both stages.

Each enabled API type scores the repo as role evidence (is it a service?) plus its own
evidence (does it expose this kind of API?). ``api_confidence`` is the best of those.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from docscout.apitypes import ApiType
from docscout.evidence import build_signals, role_hits
from docscout.health import parse_time

NEUTRAL = 0.4
# Confidence from which a repo counts as serving an API. On the 58 labeled repos (13 Oct), 0.6
# gave 76% precision and 90% recall, against 69% and 94% at 0.5. Repos between the LLM band's
# floor and this value need the LLM's confirmation to be reported (stage M2).
MIN_CONFIDENCE = 0.6
PROMO_WORDS = {"free", "fee", "fees", "best", "guide", "ultimate", "cheap", "unlimited", "premium", "earn", "giveaway"}
YEAR = re.compile(r"\b20[2-3]\d\b")


@dataclass
class Classification:
    project_type: str  # serves_api | api_tooling | library | spam | other
    api_confidence: float  # best confidence across enabled API types
    reasons: list[str] = field(default_factory=list)
    api_type: str | None = None  # key of the best-matching API type
    per_type: dict[str, float] = field(default_factory=dict)


def is_spam(meta: dict[str, Any], now: datetime) -> str | None:
    """Only new repos are judged: established projects often use many topics (GitHub allows 20)."""
    created = parse_time(meta.get("created_at"))
    if created is None or now - created > timedelta(days=60):
        return None
    topics = meta.get("topics") or []
    if len(topics) > 15:
        return f"new repo with {len(topics)} topics (keyword stuffing)"
    signals = build_signals(meta)
    hits = len(signals.tokens & PROMO_WORDS) + (1 if YEAR.search(signals.text) else 0) + (1 if "0%" in signals.text else 0)
    if hits >= 2:
        return "new repo with promotional wording"
    return None


def classify(
    meta: dict[str, Any],
    *,
    now: datetime,
    api_types: list[ApiType],
    prior: float = 0.0,
    tree: list[dict[str, Any]] | None = None,
    readme: str | None = None,
    issues: list[dict[str, Any]] | None = None,
    min_confidence: float = MIN_CONFIDENCE,
) -> Classification:
    spam = is_spam(meta, now)
    if spam:
        return Classification("spam", 0.05, [spam])

    signals = build_signals(meta, prior=prior, tree=tree, readme=readme, issues=issues)
    best: tuple[float, ApiType, list[str]] | None = None
    per_type: dict[str, float] = {}
    for api_type in api_types:
        role = api_type.role_evidence(signals)
        own = api_type.evidence(signals)
        confidence = round(min(1.0, max(0.0, NEUTRAL + role.score + own.score)), 3)
        per_type[api_type.key] = confidence
        if best is None or confidence > best[0]:
            best = (confidence, api_type, role.reasons + own.reasons)
    assert best is not None, "at least one API type must be enabled"
    confidence, api_type, reasons = best

    if confidence >= min_confidence:
        project_type = "serves_api"
    else:
        hits = role_hits(signals)
        if hits.tool and len(hits.tool) >= len(hits.lib):
            project_type = "api_tooling"
        elif hits.lib:
            project_type = "library"
        else:
            project_type = "other"
    return Classification(project_type, confidence, reasons, api_type.key, per_type)
