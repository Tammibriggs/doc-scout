"""Measure classifier accuracy against a hand-labeled sample CSV (stage M0)."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from docscout.discover import LABELS

TARGET_PRECISION = 0.70
SOURCE_MIN_PRECISION = 0.50


@dataclass
class Score:
    labeled: int = 0
    predicted_api: int = 0
    true_api: int = 0  # labeled serves_api
    correct_api: int = 0  # predicted and labeled serves_api

    @property
    def precision(self) -> float | None:
        return self.correct_api / self.predicted_api if self.predicted_api else None

    @property
    def recall(self) -> float | None:
        return self.correct_api / self.true_api if self.true_api else None


@dataclass
class Report:
    overall: Score
    by_source: dict[str, Score]
    confusion: Counter[tuple[str, str]]  # (label, predicted) -> count
    by_threshold: dict[float, Score]
    invalid_labels: list[str]


def _add(score: Score, label: str, predicted_api: bool) -> None:
    score.labeled += 1
    score.predicted_api += predicted_api
    score.true_api += label == "serves_api"
    score.correct_api += predicted_api and label == "serves_api"


def evaluate_csv(path: Path, thresholds: tuple[float, ...] = (0.5, 0.6, 0.7)) -> Report:
    overall = Score()
    by_source: dict[str, Score] = defaultdict(Score)
    by_threshold = {t: Score() for t in thresholds}
    confusion: Counter[tuple[str, str]] = Counter()
    invalid: list[str] = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            label = (row.get("label") or "").strip().lower()
            if not label:
                continue
            if label not in LABELS:
                invalid.append(f"{row.get('full_name')}: {label!r}")
                continue
            predicted = row.get("predicted_type", "")
            is_api = predicted == "serves_api"
            _add(overall, label, is_api)
            _add(by_source[row.get("source", "?")], label, is_api)
            confusion[(label, predicted)] += 1
            conf = float(row.get("api_confidence") or 0)
            for t, score in by_threshold.items():
                _add(score, label, conf >= t)
    return Report(overall, dict(by_source), confusion, by_threshold, invalid)


def _pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.0%}"


def format_report(report: Report) -> str:
    lines = []
    o = report.overall
    if not o.labeled:
        return "No labeled rows found. Fill the 'label' column with: " + ", ".join(LABELS)
    lines.append(f"Labeled rows: {o.labeled}   (predicted 'serves_api': {o.predicted_api}, labeled 'serves_api': {o.true_api})")
    lines.append("")
    lines.append(f"{'source':<20} {'labeled':>7} {'precision':>9} {'recall':>7}")
    for name, s in sorted(report.by_source.items()):
        flag = ""
        if s.precision is not None and s.precision < SOURCE_MIN_PRECISION:
            flag = "  <- below 50%: consider removing from [discovery] sources"
        lines.append(f"{name:<20} {s.labeled:>7} {_pct(s.precision):>9} {_pct(s.recall):>7}{flag}")
    lines.append(f"{'OVERALL':<20} {o.labeled:>7} {_pct(o.precision):>9} {_pct(o.recall):>7}")
    lines.append("")
    lines.append("Precision if only repos at or above a confidence threshold were reported:")
    for t, s in sorted(report.by_threshold.items()):
        lines.append(f"  >= {t:.1f}: precision {_pct(s.precision)}, recall {_pct(s.recall)}, reported {s.predicted_api}")
    lines.append("")
    lines.append("Confusion (label -> predicted):")
    for (label, predicted), n in sorted(report.confusion.items(), key=lambda kv: -kv[1]):
        lines.append(f"  {label:<12} -> {predicted:<12} {n}")
    if report.invalid_labels:
        lines.append("")
        lines.append("Ignored rows with unknown labels: " + "; ".join(report.invalid_labels))
    lines.append("")
    if o.precision is not None and o.precision >= TARGET_PRECISION:
        lines.append(f"PASS: precision {o.precision:.0%} meets the {TARGET_PRECISION:.0%} target for stage M0.")
    else:
        lines.append(f"NOT YET: precision {_pct(o.precision).strip()} is below the {TARGET_PRECISION:.0%} target. Tune classify.py or drop weak sources.")
    return "\n".join(lines)
