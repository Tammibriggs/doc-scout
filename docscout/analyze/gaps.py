"""What an API type's docs analysis returns: how bad the docs are, and why."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# kind -> heading shown in reports
KIND_LABELS = {
    "spec": "Spec with gaps",
    "prose": "Docs only in prose",
    "elsewhere": "Docs probably elsewhere",
    "none": "No API docs found",
}


@dataclass
class Finding:
    text: str  # plain text; the report escapes it
    examples: list[str] = field(default_factory=list)  # e.g. endpoints, shown as code
    more: int = 0  # how many further examples exist


@dataclass
class Gap:
    kind: str  # spec | prose | elsewhere | none
    score: float  # 0-100, higher = worse docs
    findings: list[Finding] = field(default_factory=list)
    effort_units: int | None = None  # operations or endpoints needing work; None = unknown
    location: str | None = None  # path of the spec or docs file, if any
    summary: str = ""  # e.g. "OpenAPI 3.1, 38 operations, hand-written"
    suggestion: str = ""
    generated: bool = False  # the file is generated: edit its source, not the file
    check_manually: list[str] = field(default_factory=list)  # signs docs may exist elsewhere
    unverified: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "score": self.score,
            "findings": [vars(f) for f in self.findings],
            "effort_units": self.effort_units,
            "location": self.location,
            "summary": self.summary,
            "suggestion": self.suggestion,
            "generated": self.generated,
            "check_manually": self.check_manually,
            "unverified": self.unverified,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Gap:
        data = dict(data)
        data["findings"] = [Finding(**f) for f in data.get("findings", [])]
        return cls(**data)


def effort_label(units: int | None) -> str:
    if units is None:
        return "unknown"
    if units <= 10:
        return "S"
    if units <= 40:
        return "M"
    return "L"


def counted(text: str, failing: list[str], total: int, noun: str = "operations", limit: int = 2) -> Finding:
    """'21/38 operations have no description' with up to ``limit`` examples."""
    return Finding(f"{len(failing)}/{total} {noun} {text}", failing[:limit], max(0, len(failing) - limit))
