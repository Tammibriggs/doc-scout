"""The Markdown report: what to fix, where, and why it's worth it.

Every value that came from GitHub goes through :mod:`docscout.sanitize`; links are only
built from GitHub URLs DocScout constructs itself.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from docscout.analyze.gaps import Gap, kind_label
from docscout.db import StoredFinding
from docscout.health import parse_time
from docscout.sanitize import blob_url, code, link, repo_url, text


@dataclass
class RunSummary:
    evaluated: int = 0  # candidates looked at
    analyzed: int = 0  # candidates that cost API calls
    passed: int = 0  # passed the health checks
    with_gaps: int = 0
    api_calls: dict[str, int] = field(default_factory=dict)
    seconds: float = 0.0
    stopped_early: str | None = None
    notes: list[str] = field(default_factory=list)  # e.g. a source that was skipped or is going stale
    model: str | None = None  # the reviewing model, e.g. "Gemma"
    reviewed: int = 0
    accepted: int = 0


_STYLE_NAMES = {"rest": "REST", "graphql": "GraphQL", "grpc": "gRPC", "event": "event", "rpc": "RPC"}


def _verdict(review: dict[str, Any]) -> str:
    kind = review.get("project_type")
    if kind == "serves_api":
        style = _STYLE_NAMES.get(str(review.get("api_style")))
        return f"an app or service with its own {style} API" if style else "an app or service with its own API"
    return {"api_tooling": "a tool for working with APIs", "library": "a library or SDK", "spam": "spam"}.get(str(kind), "something else")


def _model_name(review: dict[str, Any]) -> str:
    name = str(review.get("model") or "the model")
    return "Gemma" if "gemma" in name.lower() else name.split(":", 1)[-1]


def _days_ago(value: str | None, now: datetime) -> str:
    when = parse_time(value)
    if when is None:
        return "unknown"
    days = (now - when).days
    return "today" if days <= 0 else "1 day ago" if days == 1 else f"{days} days ago"


def render_item(index: int, finding: StoredFinding, now: datetime) -> list[str]:
    """The item as Markdown blocks; join them with blank lines so each stays its own paragraph."""
    name, d = finding.full_name, finding.details
    gap = Gap.from_dict(d["gap"])
    repo: dict[str, Any] = d.get("repo") or {}
    stats: dict[str, Any] = d.get("stats") or {}

    lines = [f"### {index}. {link(text(name, 140), repo_url(name))} · score {finding.score:.0f} · effort {d.get('effort', 'unknown')}"]
    meta = [f"★ {int(repo.get('stars') or 0)}"]
    if repo.get("language"):
        meta.append(text(repo["language"], 40) + (" (yours)" if repo.get("language_match") else ""))
    meta.append(f"pushed {_days_ago(repo.get('pushed_at'), now)}")
    if stats:
        merged = stats.get("outsider_merged_180d", 0)
        part = f"outside PRs in 180 days: {merged} merged, {stats.get('outsider_merge_rate', 0):.0%} merge rate"
        if stats.get("median_ttm_days") is not None:
            part += f", median {stats['median_ttm_days']:g} days to merge"
        meta.append(part)
    lines.append(" · ".join(meta))
    if repo.get("description"):
        lines.append(f"> {text(repo['description'], 200)}")
    review: dict[str, Any] = d.get("review") or {}
    who = text(_model_name(review), 60)
    if review:
        evidence = f" (\"{text(review['evidence'], 200)}\")" if review.get("evidence") else ""
        change = f"{float(review.get('code_confidence', 0)):.2f} → {float(review.get('final_confidence', 0)):.2f}"
        lines.append(f"**{who}'s review:** {text(_verdict(review))}{evidence} · type confidence {change}")

    label = text(kind_label(gap.kind, d.get("api_label", "API")))
    if gap.location:
        where = link(code(gap.location), blob_url(name, d.get("head_sha"), gap.location))
        lines.append(f"**{label}:** {where} ({text(gap.summary)})")
    else:
        lines.append(f"**{label}:** {text(gap.summary)}")
    bullets = []
    for f in gap.findings:
        line = f"- {text(f.text)}"
        if f.examples:
            examples = ", ".join(code(e, 80) for e in f.examples)
            line += f" (e.g. {examples}{f', +{f.more} more' if f.more else ''})"
        bullets.append(line)
    if bullets:
        lines.append("\n".join(bullets))
    if gap.suggestion:
        lines.append(f"**Suggestion:** {text(gap.suggestion, 400)}")
    if gap.check_manually:
        lines.append("**Check manually:** " + " · ".join(text(r, 140) for r in gap.check_manually))
    elif gap.published:  # with "check manually" the same places are already listed
        lines.append("**Docs published:** " + " · ".join(text(p, 140) for p in gap.published))
    if gap.unverified:
        lines.append("*Unverified: based on finding no docs, not on reading them.*")
    if review.get("why"):
        lines.append(f"**Why it matters ({who}):** {text(review['why'], 600)}")
    if review.get("first_steps"):
        steps = "\n".join(f"{i}. {text(step, 300)}" for i, step in enumerate(review["first_steps"][:3], 1))
        lines.append(f"**First steps ({who}):**\n\n{steps}")

    checks = d.get("checks") or {}
    if checks:
        parts = []
        if checks.get("claimed"):
            parts += [f"⚠️ {text(c, 140)}" for c in checks["claimed"]]
        elif checks.get("claim_checked"):
            parts.append("✅ not claimed")
        parts += [f"⚠️ {text(r, 220)}" for r in checks.get("requirements") or []]
        parts.append(f"local setup: {text(checks.get('local_setup', 'unclear'))}")
        lines.append("**Before you start:** " + " · ".join(parts))

    issues = d.get("issues") or []
    if issues:
        parts = []
        for issue in issues[:3]:
            label_md = text(f"#{issue.get('number')} {issue.get('title', '')}", 120)
            outreach = f" ({text(', '.join(issue.get('outreach') or []))})" if issue.get("outreach") else ""
            parts.append(link(label_md, str(issue.get("html_url", ""))) + outreach)
        lines.append("**Maintainers asked for help:** " + " · ".join(parts))
    lines.append(f"*Score: {text(d.get('breakdown', ''))}*")
    return lines


def render(
    findings: list[StoredFinding],
    still_open: list[StoredFinding],
    summary: RunSummary,
    now: datetime,
    looking_for: str,
) -> str:
    local = now.astimezone()  # your day, not UTC's: a run just after midnight belongs to the new day
    date = f"{local.day} {local.strftime('%b %Y')}"  # "%-d" isn't supported on Windows
    lines = [
        f"# DocScout · {date} · {len(findings)} new · {len(still_open)} still open",
        "",
        f"Looking for: {text(looking_for, 300)}",
        "",
    ]
    if findings:
        lines += ["## New", ""]
        for i, finding in enumerate(findings, 1):
            lines += ["\n\n".join(render_item(i, finding, now)), ""]
    if still_open:
        lines += ["## Still open from earlier", ""]
        for finding in still_open:
            gap = finding.details.get("gap") or {}
            kind = kind_label(gap.get("kind", ""), finding.details.get("api_label", "API"))
            lines.append(f"- {link(text(finding.full_name, 140), repo_url(finding.full_name))} · score {finding.score:.0f} · {text(kind)}")
        lines.append("")
    lines += [
        "---",
        "",
        "When you're done with a project, or not interested, hide it from future reports:",
        "`docscout done OWNER/REPO` or `docscout ignore OWNER/REPO --reason \"...\"`",
        "",
        _footer(summary),
        "",
    ]
    return "\n".join(lines)


def _footer(summary: RunSummary) -> str:
    calls = ", ".join(f"{k} {v}" for k, v in sorted(summary.api_calls.items())) or "none"
    minutes, seconds = divmod(int(summary.seconds), 60)
    reviewed = f"{text(summary.model, 60)} reviewed {summary.reviewed} ({summary.accepted} accepted) · " if summary.model else ""
    footer = (
        f"*Checked {summary.evaluated} repos · {summary.passed} passed the health checks · "
        f"{summary.with_gaps} with docs gaps · {reviewed}GitHub API calls: {calls} · took {minutes}m{seconds:02d}s*"
    )
    if summary.stopped_early:
        footer += f"\n\n*Stopped early: {text(summary.stopped_early, 200)}*"
    for note in summary.notes:
        footer += f"\n\n*Note: {text(note, 300)}*"
    return footer


def write(report_dir: Path, now: datetime, markdown: str) -> Path:
    """Save as YYYY-MM-DD.md (YYYY-MM-DD_2.md for a later run that day) and copy to latest.md."""
    report_dir.mkdir(parents=True, exist_ok=True)
    stem = now.astimezone().strftime("%Y-%m-%d")  # the local day, as daily.check_due counts days
    path = report_dir / f"{stem}.md"
    number = 2
    while path.exists():
        path = report_dir / f"{stem}_{number}.md"
        number += 1
    path.write_text(markdown, encoding="utf-8")
    shutil.copyfile(path, report_dir / "latest.md")
    return path
