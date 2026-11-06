"""The look for changes (M6 step 6d): every listed pick, up to 60 to a request, every 6 hours.

One GraphQL request asks, for each pick: its current name, whether it's archived, its last push,
the version of the measured docs file, its open PRs (how many, the latest update), and each
help-request issue's state, update time and comment count. Checked 6 Nov: 120 picks in 2
requests and 19 seconds, 1 point each of the 5,000 an hour. Renames are followed, and a deleted
repo or issue fails only its own part of the answer.

The answers are kept with the pick (``details["watch"]``) and compared with the last look, so a
pick whose answers didn't change costs no further requests.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from docscout.find.github import GitHub, GitHubError
from docscout.run.db import StoredFinding

log = logging.getLogger(__name__)

BATCH = 60
SMALLEST = 5  # a batch GitHub can't answer (502 on 6 Nov) is split down to this size


def _q(text: str) -> str:
    return json.dumps(text)


def _block(alias: str, finding: StoredFinding) -> str:
    owner, name = finding.full_name.split("/", 1)
    d = finding.details
    parts = [
        "nameWithOwner isArchived pushedAt",
        "defaultBranchRef { target { oid } }",
        "pullRequests(states: [OPEN], first: 1, orderBy: {field: UPDATED_AT, direction: DESC}) { totalCount nodes { updatedAt } }",
    ]
    for issue in (d.get("issues") or [])[:3]:
        number = int(issue["number"])
        parts.append(f"i{number}: issue(number: {number}) {{ state updatedAt comments {{ totalCount }} }}")
    location = (d.get("gap") or {}).get("location")
    if location:
        parts.append(f"docs: object(expression: {_q('HEAD:' + location)}) {{ ... on Blob {{ oid }} }}")
    return f"{alias}: repository(owner: {_q(owner)}, name: {_q(name)}) {{ {' '.join(parts)} }}"


def _state(node: dict[str, Any], missing: set[str], alias: str, finding: StoredFinding) -> dict[str, Any]:
    prs = node.get("pullRequests") or {}
    latest = (prs.get("nodes") or [{}])[0] if prs.get("nodes") else {}
    issues: dict[str, Any] = {}
    for issue in (finding.details.get("issues") or [])[:3]:
        number = int(issue["number"])
        value = node.get(f"i{number}")
        if value is None or f"{alias}.i{number}" in missing:
            issues[str(number)] = ["DELETED", None, 0]
        else:
            issues[str(number)] = [value.get("state"), value.get("updatedAt"), (value.get("comments") or {}).get("totalCount", 0)]
    return {
        "name": node.get("nameWithOwner"),
        "archived": bool(node.get("isArchived")),
        "pushed": node.get("pushedAt"),
        "head": ((node.get("defaultBranchRef") or {}).get("target") or {}).get("oid"),
        "docs": (node.get("docs") or {}).get("oid"),
        "prs": [prs.get("totalCount", 0), latest.get("updatedAt")],
        "issues": issues,
    }


def look(gh: GitHub, findings: list[StoredFinding], batch: int = BATCH) -> dict[str, dict[str, Any] | None]:
    """repo (lowercase) -> what GitHub says now, or None when the repo is gone (deleted or private).
    A pick GitHub couldn't answer for is left out: it waits for the next look, it isn't gone."""
    states: dict[str, dict[str, Any] | None] = {}
    queue = [(start, findings[start : start + batch]) for start in range(0, len(findings), batch)]
    while queue:
        start, chunk = queue.pop(0)
        aliases = {f"r{start + k}": f for k, f in enumerate(chunk)}
        try:
            data, missing = gh.graphql_batch("query { " + " ".join(_block(a, f) for a, f in aliases.items()) + " }")
        except GitHubError as exc:
            if exc.status < 500:
                raise
            if len(chunk) > SMALLEST:
                half = len(chunk) // 2
                queue[:0] = [(start, chunk[:half]), (start + half, chunk[half:])]
            else:
                log.info("GitHub couldn't answer for %d picks (%s); they wait for the next look", len(chunk), exc)
            continue
        for alias, f in aliases.items():
            node = data.get(alias)
            states[f.full_name.lower()] = None if node is None or alias in missing else _state(node, missing, alias, f)
    return states


def changed(old: dict[str, Any] | None, new: dict[str, Any]) -> set[str]:
    """What changed since the last look: "docs", "prs", and "issue <n>" for each help request
    whose state, text or comments changed. Everything counts as changed on the first look."""
    if not old:
        return {"docs", "prs", *(f"issue {n}" for n in new.get("issues") or {})}
    found = set()
    if old.get("docs") != new.get("docs"):
        found.add("docs")
    if list(old.get("prs") or []) != list(new.get("prs") or []):
        found.add("prs")
    for number, value in (new.get("issues") or {}).items():
        if list((old.get("issues") or {}).get(number) or []) != list(value):
            found.add(f"issue {number}")
    return found
