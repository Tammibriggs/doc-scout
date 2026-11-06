"""What an open pull request would fix, measured (M6 step 6c).

When a PR changes the docs file DocScout measured, DocScout measures the file in the PR's version
against the version the PR started from (the merge base, so changes on the main branch since then
aren't credited to the PR), with the same scorer that found the gap. What the PR claims is what
needed work before it and doesn't after: per gap key, the operations (or endpoints) it fixes, and
the fields it describes. Operations it adds or removes don't count, and neither does progress
inside an operation that still needs work.

On 6 Nov this replaced Gemma's opinion of the 14 PRs it had flagged as claims: measured, none of
them fixed a gap. They were features and fixes that edit the spec for their own changes.
"""

from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Any

from docscout.analyze.apitypes.openapi import SpecReport, score_spec
from docscout.analyze.apitypes.rest_prose import KEYS as PROSE_KEYS
from docscout.analyze.apitypes.rest_prose import analyze_docs
from docscout.find.github import GitHub, GitHubError

log = logging.getLogger(__name__)

SPEC_LEVEL = ("overview", "security", "tags", "servers")  # checks on the whole spec, not on operations
_MEASURED: OrderedDict[tuple[str, str], Any] = OrderedDict()  # the same file version, measured once (PRs often share a merge base)
_KEPT = 16


def _scored(content: bytes, path: str) -> SpecReport | None:
    """``score_spec``, remembered for the last few file versions. Its result is only read here."""
    key = (hashlib.sha256(content).hexdigest(), path)
    if key in _MEASURED:
        _MEASURED.move_to_end(key)
        return _MEASURED[key]
    report = score_spec(content, path)
    _MEASURED[key] = report
    while len(_MEASURED) > _KEPT:
        _MEASURED.popitem(last=False)
    return report
MAX_LISTED = 2000  # operations or fields kept per gap key in a stored result


def spec_fixes(before: SpecReport, after: SpecReport) -> tuple[dict[str, list[str]], list[str]]:
    """Per gap key, the operations that needed work in ``before`` and don't in ``after`` (and still
    exist); and the fields that gained a description."""
    exists = set(after.labels)
    fixed: dict[str, list[str]] = {}
    for check, ops in before.failing.items():
        still = set(after.failing.get(check, []))
        done = [op for op in ops if op in exists and op not in still]
        if done:
            fixed[check] = done[:MAX_LISTED]
    keys_after, undescribed_after = set(after.field_keys), set(after.undescribed_fields)
    fields = [f for f in before.undescribed_fields if f in keys_after and f not in undescribed_after]
    for key in SPEC_LEVEL:
        if key in before.points and key not in after.points:
            fixed[key] = ["the spec"]
    return fixed, fields[:MAX_LISTED]


def _endpoints(path: str, content: bytes) -> dict[str, set[str]]:
    result = analyze_docs([(path, content.decode("utf-8", "replace"))])
    return {e.label: {PROSE_KEYS[m] for m in e.missing} for e in result.endpoints}


def prose_fixes(path: str, before: bytes, after: bytes) -> dict[str, list[str]]:
    """Per gap key, the endpoints whose prose docs gained what they lacked."""
    then, now = _endpoints(path, before), _endpoints(path, after)
    fixed: dict[str, list[str]] = {}
    for label, missing in then.items():
        if label in now:
            for key in sorted(missing - now[label]):
                fixed.setdefault(key, []).append(label)
    return fixed


def touches(pr: dict[str, Any], path: str) -> bool | None:
    """True or False when the PR's file list (from the PR query) settles whether it changes
    ``path``; None when the list is cut short and GitHub must be asked."""
    files = pr.get("files") or []
    if path in files:
        return True
    total = pr.get("changed_files")
    return False if total is not None and len(files) >= int(total) else None


def measure(gh: GitHub, full_name: str, gap: dict[str, Any], pr: dict[str, Any]) -> dict[str, Any]:
    """What ``pr`` would fix in the measured docs file. The result is stored with the pick and
    used again until the PR's head commit changes. Raises GitHubError for a failed request."""
    path, head, base = gap.get("location"), (pr.get("head") or {}).get("sha"), (pr.get("base") or {}).get("sha")
    result: dict[str, Any] = {"number": pr.get("number"), "head": head, "touches": False, "readable": True, "fixed": {}, "fixed_fields": []}
    if not path or gap.get("kind") not in ("spec", "prose"):
        result["readable"] = False
        return result
    if touches(pr, path) is False:
        return result  # settled by the PR query: no request needed
    if not head or not base:
        result["readable"] = False
        return result
    compared = gh.compare(full_name, base, head)
    if compared is None or not compared.get("merge_base"):
        result["readable"] = False
        return result
    if path not in compared["files"]:
        result["readable"] = bool(compared["complete"])  # a PR changing 300 files or more can't be told
        return result
    result["touches"] = True
    before = gh.get_file(full_name, path, ref=compared["merge_base"])
    after = gh.get_file(full_name, path, ref=head)
    if before is None or after is None:  # the PR deletes the file, or it's too large to read
        result["readable"] = False
        return result
    if gap.get("kind") == "spec":
        then, now = _scored(before, path), _scored(after, path)
        if then is None or now is None:
            result["readable"] = False
            return result
        result["fixed"], result["fixed_fields"] = spec_fixes(then, now)
    else:
        result["fixed"] = prose_fixes(path, before, after)
    return result


def main_failing(gh: GitHub, full_name: str, gap: dict[str, Any]) -> dict[str, list[str]] | None:
    """Per gap key, what needs work on the main branch now; None if the file can't be read."""
    path = gap.get("location")
    if not path:
        return None
    try:
        content = gh.get_file(full_name, path)
    except GitHubError as exc:
        log.info("couldn't read %s in %s: %s", path, full_name, exc)
        return None
    if content is None:
        return None
    if gap.get("kind") == "spec":
        report = _scored(content, path)
        return report.failing if report else None
    failing: dict[str, list[str]] = {}
    for label, missing in _endpoints(path, content).items():
        for key in missing:
            failing.setdefault(key, []).append(label)
    return failing


def work_left(failing: dict[str, list[str]], covered: dict[str, set[str]], whole: set[str]) -> tuple[int, int]:
    """(operations or endpoints still needing work, all that need work): one is left while any
    gap it has isn't fixed by an open PR (``covered``, per key) or taken by a live offer (``whole``:
    keys an offer covers entirely)."""
    gaps: dict[str, set[str]] = {}
    for key, ops in failing.items():
        for op in ops:
            gaps.setdefault(op, set()).add(key)
    left = sum(1 for op, keys in gaps.items() if any(k not in whole and op not in covered.get(k, set()) for k in keys))
    return left, len(gaps)
