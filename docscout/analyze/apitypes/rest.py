"""REST/HTTP APIs, usually described by OpenAPI (Swagger) specs.

Detection and analysis are language- and framework-agnostic: they read OpenAPI files
(an open standard) and Markdown, never source code.

Docs analysis, in order of evidence:
- **spec**: the worst-documented OpenAPI/Swagger file the repo owns (see :mod:`openapi`);
- **prose**: endpoints documented in the README or API Markdown files (see :mod:`rest_prose`);
- **elsewhere**: no endpoints in the repo, but signs of docs on a website or in another repo.
Finding nothing at all isn't reported: it rests only on not finding docs, and the one such
pick in the comparison (16 Oct) had its API docs in a GitHub wiki. Signs of docs elsewhere, or of a spec generated when the app runs, cap the gap and mark
the item "check manually". Docs published as pages (a docs site, a docs repo, Markdown on
GitHub) are listed with any gap, because they raise the project's score.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

from docscout.analyze.elsewhere import docs_elsewhere, published_docs
from docscout.analyze.gaps import Gap
from docscout.analyze.tree import OwnedFile, find_owned_files, is_owned_path
from docscout.analyze.apitypes.base import ApiType, DocsContext
from docscout.analyze.apitypes.openapi import score_spec
from docscout.analyze.apitypes.rest_prose import COMPLETE, analyze_docs, find_endpoints, mentions_rest_api
from docscout.find.evidence import Evidence, Signals
from docscout.find.github import GitHubError

log = logging.getLogger(__name__)

__all__ = ["RestApi", "find_endpoints", "mentions_rest_api"]

_REST_DESCRIPTION = re.compile(r"\b(rest(ful)?\s+api|http\s+api|rest\s+server)\b", re.IGNORECASE)
_REST_ISSUE = re.compile(r"\b(openapi|swagger|endpoints?|rest(ful)?)\b", re.IGNORECASE)
# "/docs" counts only on a local address or port (localhost:8000/docs), where frameworks serve
# generated API docs; on a website (laravel.com/docs) it's just a docs page.
_RUNTIME_SPEC = re.compile(
    r"swagger[ -]?ui|redoc|openapi\.json|/api-docs\b|/swagger\b|(localhost|127\.0\.0\.1|0\.0\.0\.0|:\d{2,5})/docs\b",
    re.IGNORECASE,
)
_DOCS_FILE = re.compile(r"(api|endpoint|rest)[^/]*\.(md|mdx|markdown)$|(^|/)api/[^/]+\.(md|mdx|markdown)$", re.IGNORECASE)
# Notes for the project's own developers (decision records, audits, proposals), not API docs for users.
_INTERNAL_DOCS = re.compile(r"(^|[/_-])(adrs?|rfcs?|decisions?|proposals?|design|audits?|internal|meetings?|changelogs?|archive)([/_-]|$)", re.IGNORECASE)
# Hidden folders hold tool settings and instructions for AI coding agents (.agents/, .claude/,
# .cursor/), not docs for users. Seen 15 Oct: ChurchCRM's .agents/skills/churchcrm/api-development.md.
_HIDDEN_DIR = re.compile(r"(^|/)\.[^/]+/")
# Specs whose file name doesn't say so. Seen 15 Oct: dagu's api/v1/api.yaml, jupyter_server's
# services/api/api.yaml, traceroot's backend/rest/openapi/public.json and ChurchCRM's
# docs/openapi/generated/public-api.yaml. score_spec skips the files that turn out not to be specs.
_SPEC_FOLDER = re.compile(r"(^|/)(openapi|swagger)[\w.-]*(/|$)", re.IGNORECASE)
_YAML_OR_JSON = re.compile(r"\.(ya?ml|json)$", re.IGNORECASE)
_API_NAMED = re.compile(r"^([\w.-]*[-_.])?api([-_.][\w.-]*)?\.(ya?ml|json)$", re.IGNORECASE)
_NOT_A_SPEC = re.compile(r"^(package(-lock)?|composer|tsconfig[\w.-]*|\.?redocly[\w.-]*|\.?spectral[\w.-]*)\.(json|ya?ml)$", re.IGNORECASE)
MAX_SPEC_FILES = 4
MAX_DOCS_FILES = 3
MAX_DOCS_BYTES = 512 * 1024

# Generators that put their "do not edit" marker in a file beside the spec, not in it: swag
# writes docs.go next to swagger.json and swagger.yaml (seen 16 Oct: autentico's docs/).
_GENERATOR_FILES_BESIDE = ("docs.go",)

GAP_ELSEWHERE = 40  # no endpoints in the repo, but docs probably exist elsewhere
CAP_CHECK_MANUALLY = 50
CAP_COMPLETE_PROSE = 35


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

    def spec_files(self, tree: list[dict]) -> list[OwnedFile]:
        """Files that may be this repo's spec, most likely first: named openapi or swagger, then
        any YAML or JSON in an openapi or swagger folder, then files named like api.yaml."""
        named = self.find_definitions(tree)
        seen = {f.path for f in named}
        in_folder, api_named = [], []
        for f in find_owned_files(tree, _YAML_OR_JSON):
            folder, _, name = f.path.rpartition("/")
            if f.path in seen or _NOT_A_SPEC.search(name):
                continue
            if _SPEC_FOLDER.search(folder):
                in_folder.append(f)
            elif _API_NAMED.search(name):
                api_named.append(f)
        return named + in_folder + api_named

    def analyze(self, ctx: DocsContext) -> Gap | None:
        owner_repos: list[dict] | None = None

        def owners() -> list[dict]:  # at most one API call per repo, and only when needed
            nonlocal owner_repos
            if owner_repos is None:
                owner_repos = self._owner_repos(ctx)
            return owner_repos

        gap = self._spec_gap(ctx) or self._docs_gap(ctx, owners)
        if gap is not None:
            gap.published = published_docs(ctx.repo, ctx.readme, ctx.tree, owners(), ctx.full_name)
            if gap.kind == "prose":
                where = "the README" if gap.location is None else gap.location
                gap.published.insert(0, f"API docs in Markdown on GitHub ({where})")
        return gap

    def _docs_gap(self, ctx: DocsContext, owners: Callable[[], list[dict]]) -> Gap | None:
        files = [("README", ctx.readme or ""), *self._docs_files(ctx)]
        prose = analyze_docs(files)
        check_manually = []
        if _RUNTIME_SPEC.search(ctx.readme or ""):
            check_manually.append("The README mentions Swagger UI, ReDoc or an OpenAPI URL, so a spec may be generated when the app runs")
        if not prose.endpoints or prose.completeness < COMPLETE:
            check_manually += docs_elsewhere(ctx.repo, ctx.readme, owners(), ctx.full_name)

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
                summary=f"{len(prose.endpoints)} endpoint{'s' if len(prose.endpoints) != 1 else ''}, {round(completeness * 100)}% complete, no OpenAPI spec",
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
        return None

    def _spec_gap(self, ctx: DocsContext) -> Gap | None:
        best = None
        for spec_file in self.spec_files(ctx.tree)[:MAX_SPEC_FILES]:
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
        folder = path.rpartition("/")[0]
        beside = {f"{folder}/{name}" if folder else name for name in _GENERATOR_FILES_BESIDE}
        generated = report.generated or any(e.get("path") in beside for e in ctx.tree)
        if generated:
            suggestion = "This spec is generated: improve the descriptions and examples in the code annotations it's generated from, not the file itself."
        else:
            suggestion = "Fill in the missing descriptions, examples and responses in the spec."
        return Gap(
            kind="spec",
            score=report.gap,
            findings=report.findings,
            effort_units=report.failing_operations,
            location=path,
            summary=f"{report.version}, {report.operations} operations, {'generated' if generated else 'hand-written'}",
            suggestion=suggestion,
            generated=generated,
        )

    def _docs_files(self, ctx: DocsContext) -> list[tuple[str, str]]:
        paths = sorted(
            (e["path"] for e in ctx.tree
             if e.get("type") == "blob" and _DOCS_FILE.search(e.get("path", "")) and is_owned_path(e["path"])
             and not _INTERNAL_DOCS.search(e["path"].rpartition("/")[0]) and not _HIDDEN_DIR.search(e["path"])
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
