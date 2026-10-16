"""The interface every API type implements.

An API type (REST, and later GraphQL, gRPC, AsyncAPI, ...) supplies only what is
specific to it: how to find it on GitHub, what its definition files look like, what
evidence shows a repo exposes it, and how to describe it to the LLM. Discovery, the
health gate, ranking, reports, scheduling and the LLM backends are shared.

Search settings (repo queries, definition filenames, issue keywords) come from the
type's ``[api_types.<key>]`` config section, so users can tune them without code.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from docscout.analyze.gaps import Gap
from docscout.analyze.tree import OwnedFile, find_owned_files
from docscout.find.evidence import Evidence, Signals, service_role
from docscout.llm.base import Review

if TYPE_CHECKING:
    from docscout.find.github import GitHub


@dataclass
class DocsContext:
    """What an API type gets when it analyzes a repo's docs (after the repo passed the gate)."""

    gh: GitHub
    full_name: str
    repo: dict[str, Any]
    tree: list[dict[str, Any]]
    readme: str | None
    head_sha: str | None  # latest commit on the default branch, for permanent links
    type_confidence: float


class ApiType:
    key: ClassVar[str]  # config key, e.g. "rest"
    label: ClassVar[str]  # shown in reports, e.g. "REST"
    llm_style: ClassVar[str]  # the Review.api_style value that means this type
    # Matches the file names of this type's definition files (OpenAPI specs, .graphql schemas, ...).
    definition_pattern: ClassVar[re.Pattern[str] | None] = None
    # How much the contributor's languages matter when [profile] language_filter = "auto":
    # "prefer" ranks their languages higher (most fixes are YAML or Markdown), "require" excludes
    # other languages (library/SDK docs are written as doc comments in the code itself).
    language_mode: ClassVar[str] = "prefer"

    def __init__(self, settings: dict[str, Any] | None = None) -> None:
        self.settings = settings or {}

    # ------------------------------------------------------------ discovery settings

    @property
    def repo_queries(self) -> list[str]:
        return list(self.settings.get("repo_queries", []))

    @property
    def definition_filenames(self) -> list[str]:
        return list(self.settings.get("definition_filenames", []))

    @property
    def issue_keywords(self) -> list[str]:
        return list(self.settings.get("issue_keywords", []))

    # ------------------------------------------------------------ analysis

    def find_definitions(self, tree: list[dict[str, Any]]) -> list[OwnedFile]:
        if self.definition_pattern is None:
            return []
        return find_owned_files(tree, self.definition_pattern)

    def role_evidence(self, signals: Signals) -> Evidence:
        """Evidence the repo plays the role this type targets. Most API types target
        deployable services; a type that targets libraries would override this."""
        return service_role(signals)

    def evidence(self, signals: Signals) -> Evidence:
        """Evidence the repo exposes this kind of API."""
        raise NotImplementedError

    def analyze(self, ctx: DocsContext) -> Gap | None:
        """How bad this repo's docs for this API are. None: not enough evidence to say."""
        raise NotImplementedError

    # ------------------------------------------------------------ LLM

    def llm_verdict(self, review: Review, veto_confidence: float = 0.7) -> str:
        """'agree', 'neutral' or 'disagree' with the code's "this repo serves this API type".

        Measured on the 58 labeled repos (14 Oct): the small local model often calls an app
        that serves an API "serves_api" with style "none", or names only one of several
        styles (flipt: gRPC with a REST gateway). Counting those as disagreement dropped
        12 real API apps, so they're neutral. Only a clear verdict that it isn't an app
        with an API (a tool, library, spam or something else) lowers confidence.
        """
        if review.project_type == "serves_api":
            return "agree" if review.api_style == self.llm_style else "neutral"
        return "disagree" if review.confidence >= veto_confidence else "neutral"

    def llm_agrees(self, review: Review) -> bool:
        return self.llm_verdict(review) == "agree"
