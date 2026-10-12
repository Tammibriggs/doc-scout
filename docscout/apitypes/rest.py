"""REST/HTTP APIs, usually described by OpenAPI (Swagger) specs.

Detection and analysis are language- and framework-agnostic: they read OpenAPI files
(an open standard) and Markdown, never source code.

Docs analysis, in order of evidence:
- **spec**: the worst-documented OpenAPI/Swagger file the repo owns (see :mod:`openapi`);
- **prose**: endpoints documented in the README or API Markdown files (see :mod:`rest_prose`);
- **elsewhere**: no endpoints in the repo, but signs of docs on a website or in another repo;
- **none**: nothing at all, reported only when the repo is very likely an API (unverified).
Signs of docs elsewhere, or of a spec generated when the app runs, cap the gap and mark
the item "check manually".
"""

from __future__ import annotations

import logging
import re

from docscout.analyze.elsewhere import docs_elsewhere
from docscout.analyze.gaps import Gap
from docscout.analyze.tree import is_owned_path
from docscout.apitypes.base import ApiType, DocsContext
from docscout.apitypes.openapi import score_spec
from docscout.apitypes.rest_prose import COMPLETE, analyze_docs, find_endpoints, mentions_rest_api
from docscout.evidence import Evidence, Signals
from docscout.github import GitHubError

log = logging.getLogger(__name__)

__all__ = ["RestApi", "find_endpoints", "mentions_rest_api"]

_REST_DESCRIPTION = re.compile(r"\b(rest(ful)?\s+api|http\s+api|rest\s+server)\b", re.IGNORECASE)
_REST_ISSUE = re.compile(r"\b(openapi|swagger|endpoints?|rest(ful)?)\b", re.IGNORECASE)
_RUNTIME_SPEC = re.compile(r"swagger[ -]?ui|redoc|openapi\.json|/api-docs\b|/swagger\b|/docs\b", re.IGNORECASE)
_DOCS_FILE = re.compile(r"(api|endpoint|rest)[^/]*\.(md|mdx|markdown)$|(^|/)api/[^/]+\.(md|mdx|markdown)$", re.IGNORECASE)
MAX_DOCS_FILES = 3
MAX_DOCS_BYTES = 512 * 1024

GAP_ELSEWHERE = 40  # no endpoints in the repo, but docs probably exist elsewhere
GAP_NONE = 60  # nothing found anywhere; below a measured gap, since it rests on the weakest evidence
CAP_CHECK_MANUALLY = 50
CAP_COMPLETE_PROSE = 35
NONE_MIN_CONFIDENCE = 0.8


class RestApi(ApiType):
    key = "rest"
    label = "REST"
    llm_style = "rest"
    definition_pattern = re.compile(r"(openapi|swagger)[\w.-]*\.(ya?ml|json)$", re.IGNORECASE)

    def evidence(self, signals: Signals) -> Evidence:
        ev = Evidence()
        if _REST_DESCRIPTION.search(signals.text):
            ev.add(0.1, "describes a REST/HTTP API")
        if signals.tree is not None and self.find_definitions(signals.tree):
            ev.add(0.1, "owns an OpenAPI/Swagger spec")
        if signals.readme:
            endpoints = find_endpoints(signals.readme)
            if len(endpoints) >= 3:
                ev.add(0.15, f"README documents {len(endpoints)} endpoints")
            elif endpoints:
                ev.add(0.08, f"README mentions {len(endpoints)} endpoint(s)")
            if mentions_rest_api(signals.readme):
                ev.add(0.05, "README mentions a REST/HTTP API")
        if any(_REST_ISSUE.search(title) for title in signals.issue_titles):
            ev.add(0.1, "maintainers asked for REST API docs help")
        return ev

    # ------------------------------------------------------------------ docs analysis

    def analyze(self, ctx: DocsContext) -> Gap | None:
        spec = self._spec_gap(ctx)
        if spec is not None:
            return spec

        files = [("README", ctx.readme or ""), *self._docs_files(ctx)]
        prose = analyze_docs(files)
        check_manually = []
        if _RUNTIME_SPEC.search(ctx.readme or ""):
            check_manually.append("The README mentions Swagger UI, ReDoc or an OpenAPI URL, so a spec may be generated when the app runs")
        if not prose.endpoints or prose.completeness < COMPLETE:
            check_manually += docs_elsewhere(ctx.repo, ctx.readme, self._owner_repos(ctx), ctx.full_name)

        if prose.endpoints:
            completeness = prose.completeness
            if completeness >= COMPLETE:
                gap, suggestion = CAP_COMPLETE_PROSE, "The prose docs are fairly complete: turn them into an OpenAPI spec so tools and readers can use them."
            else:
                gap = max(CAP_COMPLETE_PROSE, round(100 * (1 - completeness)))
                suggestion = "Add what each endpoint is missing: a description, request and response examples, status codes and auth."
            if check_manually:
                gap = min(gap, CAP_CHECK_MANUALLY)
            return Gap(
                kind="prose",
                score=gap,
                findings=prose.findings(),
                effort_units=sum(1 for e in prose.endpoints if e.completeness < COMPLETE),
                location=None if prose.source == "README" else prose.source,
                summary=f"{len(prose.endpoints)} endpoints, {round(completeness * 100)}% complete, no OpenAPI spec",
                suggestion=suggestion,
                check_manually=check_manually,
            )
        if check_manually:
            return Gap(
                kind="elsewhere",
                score=GAP_ELSEWHERE,
                summary="No endpoints documented in the repo",
                suggestion="Check the docs below. If they're thin or missing, document the API in the repo, ideally as an OpenAPI spec.",
                check_manually=check_manually,
            )
        if ctx.type_confidence >= NONE_MIN_CONFIDENCE:
            return Gap(
                kind="none",
                score=GAP_NONE,
                summary="No spec, no endpoints in the README or docs, and no docs found elsewhere",
                suggestion="Confirm the project has an HTTP API (look for routes in the code), then document its main endpoints.",
                unverified=True,
            )
        return None

    def _spec_gap(self, ctx: DocsContext) -> Gap | None:
        best = None
        for spec_file in self.find_definitions(ctx.tree)[:3]:
            try:
                content = ctx.gh.get_file(ctx.full_name, spec_file.path, ref=ctx.head_sha)
            except GitHubError as exc:
                log.info("couldn't fetch %s in %s: %s", spec_file.path, ctx.full_name, exc)
                continue
            report = score_spec(content, spec_file.path) if content else None
            if report and (best is None or report.gap > best[1].gap):
                best = (spec_file.path, report)
        if best is None:
            return None
        path, report = best
        if report.generated:
            suggestion = "This spec is generated: improve the descriptions and examples in the code annotations it's generated from, not the file itself."
        else:
            suggestion = "Fill in the missing descriptions, examples and responses in the spec."
        return Gap(
            kind="spec",
            score=report.gap,
            findings=report.findings,
            effort_units=report.failing_operations,
            location=path,
            summary=f"{report.version}, {report.operations} operations, {'generated' if report.generated else 'hand-written'}",
            suggestion=suggestion,
            generated=report.generated,
        )

    def _docs_files(self, ctx: DocsContext) -> list[tuple[str, str]]:
        paths = sorted(
            (e["path"] for e in ctx.tree
             if e.get("type") == "blob" and _DOCS_FILE.search(e.get("path", "")) and is_owned_path(e["path"])
             and 0 < int(e.get("size") or 0) <= MAX_DOCS_BYTES),
            key=lambda p: (p.count("/"), p),
        )  # fmt: skip
        files = []
        for path in paths[:MAX_DOCS_FILES]:
            try:
                content = ctx.gh.get_file(ctx.full_name, path, ref=ctx.head_sha, max_bytes=MAX_DOCS_BYTES)
            except GitHubError:
                continue
            if content:
                files.append((path, content.decode("utf-8", "replace")))
        return files

    def _owner_repos(self, ctx: DocsContext) -> list[dict]:
        try:
            return ctx.gh.list_owner_repos(ctx.full_name.split("/")[0])
        except GitHubError:
            return []
