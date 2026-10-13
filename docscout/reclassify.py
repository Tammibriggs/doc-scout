"""Re-run the current classifier on a labeled sample, to measure changes without relabeling.

What each classification needs (repo details, a trimmed file list, README and issue titles)
is fetched once and cached in the user data folder, so tuning reruns cost no API calls.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from docscout.apitypes import ApiType
from docscout.classify import classify
from docscout.github import GitHub, GitHubError
from docscout.sources import awesome_selfhosted

log = logging.getLogger(__name__)

CACHE_VERSION = 1
README_CHARS = 60_000
_META_KEYS = ("full_name", "description", "topics", "created_at", "stargazers_count", "homepage", "language")


def _issue_numbers(row: dict[str, Any], full_name: str) -> list[int]:
    """Issue numbers from any cell of the row (a spreadsheet may have shifted the columns)."""
    pattern = re.compile(rf"https://github\.com/{re.escape(full_name)}/issues/(\d+)", re.IGNORECASE)
    cells = [str(v) for v in row.values() if v] + [str(v) for v in row.get(None, []) or []]
    return sorted({int(n) for cell in cells for n in pattern.findall(cell)})


def _keep(entry: dict[str, Any], types: list[ApiType]) -> bool:
    """Only the files the classifier looks at: root files, devcontainers and API definitions."""
    path = entry.get("path", "")
    name = path.rsplit("/", 1)[-1]
    if "/" not in path or path.lower().startswith(".devcontainer/"):
        return True
    return any(t.definition_pattern is not None and t.definition_pattern.search(name) for t in types)


def fetch_inputs(gh: GitHub, full_name: str, issue_numbers: list[int], types: list[ApiType]) -> dict[str, Any]:
    meta = gh.get_repo(full_name)
    tree, _ = gh.get_tree(full_name, meta.get("default_branch") or "HEAD")
    readme = gh.get_readme(full_name) or ""
    issues = []
    for number in issue_numbers[:3]:
        try:
            issues.append({"title": gh.get_issue(full_name, number).get("title", "")})
        except GitHubError:
            continue
    return {
        "meta": {k: meta.get(k) for k in _META_KEYS},
        "tree": [{"path": e["path"], "type": e.get("type"), "size": e.get("size")} for e in tree if _keep(e, types)],
        "readme": readme[:README_CHARS],
        "issues": issues,
    }


def load_cache(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("repos", {}) if data.get("version") == CACHE_VERSION else {}


def save_cache(path: Path, repos: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": CACHE_VERSION, "repos": repos}), encoding="utf-8")


@dataclass
class Changed:
    full_name: str
    label: str
    before: str
    after: str
    confidence_after: float


def reclassify(
    rows: list[dict[str, Any]],
    gh: GitHub,
    cache_path: Path,
    now: datetime,
    types: list[ApiType],
    min_confidence: float | None = None,
) -> tuple[list[dict[str, Any]], list[Changed], list[str]]:
    """(rows with current predictions, predictions that changed, repos that couldn't be fetched)."""
    cache = load_cache(cache_path)
    new_rows, changed, missing = [], [], []
    fetched = 0
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        full_name = (row.get("full_name") or "").strip()
        if not label or not full_name:
            continue
        key = full_name.lower()
        if key not in cache:
            try:
                cache[key] = fetch_inputs(gh, full_name, _issue_numbers(row, full_name), types)
            except GitHubError as exc:
                missing.append(f"{full_name}: {exc}")
                continue
            fetched += 1
            if fetched % 10 == 0:
                save_cache(cache_path, cache)
        data = cache[key]
        prior = awesome_selfhosted.PRIOR if row.get("source") == awesome_selfhosted.SOURCE else 0.0
        extra = {} if min_confidence is None else {"min_confidence": min_confidence}
        c = classify(data["meta"], now=now, api_types=types, prior=prior, tree=data["tree"], readme=data["readme"], issues=data["issues"], **extra)
        new_rows.append(dict(row, predicted_type=c.project_type, api_confidence=c.api_confidence, reasons="; ".join(c.reasons)))
        if c.project_type != row.get("predicted_type"):
            changed.append(Changed(full_name, label, str(row.get("predicted_type")), c.project_type, c.api_confidence))
    if fetched:
        save_cache(cache_path, cache)
    return new_rows, changed, missing
