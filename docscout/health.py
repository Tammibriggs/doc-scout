"""Repo health: is the project alive, and does it merge PRs from outsiders?

Everything here is code-only, so README text (or an LLM reading it) can't influence it.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

OUTSIDERS = {"CONTRIBUTOR", "FIRST_TIME_CONTRIBUTOR", "FIRST_TIMER", "NONE"}
BOT_NAMES = {"dependabot", "renovate", "github-actions", "pre-commit-ci", "snyk-bot", "greenkeeper", "imgbot"}


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _is_bot_login(login: str | None) -> bool:
    if not login:
        return False
    login = login.lower()
    return login.endswith("[bot]") or login in BOT_NAMES


def gate_metadata(repo: dict[str, Any], cfg: dict[str, Any], now: datetime) -> str | None:
    """Reason the repo fails the cheap metadata checks, or None if it passes."""
    if repo.get("archived"):
        return "archived"
    if repo.get("fork"):
        return "fork"
    if not repo.get("license"):
        return "no license"
    stars = repo.get("stargazers_count") or 0
    ranges = cfg["star_ranges"]
    if not any(low <= stars and (high is None or stars <= high) for low, high in ranges):
        lowest = min(low for low, _ in ranges)
        if stars < lowest:
            return f"fewer than {lowest} stars"
        return f"{stars} stars is outside your project sizes"
    pushed = parse_time(repo.get("pushed_at"))
    if pushed is None or now - pushed > timedelta(days=cfg["pushed_within_days"]):
        return f"no push in {cfg['pushed_within_days']} days"
    return None


@dataclass
class PRStats:
    outsider_merged_180d: int = 0
    outsider_closed_unmerged_180d: int = 0
    median_ttm_days: float | None = None
    docs_prs_merged: int = 0
    human_committers_90d: int = 0
    commits_90d: int = 0

    @property
    def outsider_merge_rate(self) -> float:
        total = self.outsider_merged_180d + self.outsider_closed_unmerged_180d
        return self.outsider_merged_180d / total if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self) | {"outsider_merge_rate": round(self.outsider_merge_rate, 2)}


def pr_stats(closed_pulls: list[dict[str, Any]], commits: list[dict[str, Any]], now: datetime) -> PRStats:
    stats = PRStats()
    since = now - timedelta(days=180)
    ttm: list[float] = []
    for pr in closed_pulls:
        user = pr.get("user") or {}
        if user.get("type") != "User" or _is_bot_login(user.get("login")):
            continue
        if pr.get("author_association") not in OUTSIDERS:
            continue
        closed = parse_time(pr.get("closed_at"))
        if closed is None or closed < since:
            continue
        merged = parse_time(pr.get("merged_at"))
        if merged is None:
            stats.outsider_closed_unmerged_180d += 1
            continue
        stats.outsider_merged_180d += 1
        created = parse_time(pr.get("created_at"))
        if created:
            ttm.append((merged - created).total_seconds() / 86400)
        text = f"{pr.get('title', '')} {(pr.get('head') or {}).get('ref', '')}".lower()
        if "doc" in text or "readme" in text or "openapi" in text or "swagger" in text:
            stats.docs_prs_merged += 1
    if ttm:
        stats.median_ttm_days = round(statistics.median(ttm), 1)

    authors: set[str] = set()
    for commit in commits:
        login = (commit.get("author") or {}).get("login")
        if _is_bot_login(login):
            continue
        identity = login or ((commit.get("commit") or {}).get("author") or {}).get("email")
        if identity and "[bot]" not in identity:
            authors.add(identity.lower())
            stats.commits_90d += 1
    stats.human_committers_90d = len(authors)
    return stats


def gate_activity(stats: PRStats, cfg: dict[str, Any]) -> str | None:
    if stats.human_committers_90d < cfg["min_human_committers_90d"]:
        return f"fewer than {cfg['min_human_committers_90d']} human committers in 90 days"
    if stats.outsider_merged_180d < cfg["min_outsider_merged_prs_180d"]:
        return "no merged PRs from outside contributors in 180 days"
    return None


def health_score(stats: PRStats, has_contributing: bool) -> float:
    if stats.median_ttm_days is None:
        ttm_score = 0.0
    else:
        ttm_score = min(1.0, max(0.0, (60 - stats.median_ttm_days) / (60 - 7)))
    score = (
        0.35 * min(1.0, stats.outsider_merged_180d / 5)
        + 0.20 * stats.outsider_merge_rate
        + 0.15 * ttm_score
        + 0.20 * min(1.0, stats.human_committers_90d / 5)
        + 0.10 * (1.0 if has_contributing else 0.0)
    )
    return round(score, 3)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
