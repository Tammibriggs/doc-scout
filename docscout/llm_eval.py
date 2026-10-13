"""``docscout eval labels.csv --llm``: measure the model's review against hand-labeled repos.

Reports precision and recall with and without the model, seconds per review, and the
memory the model needed (which sets ``[llm] min_free_memory_gb``). It uses the repo data
``--reclassify`` cached, so it makes no GitHub calls. Reviews are cached by repo, model
and thinking, so a rerun (e.g. with ``--think borderline``) only reviews what's new.

Unlike a daily run, the model doesn't see the docs gaps here (the labeled sample has
no gap analysis), only the README, description, topics and issue titles.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docscout.apitypes import ApiType
from docscout.config import Config
from docscout.evaluate import Report, evaluate_rows
from docscout.llm import LLMClient, LLMError, LLMUnavailable, RepoContext, Review, apply_review, memory
from docscout.llm.base import review_with_retry
from docscout.review import model_label, think_for

CACHE_VERSION = 1


@dataclass
class Change:
    full_name: str
    label: str
    before: str
    after: str
    code_confidence: float
    final_confidence: float
    evidence: str


@dataclass
class LLMEval:
    model: str
    think: str
    rows: list[dict[str, Any]]
    reviewed: int = 0  # repos with a review (fresh or cached)
    seconds: list[float] = field(default_factory=list)  # fresh reviews only
    thinking_seconds: list[float] = field(default_factory=list)
    changes: list[Change] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    stopped: str | None = None  # the model became unavailable
    free_before: int | None = None
    lowest_free: int | None = None


def load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("reviews", {}) if data.get("version") == CACHE_VERSION else {}


def save_cache(path: Path, reviews: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CACHE_VERSION, "reviews": reviews}), encoding="utf-8")


def _context(name: str, inputs: dict[str, Any], readme_chars: int, wanted: str) -> RepoContext:
    meta = inputs.get("meta") or {}
    return RepoContext(
        full_name=name,
        description=meta.get("description") or "",
        topics=list(meta.get("topics") or []),
        language=meta.get("language"),
        readme_excerpt=(inputs.get("readme") or "")[:readme_chars],
        issues=[i.get("title", "") for i in inputs.get("issues") or []],
        wanted_api_types=[wanted],
    )


def run(
    rows: list[dict[str, Any]],
    inputs: dict[str, Any],
    client: LLMClient,
    cfg: Config,
    api_type: ApiType,
    *,
    think: str,
    cache_path: Path,
    progress: Callable[[str], None] = lambda message: None,
    clock: Callable[[], float] = time.monotonic,
) -> LLMEval:
    """``rows`` carry the current code prediction (from reclassify); ``inputs`` its cached repo data."""
    classify, llm = cfg["classify"], cfg["llm"]
    floor, min_confidence, cap = float(classify["drop_below"]), float(classify["min_confidence"]), float(classify["llm_raise_cap"])
    readme_chars = int(llm.get("readme_chars", 1500))
    rows = [dict(r) for r in rows]  # the code-only rows stay as they were, for the comparison
    cache = load_cache(cache_path)
    result = LLMEval(model=client.name, think=think, rows=[])
    todo = [r for r in rows if (r.get("label") or "").strip() and float(r.get("api_confidence") or 0) >= floor]
    with memory.Watch() as watch:
        try:
            for i, row in enumerate(todo, 1):
                name = (row.get("full_name") or "").strip()
                data = inputs.get(name.lower())
                if data is None:
                    result.errors.append(f"{name}: no cached data (run with --reclassify first)")
                    continue
                code_confidence = float(row["api_confidence"])
                thinking = think_for(think, code_confidence, min_confidence)
                key = f"{name.lower()}|{client.name}|think={thinking}"
                if key not in cache:
                    started = clock()
                    try:
                        review = review_with_retry(client, _context(name, data, readme_chars, api_type.label), readme_chars, thinking)
                    except LLMUnavailable:
                        raise
                    except LLMError as exc:
                        result.errors.append(f"{name}: {exc}")
                        continue
                    seconds = clock() - started
                    (result.thinking_seconds if thinking else result.seconds).append(seconds)
                    cache[key] = review.model_dump()
                    save_cache(cache_path, cache)
                review = Review.model_validate(cache[key])
                result.reviewed += 1
                agrees = api_type.llm_agrees(review)
                final = apply_review(code_confidence, review, agrees=agrees, raise_cap=cap)
                after = "serves_api" if final >= min_confidence else (review.project_type if review.project_type != "serves_api" else "other")
                before = row.get("predicted_type", "")
                row.update(predicted_type=after, api_confidence=final)
                if (before == "serves_api") != (after == "serves_api"):
                    result.changes.append(Change(name, row["label"].strip().lower(), before, after, code_confidence, final, review.evidence))
                progress(f"  {i}/{len(todo)} {name}: {review.project_type}/{review.api_style} ({code_confidence:.2f} -> {final:.2f})")
        except LLMUnavailable as exc:
            result.stopped = str(exc)
        finally:
            client.unload()
    result.free_before, result.lowest_free = watch.before, watch.lowest
    result.rows = rows
    return result


def suggested_free_memory_gb(result: LLMEval) -> float | None:
    """What the model needed (free memory before minus the lowest during), plus 1 GB to spare."""
    if result.free_before is None or result.lowest_free is None or not (result.seconds or result.thinking_seconds):
        return None
    needed = max(0, result.free_before - result.lowest_free) / 1e9
    return math.ceil((needed + 1.0) * 2) / 2  # rounded up to half a gigabyte


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.0%}"


def format_result(result: LLMEval, before: Report, after: Report) -> str:
    label = model_label(result.model)
    lines = [f"{label} ({result.model}), thinking: {result.think}"]
    timing = []
    if result.seconds:
        timing.append(f"{sum(result.seconds) / len(result.seconds):.1f} s per review")
    if result.thinking_seconds:
        timing.append(f"{sum(result.thinking_seconds) / len(result.thinking_seconds):.1f} s with thinking")
    lines.append(f"Reviewed {result.reviewed} labeled repos (those with code confidence of at least 0.40)" + (f", {', '.join(timing)}." if timing else " (all from the cache)."))
    lines += ["", f"{'':<22} {'precision':>9} {'recall':>7} {'reported':>9}"]
    for name, report in (("Code only", before), (f"With {label}", after)):
        o = report.overall
        lines.append(f"{name:<22} {_pct(o.precision):>9} {_pct(o.recall):>7} {o.predicted_api:>9}")
    if result.changes:
        lines += ["", f"What {label} changed ({len(result.changes)}):"]
        for c in result.changes:
            verdict = "now right" if (c.after == "serves_api") == (c.label == "serves_api") else "now wrong"
            reported = "reported" if c.after == "serves_api" else "not reported"
            lines.append(f"  {c.full_name:<40} label {c.label:<12} {c.code_confidence:.2f} -> {c.final_confidence:.2f}, {reported:<12} {verdict}  \"{c.evidence[:60]}\"")
    if result.free_before is not None and result.lowest_free is not None and (result.seconds or result.thinking_seconds):
        gb = 1e9
        lines += ["", f"Memory: {result.free_before / gb:.1f} GB free before, lowest {result.lowest_free / gb:.1f} GB during the reviews."]
        suggestion = suggested_free_memory_gb(result)
        if suggestion is not None:
            lines.append(f"Suggested [llm] min_free_memory_gb = {suggestion:g} (what the model needed, plus 1 GB to spare)")
    for error in result.errors:
        lines.append(f"  couldn't review {error}")
    if result.stopped:
        lines += ["", f"Stopped early: {result.stopped}"]
    return "\n".join(lines)


def compare(code_rows: list[dict[str, Any]], result: LLMEval) -> tuple[Report, Report]:
    return evaluate_rows(code_rows), evaluate_rows(result.rows)
