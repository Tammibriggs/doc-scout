"""Before you contribute: is it already claimed, and are there extra steps?

These never hide a repo or change its score; they warn about things that otherwise
surprise contributors after the work is done. Each requirement quotes the sentence it
matched, so you can judge it yourself. Everything is plain-text matching, so it works
for any language.

Free checks (from data already fetched) run during analysis; the ones that cost API
calls (open PRs, issue comments, CONTRIBUTING and the PR template) run only for items
that make it into the report.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from docscout.analyze.tree import has_path
from docscout.github import GitHub, GitHubError

_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]|\n|$)")
REQUIREMENTS = {
    "CLA required": re.compile(r"contributor licen[cs]e agreement|\bCLA\b|cla[- ]assistant", re.IGNORECASE),
    "Commits need sign-off (DCO)": re.compile(r"signed-off-by|\bDCO\b|developer certificate of origin", re.IGNORECASE),
}
_AI_TERMS = re.compile(
    r"\b(AI[- ]generated|generated (?:by|with|using) AI|AI[- ]assisted|AI tools?|LLMs?|large language models?|ChatGPT|Copilot|Claude|Gemini)\b",
    re.IGNORECASE,
)
_AI_POLICY_WORDS = re.compile(r"\b(contribut\w*|pull requests?|PRs?|accept\w*|prohibit\w*|disclos\w*|ban\w*|not allowed|reject\w*)\b", re.IGNORECASE)
_DOCS_WORK = re.compile(r"\b(docs?|documentation|openapi|swagger|api[- ]docs|readme)\b", re.IGNORECASE)
# Dependency updates that touch docs tooling ("bump mkdocs-material in /docs") aren't someone writing docs.
_DEPENDENCY_UPDATE = re.compile(r"\b(bump|bumps|deps?|dependenc(y|ies)|dependabot|renovate)\b|\(deps\)", re.IGNORECASE)
_CLAIM = re.compile(
    r"\b(i'?ll take|i will take|i'?d like to (?:work|take)|i am working on|i'?m working on|working on (?:this|it)|"
    r"assign (?:this|it)? ?to me|assign me|can i (?:take|work on))\b",
    re.IGNORECASE,
)
_SETUP_HEADINGS = re.compile(r"^#{1,6}[ \t]+.*\b(development|developing|running locally|run locally|getting started|install\w*|build\w* from source|setup)\b", re.IGNORECASE | re.MULTILINE)
CONTRIBUTING = re.compile(r"^(\.github/|docs/)?contributing(\.\w+)?$", re.IGNORECASE)
PR_TEMPLATE = re.compile(r"^(\.github/|docs/)?(pull_request_template\.md|PULL_REQUEST_TEMPLATE\.md)$", re.IGNORECASE)


@dataclass
class Checks:
    claimed: list[str] = field(default_factory=list)  # signs someone is already on it
    requirements: list[str] = field(default_factory=list)  # 'CLA required ("…" in CONTRIBUTING.md)'
    local_setup: str = "unclear"  # easy (…) | documented | unclear
    claim_checked: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _quote(text: str, match: re.Match[str], limit: int = 140) -> str:
    for sentence in _SENTENCE.finditer(text):
        if sentence.start() <= match.start() < sentence.end():
            words = " ".join(sentence.group(0).split())
            return words if len(words) <= limit else words[: limit - 1] + "…"
    return match.group(0)


def find_requirements(text: str, source: str) -> list[str]:
    found = []
    for label, pattern in REQUIREMENTS.items():
        match = pattern.search(text)
        if match:
            found.append(f'{label} ("{_quote(text, match)}" in {source})')
    for match in _AI_TERMS.finditer(text):
        sentence = _quote(text, match, limit=400)
        if _AI_POLICY_WORDS.search(sentence):
            found.append(f'AI-contribution policy ("{_quote(text, match)}" in {source})')
            break
    return found


def local_setup(tree: list[dict[str, Any]], readme: str | None) -> str:
    if has_path(tree, r"^(docker-compose[\w.-]*\.ya?ml|compose\.ya?ml)$"):
        return "easy (docker-compose)"
    if has_path(tree, r"^\.devcontainer/"):
        return "easy (devcontainer)"
    if has_path(tree, r"^dockerfile$"):
        return "easy (Dockerfile)"
    if readme and _SETUP_HEADINGS.search(readme):
        return "documented"
    return "unclear"


def free_checks(tree: list[dict[str, Any]], readme: str | None) -> tuple[Checks, dict[str, str]]:
    """Checks from data already fetched, plus the paths the paid checks will read."""
    checks = Checks(local_setup=local_setup(tree, readme), requirements=find_requirements(readme or "", "README"))
    if has_path(tree, r"^\.clabot$"):
        checks.requirements.append("CLA required (.clabot file)")
    paths = {}
    for entry in tree:
        path = entry.get("path", "")
        if entry.get("type") == "blob" and CONTRIBUTING.match(path) and "contributing" not in paths:
            paths["contributing"] = path
        elif entry.get("type") == "blob" and PR_TEMPLATE.match(path) and "pr_template" not in paths:
            paths["pr_template"] = path
    return checks, paths


def paid_checks(gh: GitHub, full_name: str, checks: Checks, paths: dict[str, str], issues: list[dict[str, Any]], head_sha: str | None) -> Checks:
    """Open docs PRs, claims in issue comments, and requirements in CONTRIBUTING and the PR template."""
    try:
        for pr in gh.list_open_pulls(full_name):
            user = pr.get("user") or {}
            if user.get("type") == "Bot" or str(user.get("login", "")).endswith("[bot]"):
                continue
            title_and_branch = f"{pr.get('title', '')} {(pr.get('head') or {}).get('ref', '')}"
            if _DOCS_WORK.search(title_and_branch) and not _DEPENDENCY_UPDATE.search(title_and_branch):
                checks.claimed.append(f"Open PR #{pr.get('number')}: {pr.get('title', '')}")
        for issue in issues[:2]:
            for comment in gh.list_issue_comments(full_name, int(issue["number"])):
                if _CLAIM.search(str(comment.get("body") or "")):
                    checks.claimed.append(f"Someone offered to work on #{issue['number']}")
                    break
        checks.claim_checked = True
    except GitHubError:
        pass
    seen = {r.split(" (")[0] for r in checks.requirements}
    for key in ("contributing", "pr_template"):
        path = paths.get(key)
        if not path:
            continue
        try:
            content = gh.get_file(full_name, path, ref=head_sha, max_bytes=256 * 1024)
        except GitHubError:
            continue
        for requirement in find_requirements((content or b"").decode("utf-8", "replace"), path):
            if requirement.split(" (")[0] not in seen:
                checks.requirements.append(requirement)
                seen.add(requirement.split(" (")[0])
    return checks
