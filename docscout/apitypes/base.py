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
from typing import Any, ClassVar

from docscout.analyze.tree import OwnedFile, find_owned_files
from docscout.evidence import Evidence, Signals, service_role
from docscout.llm.base import Review


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

    # ------------------------------------------------------------ LLM

    def llm_agrees(self, review: Review) -> bool:
        return review.project_type == "serves_api" and review.api_style == self.llm_style
