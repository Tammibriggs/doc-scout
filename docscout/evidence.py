"""Signals about a repo, and the generic "what role does this project play" evidence.

Everything here works on text and file names only, so it treats every language and
framework alike. API-type-specific evidence lives in :mod:`docscout.apitypes`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docscout.analyze.tree import has_container_setup

TOOL_WORDS = {
    "generator", "generators", "codegen", "validator", "validation", "linter", "lint", "mock", "mocking",
    "mocks", "testing", "tester", "fuzzer", "fuzzing", "parser", "converter", "plugin", "plugins",
    "framework", "mcp", "middleware", "toolkit", "boilerplate", "template", "starter", "scaffold",
    "extension", "specification", "schema", "schemas", "compiler",
}  # fmt: skip
LIB_WORDS = {"library", "lib", "sdk", "client", "bindings", "wrapper", "package", "module", "crate", "gem"}
APP_WORDS = {
    "server", "service", "selfhosted", "self-hosted", "platform", "app", "application", "tracker",
    "dashboard", "manager", "backend", "cms", "crm", "erp", "monitoring", "panel", "portal", "saas",
    "inventory", "bookmarks", "wiki", "helpdesk", "ticketing", "scheduler", "homelab",
}  # fmt: skip
APP_PHRASES = re.compile(r"\b(api\s+server|web\s+app(lication)?|self[- ]hosted)\b", re.I)


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9+-]*", text.lower())


@dataclass
class Signals:
    """Everything known about a repo at a given stage; later stages fill more fields."""

    meta: dict[str, Any]
    text: str  # repo name + description + topics
    tokens: set[str]
    prior: float = 0.0
    tree: list[dict[str, Any]] | None = None
    readme: str | None = None
    issue_titles: list[str] = field(default_factory=list)


def build_signals(
    meta: dict[str, Any],
    *,
    prior: float = 0.0,
    tree: list[dict[str, Any]] | None = None,
    readme: str | None = None,
    issues: list[dict[str, Any]] | None = None,
) -> Signals:
    name = str(meta.get("full_name") or meta.get("name") or "").split("/")[-1]
    description = str(meta.get("description") or "")
    topics = [str(t) for t in meta.get("topics") or []]
    text = " ".join([re.sub(r"[-_.]", " ", name), description, " ".join(topics)])
    tokens = set(words(text)) | {t.lower() for t in topics}
    titles = [str(i.get("title", "")) for i in issues or []]
    return Signals(meta=meta, text=text, tokens=tokens, prior=prior, tree=tree, readme=readme, issue_titles=titles)


@dataclass
class Evidence:
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)

    def add(self, amount: float, reason: str) -> None:
        self.score += amount
        self.reasons.append(reason)


@dataclass
class RoleHits:
    app: list[str]
    tool: list[str]
    lib: list[str]


def role_hits(signals: Signals) -> RoleHits:
    app = sorted(signals.tokens & APP_WORDS)
    if APP_PHRASES.search(signals.text):
        app.append("app phrase")
    return RoleHits(app=app, tool=sorted(signals.tokens & TOOL_WORDS), lib=sorted(signals.tokens & LIB_WORDS))


def service_role(signals: Signals) -> Evidence:
    """Evidence that the repo is a deployable app or service (not a tool or library)."""
    ev = Evidence()
    if signals.prior:
        ev.add(signals.prior, f"curated source (+{signals.prior:.2f})")
    hits = role_hits(signals)
    if hits.app:
        ev.add(0.1 * min(len(hits.app), 3), "app words: " + ", ".join(hits.app[:4]))
    if hits.tool:
        ev.add(-0.15 * min(len(hits.tool), 3), "tool words: " + ", ".join(hits.tool[:4]))
    if hits.lib:
        ev.add(-0.15 * min(len(hits.lib), 3), "library words: " + ", ".join(hits.lib[:4]))
    if signals.tree is not None and has_container_setup(signals.tree):
        ev.add(0.15, "Docker/compose setup (deployable service)")
    return ev
