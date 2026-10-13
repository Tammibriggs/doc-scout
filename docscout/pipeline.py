"""``docscout run``: find candidates, check them, analyze their docs, score, report.

Sources take turns, starting with maintainers' help requests (the strongest signal).
Repos already reported, marked done or ignored, or checked recently are skipped. Each
analyzed repo is saved as soon as it's done, so an interrupted run loses nothing.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from docscout import apitypes
from docscout.analyze.checks import Checks, free_checks, paid_checks
from docscout.analyze.gaps import Gap, effort_label
from docscout.apitypes import ApiType
from docscout.apitypes.base import DocsContext
from docscout.config import Config
from docscout.db import Store, StoredFinding
from docscout.discover import Evaluated, evaluate, source_candidates
from docscout.config import data_dir
from docscout.github import AuthError, GitHub, GitHubError, RateLimited
from docscout.profile import language_policy, one_line
from docscout.report import RunSummary, render, write
from docscout.scoring import Score, opportunity_score
from docscout.sources import SourceUnavailable, awesome_selfhosted

log = logging.getLogger(__name__)

SOURCE_ORDER = ("help_requested", "awesome_selfhosted", "repo_search", "code_search")


def guarded(name: str, stream: Iterator[Any], notes: list[str]) -> Iterator[Any]:
    """A source that fails is skipped for this run (with a note); the others carry on.
    Rate limits and an expired token still stop the run, since they affect every source."""
    try:
        yield from stream
    except (RateLimited, AuthError):
        raise
    except (SourceUnavailable, GitHubError, httpx.HTTPError) as exc:
        log.warning("skipping the %s source this run: %s", name, exc)
        notes.append(f"Skipped the {name} source this run: {exc}")


def interleave(streams: Iterable[Iterator[Any]]) -> Iterator[Any]:
    """Round-robin over several iterators until all are exhausted."""
    active = list(streams)
    while active:
        for stream in list(active):
            try:
                yield next(stream)
            except StopIteration:
                active.remove(stream)


@dataclass
class Analysis:
    gap: Gap
    score: Score
    details: dict[str, Any]


def analyze(gh: GitHub, ev: Evaluated, cfg: Config, types_by_key: dict[str, ApiType]) -> Analysis | None:
    """Docs gaps and score for a repo that passed the checks, or None if there's nothing to report."""
    api_type = types_by_key.get(ev.classification.api_type or "")
    # Until the LLM can confirm borderline repos (stage M2), only confident ones are reported.
    if api_type is None or ev.classification.api_confidence < cfg["classify"]["min_confidence"]:
        return None
    ctx = DocsContext(
        gh=gh,
        full_name=ev.candidate.full_name,
        repo=ev.repo,
        tree=ev.tree or [],
        readme=ev.readme,
        head_sha=ev.head_sha,
        type_confidence=ev.classification.api_confidence,
    )
    gap = api_type.analyze(ctx)
    if gap is None:
        return None
    score = opportunity_score(
        gap.score,
        ev.health or 0.0,
        ev.classification.api_confidence,
        ev.candidate.issues,
        ev.language_match,
        int(cfg["scoring"]["language_bonus"]),
    )
    repo = ev.repo
    details = {
        "api_type": api_type.key,
        "api_label": api_type.label,
        "gap": gap.as_dict(),
        "score": score.as_dict(),
        "breakdown": score.breakdown(),
        "effort": effort_label(gap.effort_units),
        "repo": {
            "stars": repo.get("stargazers_count"),
            "language": repo.get("language"),
            "language_match": ev.language_match,
            "pushed_at": repo.get("pushed_at"),
            "description": repo.get("description"),
        },
        "stats": ev.stats.as_dict() if ev.stats else {},
        "issues": ev.candidate.issues[:3],
        "head_sha": ev.head_sha,
        "reasons": ev.classification.reasons,
    }
    checks, paths = free_checks(ev.tree or [], ev.readme)
    details["checks"] = checks.as_dict()
    details["check_paths"] = paths
    return Analysis(gap, score, details)


def before_you_start(gh: GitHub, run_id: int, store: Store, findings: list[StoredFinding]) -> None:
    """Claim and requirement checks for reported items (about 2-3 API calls each)."""
    for finding in findings:
        d = finding.details
        checks = Checks(**d.get("checks", {}))
        paid_checks(gh, finding.full_name, checks, d.get("check_paths", {}), d.get("issues", []), d.get("head_sha"))
        d["checks"] = checks.as_dict()
        store.update_details(run_id, finding.full_name, d)


@dataclass
class RunResult:
    run_id: int
    summary: RunSummary
    findings: list[StoredFinding]
    still_open: list[StoredFinding]
    report_path: Path | None
    status: str


def run(
    gh: GitHub,
    cfg: Config,
    store: Store,
    now: datetime,
    *,
    limit: int,
    sources: list[str],
    rng: random.Random | None = None,
    progress: Callable[[str], None] = lambda message: None,
    clock: Callable[[], float] = time.monotonic,
) -> RunResult:
    types = apitypes.enabled_types(cfg["api_types"])
    by_key = {t.key: t for t in types}
    policy = language_policy(cfg["profile"], types)
    rng = rng or random.Random(now.strftime("%Y-%m-%d"))
    recheck = int(cfg["discovery"]["recheck_after_days"])
    ordered = [s for s in SOURCE_ORDER if s in sources] + [s for s in sources if s not in SOURCE_ORDER]
    run_id = store.start_run(now)
    summary = RunSummary()
    streams = [guarded(name, source_candidates(name, gh, cfg, rng, now.date(), types, policy), summary.notes) for name in ordered]
    started = clock()
    status = "ok"
    auth_error: AuthError | None = None
    seen: set[str] = set()
    try:
        for cand in interleave(streams):
            if summary.analyzed >= limit:
                break
            key = cand.full_name.lower()
            if key in seen or store.skip_reason(cand.full_name, now, recheck):
                continue
            seen.add(key)
            summary.evaluated += 1
            try:
                ev = evaluate(gh, cand, cfg, now, types, policy)
            except (RateLimited, AuthError):
                raise
            except (GitHubError, httpx.HTTPError) as exc:
                log.warning("skipping %s: %s", cand.full_name, exc)
                summary.analyzed += 1
                store.save_repo(cand.full_name, now, source=cand.source, rejected=f"error: {exc}")
                continue
            if ev.used_api:
                summary.analyzed += 1
            store.save_repo(
                cand.full_name,
                now,
                source=cand.source,
                stars=ev.repo.get("stargazers_count"),
                language=ev.repo.get("language"),
                api_type=ev.classification.api_type,
                type_conf=ev.classification.api_confidence,
                health=ev.health,
                rejected=ev.rejected,
            )
            if ev.rejected:
                continue
            summary.passed += 1
            try:
                result = analyze(gh, ev, cfg, by_key)
            except (RateLimited, AuthError):
                raise
            except (GitHubError, httpx.HTTPError) as exc:
                log.warning("couldn't analyze %s: %s", cand.full_name, exc)
                continue
            if result is None:
                continue
            store.save_finding(
                run_id,
                cand.full_name,
                now,
                api_type=result.details["api_type"],
                kind=result.gap.kind,
                gap=result.gap.score,
                score=result.score.total,
                effort=result.details["effort"],
                details=result.details,
            )
            summary.with_gaps += 1
            progress(f"{cand.full_name}: {result.gap.kind} gap {result.gap.score:.0f}, score {result.score.total:.0f}")
    except RateLimited as exc:
        status, summary.stopped_early = "partial", str(exc)
    except AuthError as exc:
        status, summary.stopped_early, auth_error = "failed", str(exc), exc
    except KeyboardInterrupt:
        status, summary.stopped_early = "partial", "interrupted (Ctrl+C)"
    except Exception as exc:  # keep what was found; the error is reported, not hidden
        log.exception("run stopped by an unexpected error")
        status, summary.stopped_early = "partial", f"unexpected error: {exc!r}"

    summary.api_calls = dict(gh.calls)
    summary.seconds = clock() - started
    if awesome_selfhosted.SOURCE in ordered:
        note = awesome_selfhosted.staleness_note(data_dir() / "awesome_selfhosted.json", now)
        if note:
            summary.notes.append(note)
    report_cfg = cfg["report"]
    findings = store.run_findings(run_id, float(report_cfg["min_score"]), int(report_cfg["max_items"]))
    if findings and cfg["checks"]["claim_and_policy"] and auth_error is None:
        try:
            before_you_start(gh, run_id, store, findings)
        except Exception as exc:  # optional extras: never lose the report over them
            log.warning("skipped some before-you-start checks: %s", exc)
        findings = store.run_findings(run_id, float(report_cfg["min_score"]), int(report_cfg["max_items"]))
    still_open = store.still_open(run_id, int(report_cfg["still_open_count"]))
    report_path = None
    if findings:
        markdown = render(findings, still_open, summary, now, one_line(cfg.values, types))
        report_path = write(cfg.reports_dir, now, markdown)
        for finding in findings:
            store.set_status(finding.full_name, "reported", now)
    elif status == "ok":
        status = "empty"
    store.finish_run(
        run_id,
        now,
        status=status,
        analyzed=summary.analyzed,
        new_items=len(findings),
        api_calls=sum(summary.api_calls.values()),
        report_path=str(report_path) if report_path else None,
        error=summary.stopped_early,
    )
    if auth_error is not None:
        raise auth_error
    return RunResult(run_id, summary, findings, still_open, report_path, status)
