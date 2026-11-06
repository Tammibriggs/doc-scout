"""What an API type's docs analysis returns: how bad the docs are, and why."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# kind -> heading shown in reports; {api} is the API type's label, e.g. "REST"
KIND_LABELS = {
    "spec": "{api} API spec with gaps",
    "prose": "{api} API docs only in prose",
    "elsewhere": "{api} API docs probably elsewhere",
    "none": "No {api} API docs found",
}


def kind_label(kind: str, api_label: str) -> str:
    return KIND_LABELS.get(kind, kind).format(api=api_label).strip()


@dataclass
class Finding:
    text: str  # plain text; the report escapes it
    examples: list[str] = field(default_factory=list)  # e.g. endpoints, shown as code
    more: int = 0  # how many further examples exist
    # The gap's stable key (M6): what a claim or a measured PR is matched on. Specs: description,
    # parameters, fields, request_example, response_example, success_schema, errors, overview,
    # security, tags, servers. Prose: description, request_example, response_example,
    # status_codes, auth. Empty for findings stored before 6 Nov.
    check: str = ""


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
    published: list[str] = field(default_factory=list)  # where the docs are published as pages

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
            "published": self.published,
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


def counted(text: str, failing: list[str], total: int, noun: str = "operations", limit: int = 2, check: str = "") -> Finding:
    """'21/38 operations have no description' with up to ``limit`` examples."""
    return Finding(f"{len(failing)}/{total} {noun} {text}", failing[:limit], max(0, len(failing) - limit), check)


# Findings stored before 6 Nov have no key; their text says which gap they are. The more
# specific phrases come first ("fields have no description" before prose "have no description").
_LEGACY_KEYS = (
    ("have no summary or description", "description"),
    ("have parameters without descriptions", "parameters"),
    ("have no request or response examples", "response_example"),  # one line for both kinds until 6 Nov
    ("have no request example", "request_example"),
    ("have no example of a successful response", "response_example"),
    ("have no response example", "response_example"),
    ("have no schema for a successful response", "success_schema"),
    ("document no error responses", "errors"),
    ("describe their error responses", "errors"),
    ("fields have no description", "fields"),
    ("API overview", "overview"),
    ("authentication schemes", "security"),
    ("operation groups (tags)", "tags"),
    ("No server address", "servers"),
    ("list no status or error codes", "status_codes"),
    ("say how to authenticate", "auth"),
    ("have no description", "description"),
)


def finding_key(finding: dict[str, Any]) -> str:
    """A stored finding's gap key: its own, or the one its text names."""
    if finding.get("check"):
        return str(finding["check"])
    text = str(finding.get("text", ""))
    return next((key for phrase, key in _LEGACY_KEYS if phrase in text), "")
