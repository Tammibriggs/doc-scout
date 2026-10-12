"""Evaluate candidates (gate + classifier) and draw labeled samples for stage M0.

Checks run cheapest-first so rejected repos cost as few API calls as possible:
stage-1 classifier (free) → repo metadata (≤1 call) → PR and commit history (2 calls)
→ file tree and README (2 calls).

Everything specific to one kind of API comes from the enabled API types
(:mod:`docscout.apitypes`); this module only orchestrates.
"""

from __future__ import annotations

import csv
import logging

import httpx
import random
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from docscout import apitypes
from docscout.analyze.tree import has_contributing
from docscout.apitypes import ApiType
from docscout.classify import Classification, classify
from docscout.config import Config, data_dir
from docscout.github import AuthError, GitHub, GitHubError, NotFound, RateLimited
from docscout.health import PRStats, gate_activity, gate_metadata, health_score, pr_stats
from docscout.profile import LanguagePolicy, language_policy
from docscout.sources import Candidate, awesome_selfhosted, code_search, help_requested, repo_search

log = logging.getLogger(__name__)

LABELS = ("serves_api", "api_tooling", "library", "spam", "other")
_FULL_REPO_KEYS = ("pushed_at", "license", "archived", "fork", "default_branch", "created_at")
LANGUAGE_SHARE = 0.25  # a language counts if it's at least this share of the repo's code


@dataclass
class Evaluated:
    candidate: Candidate
    repo: dict[str, Any]
    classification: Classification
    rejected: str | None = None  # None means it passed every gate
    stats: PRStats | None = None
    health: float | None = None
    definition_paths: list[str] = field(default_factory=list)
    language_match: bool | None = None  # None: no languages in the profile


def maintainers_asked_for_help(cand: Candidate) -> bool:
    """True if a maintainer-applied outreach label ("help wanted", "good first issue") was found."""
    return any(issue.get("outreach") for issue in cand.issues)


def activity_thresholds(cfg: Config, cand: Candidate) -> dict[str, Any]:
    health_cfg = cfg["health"]
    if maintainers_asked_for_help(cand):
        return health_cfg | health_cfg.get("help_requested", {})
    return health_cfg


def language_matches(gh: GitHub, full_name: str, repo: dict[str, Any], policy: LanguagePolicy) -> bool:
    """True if the repo is written in one of the contributor's languages.

    The main language is free; the full breakdown costs one call and is only fetched when
    languages are required, since a main language can mislead (a Python backend with a
    big TypeScript frontend is listed as TypeScript).
    """
    if any(lang.matches(repo.get("language")) for lang in policy.languages):
        return True
    if not policy.required:
        return False
    breakdown = gh.get_languages(full_name)
    total = sum(breakdown.values()) or 1
    return any(lang.matches(name) and size / total >= LANGUAGE_SHARE for name, size in breakdown.items() for lang in policy.languages)


def evaluate(
    gh: GitHub,
    cand: Candidate,
    cfg: Config,
    now: datetime,
    api_types: list[ApiType] | None = None,
    policy: LanguagePolicy | None = None,
) -> Evaluated:
    types = api_types if api_types is not None else apitypes.enabled_types(cfg["api_types"])
    policy = policy if policy is not None else language_policy(cfg["profile"], types)
    meta = cand.meta
    stage1 = classify(meta, now=now, api_types=types, prior=cand.prior, issues=cand.issues)
    result = Evaluated(cand, meta, stage1)
    prefilter = cfg["classify"].get("prefilter_below", 0.25)
    if stage1.project_type == "spam":
        result.rejected = f"spam: {stage1.reasons[0]}"
        return result
    if stage1.api_confidence < prefilter:
        result.rejected = f"prefilter: looks like {stage1.project_type}"
        return result

    if not all(key in meta for key in _FULL_REPO_KEYS):
        try:
            meta = gh.get_repo(cand.full_name)
        except NotFound:
            result.rejected = "repo not found"
            return result
        result.repo = meta
        result.classification = classify(meta, now=now, api_types=types, prior=cand.prior, issues=cand.issues)
    reason = gate_metadata(meta, cfg["health"], now)
    if reason:
        result.rejected = reason
        return result

    if policy.languages:
        result.language_match = language_matches(gh, cand.full_name, meta, policy)
        if policy.required and not result.language_match:
            result.rejected = f"language: {meta.get('language') or 'unknown'} is not one of yours"
            return result

    since = (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    stats = pr_stats(gh.list_closed_pulls(cand.full_name), gh.list_commits(cand.full_name, since), now)
    result.stats = stats
    reason = gate_activity(stats, activity_thresholds(cfg, cand))
    if reason:
        result.rejected = reason
        return result

    tree, _truncated = gh.get_tree(cand.full_name, meta.get("default_branch") or "HEAD")
    readme = gh.get_readme(cand.full_name)
    result.classification = classify(meta, now=now, api_types=types, prior=cand.prior, tree=tree, readme=readme, issues=cand.issues)
    result.health = health_score(stats, has_contributing(tree))
    result.definition_paths = [f"{t.key}: {f.path}" for t in types for f in t.find_definitions(tree)[:3]]
    return result


# ---------------------------------------------------------------------- sampling


def source_candidates(
    name: str,
    gh: GitHub,
    cfg: Config,
    rng: random.Random,
    today: date,
    api_types: list[ApiType],
    policy: LanguagePolicy | None = None,
) -> Iterator[Candidate]:
    """Candidates from one source, in a shuffled order suitable for sampling."""
    disc = cfg["discovery"]
    # Required languages narrow the searches themselves; code search can't (its language: means file language).
    qualifiers = policy.search_qualifiers() if policy else ""
    if name == awesome_selfhosted.SOURCE:
        seed = awesome_selfhosted.load_seed(gh, data_dir() / "awesome_selfhosted.json", disc["seed_max_age_days"])
        rng.shuffle(seed)
        yield from seed
    elif name == repo_search.SOURCE:
        slices = repo_search.all_slices(apitypes.repo_queries(api_types), disc["star_bands"], qualifiers)
        rng.shuffle(slices)
        for slice_ in slices:
            page = list(
                repo_search.fetch_slice(gh, slice_, pushed_within_days=cfg["health"]["pushed_within_days"], max_pages=1, today=today)
            )
            rng.shuffle(page)
            yield from page[:5]
    elif name == help_requested.SOURCE:
        since = today - timedelta(days=disc["issue_lookback_days"])
        keywords = apitypes.issue_keywords(api_types, disc["help_requested_keywords"])
        query_list = help_requested.queries(disc["issue_label_families"], keywords, since, qualifiers)
        found = list(
            help_requested.fetch(
                gh,
                query_list,
                label_denylist=disc["issue_label_denylist"],
                title_denylist=disc["issue_title_denylist"],
                max_pages=1,
            )
        )
        rng.shuffle(found)
        yield from found
    elif name == code_search.SOURCE:
        query_list = code_search.queries(apitypes.definition_filenames(api_types), disc["code_search_size_bands"])
        rng.shuffle(query_list)
        for query in query_list:
            page = list(code_search.fetch(gh, query, max_pages=1))
            rng.shuffle(page)
            yield from page[:8]
    else:
        raise ValueError(f"unknown source {name!r}")


@dataclass
class SourceSummary:
    source: str
    tried: int = 0
    passed: int = 0
    rejections: dict[str, int] = field(default_factory=dict)


@dataclass
class Sample:
    passed: list[Evaluated] = field(default_factory=list)
    rejected: list[Evaluated] = field(default_factory=list)
    summaries: list[SourceSummary] = field(default_factory=list)
    stopped_early: str | None = None  # why sampling stopped before reaching the target


def draw_sample(
    gh: GitHub,
    cfg: Config,
    sources: list[str],
    total: int,
    *,
    rng: random.Random,
    now: datetime,
    max_tries_factor: int = 6,
    progress: Callable[[str], None] = lambda msg: None,
) -> Sample:
    """Up to ``total`` gate-passing repos, split evenly across sources.

    A failed request skips that one repo (recorded as rejected with the error). A rate
    limit, an auth failure, Ctrl+C or an unexpected error stops sampling but keeps
    everything gathered so far.
    """
    api_types = apitypes.enabled_types(cfg["api_types"])
    policy = language_policy(cfg["profile"], api_types)
    per_source = max(1, total // len(sources))
    sample = Sample()
    seen: set[str] = set()
    try:
        for name in sources:
            summary = SourceSummary(name)
            sample.summaries.append(summary)
            for cand in source_candidates(name, gh, cfg, rng, now.date(), api_types, policy):
                key = cand.full_name.lower()
                if key in seen:
                    continue
                seen.add(key)
                try:
                    ev = evaluate(gh, cand, cfg, now, api_types, policy)
                except (RateLimited, AuthError):
                    raise
                except (GitHubError, httpx.HTTPError) as exc:
                    log.warning("skipping %s: %s", cand.full_name, exc)
                    ev = Evaluated(cand, cand.meta, Classification("other", 0.0), rejected=f"error: {exc}")
                summary.tried += 1
                if ev.rejected:
                    sample.rejected.append(ev)
                    bucket = ev.rejected.split(":")[0]
                    summary.rejections[bucket] = summary.rejections.get(bucket, 0) + 1
                else:
                    sample.passed.append(ev)
                    summary.passed += 1
                    progress(f"[{name}] {summary.passed}/{per_source} {cand.full_name}")
                if summary.passed >= per_source or summary.tried >= per_source * max_tries_factor:
                    break
    except (RateLimited, AuthError) as exc:
        sample.stopped_early = str(exc)
    except KeyboardInterrupt:
        sample.stopped_early = "interrupted (Ctrl+C)"
    except Exception as exc:  # keep the partial sample; the error is reported, not hidden
        log.exception("sampling stopped by an unexpected error")
        sample.stopped_early = f"unexpected error: {exc!r}"
    return sample


# ---------------------------------------------------------------------- CSV output

SAMPLE_COLUMNS = [
    "label", "full_name", "url", "source", "predicted_type", "api_type", "api_confidence", "health",
    "help_requested", "stars", "language", "language_match", "description", "reasons", "definition_files", "issues", "note",
]  # fmt: skip


def _row(ev: Evaluated) -> dict[str, Any]:
    repo = ev.repo
    return {
        "label": "",
        "full_name": ev.candidate.full_name,
        "url": f"https://github.com/{ev.candidate.full_name}",
        "source": ev.candidate.source,
        "predicted_type": ev.classification.project_type,
        "api_type": ev.classification.api_type or "",
        "api_confidence": ev.classification.api_confidence,
        "health": "" if ev.health is None else ev.health,
        "help_requested": "yes" if maintainers_asked_for_help(ev.candidate) else "",
        "stars": repo.get("stargazers_count", ""),
        "language": repo.get("language") or "",
        "language_match": {True: "yes", False: "no", None: ""}[ev.language_match],
        "description": " ".join(str(repo.get("description") or "").split())[:200],
        "reasons": "; ".join(ev.classification.reasons),
        "definition_files": "; ".join(ev.definition_paths),
        "issues": "; ".join(i["html_url"] for i in ev.candidate.issues[:3]),
        "note": "",
    }


def write_sample(path: Path, rows: list[Evaluated]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=SAMPLE_COLUMNS)
        writer.writeheader()
        for ev in rows:
            writer.writerow(_row(ev))


def write_rejected(path: Path, rows: list[Evaluated]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["full_name", "source", "rejected_because", "predicted_type", "api_confidence"])
        for ev in rows:
            writer.writerow(
                [ev.candidate.full_name, ev.candidate.source, ev.rejected, ev.classification.project_type, ev.classification.api_confidence]
            )
