"""The picks from the last 7 days as plain data for the website.

Built from DocScout's own database after each run. Every string is cleaned as in the
reports (no control or bidirectional characters, one line, limited length), and the
website's templates escape it again as HTML. Links are kept only when they're GitHub URLs
DocScout builds and trusts; anything else becomes plain text.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from docscout.analyze.gaps import Gap, kind_label
from docscout.run.db import Store, StoredFinding
from docscout.llm.review import model_label
from docscout.run.sanitize import blob_url, clean, is_github_url, repo_url

WEEK = timedelta(days=7)
NEW_FOR = timedelta(days=1)  # picks reported this recently are labeled "New"
FREE_PICKS = 3
EFFORT = {"S": "Small job", "M": "Medium job", "L": "Big job"}
_EMOJI_CODE = re.compile(r":[a-z0-9_+-]{1,30}:")  # GitHub shows ":baby:" as an emoji; elsewhere it's noise


def _trusted(url: str) -> str | None:
    return url if is_github_url(url) else None


def _biggest(findings: list) -> Any:
    """The gap that covers the most operations or endpoints; the first one on a tie."""
    return max(findings, key=lambda f: len(f.examples) + f.more)


def pick(finding: StoredFinding, rank: int, now: datetime | None = None) -> dict[str, Any]:
    d = finding.details
    reported = datetime.fromisoformat(finding.reported).astimezone(timezone.utc) if finding.reported else None
    name = finding.full_name
    gap = Gap.from_dict(d.get("gap") or {"kind": "spec", "score": 0})
    review = d.get("review") or {}
    repo = d.get("repo") or {}
    checks = d.get("checks") or {}
    stats = d.get("stats") or {}
    findings = []
    for f in gap.findings[:6]:
        examples = ", ".join(clean(e, 80) for e in f.examples[:2])
        more = f" and {f.more} more" if f.more else ""
        findings.append(clean(f.text, 300) + (f" (e.g. {examples}{more})" if examples else ""))
    return {
        "rank": rank,
        "reported": reported.isoformat(timespec="seconds") if reported else None,  # sortable: always UTC
        "found": f"{reported.day} {reported:%b}" if reported else None,
        "new": bool(reported and now and now - reported < NEW_FOR),
        "full_name": clean(name, 140),
        "url": _trusted(repo_url(name)),
        "score": round(float(finding.score)),
        "stars": repo.get("stars"),
        "language": clean(repo.get("language") or "", 40) or None,
        "description": clean(_EMOJI_CODE.sub("", str(repo.get("description") or "")), 300) or None,
        "gap_heading": clean(kind_label(gap.kind, d.get("api_label", "API")), 80),
        "gap_summary": clean(gap.summary, 200),
        "gap_file": clean(gap.location, 200) if gap.location else None,
        "gap_file_url": _trusted(blob_url(name, d.get("head_sha"), gap.location)) if gap.location else None,
        "findings": findings,
        "headline": clean(_biggest(gap.findings).text, 160) if gap.findings else clean(gap.summary, 160),
        "effort": EFFORT.get(str(d.get("effort") or "")),
        "outside_prs": int(stats.get("outsider_merged_180d") or 0),
        "suggestion": clean(gap.suggestion, 400) or None,
        "published": [clean(p, 140) for p in gap.published[:3]],
        "check_manually": [clean(p, 140) for p in gap.check_manually[:3]],
        "model": model_label(str(review.get("model") or "")) if review else None,
        "why": clean(review.get("why") or "", 600) or None,
        "first_steps": [clean(s, 300) for s in (review.get("first_steps") or [])[:3]],
        "claimed": [clean(c, 140) for c in checks.get("claimed") or []],
        "requirements": [clean(r, 220) for r in checks.get("requirements") or []],
        "local_setup": clean(checks.get("local_setup") or "", 60) or None,
        "issues": [
            {"title": clean(f"#{i.get('number')} {i.get('title', '')}", 140), "url": _trusted(str(i.get("html_url", "")))}
            for i in (d.get("issues") or [])[:3]
        ],
    }


def _too_small(finding: StoredFinding, min_units: int) -> bool:
    units = (finding.details.get("gap") or {}).get("effort_units")
    return units is not None and units < min_units


def weekly_picks(store: Store, now: datetime, min_units: int = 0) -> list[dict[str, Any]]:
    """Every project reported in the last 7 days and still open, best first, leaving out gaps
    covering fewer than ``min_units`` operations or endpoints (``[report] min_effort_units``;
    the same rule a run applies, so projects reported before it came in drop out too)."""
    found = [f for f in store.reported_since(now - WEEK) if not _too_small(f, min_units)]
    return [pick(f, rank, now) for rank, f in enumerate(found, 1)]
