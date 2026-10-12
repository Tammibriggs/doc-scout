"""The opportunity score that ranks report items.

    score = gap × (0.5 + 0.5·health) × type_confidence + issue bonus + language bonus   (max 100)

Issue bonus: "help wanted" +10, "good first issue" +5, a docs label +5 (at most +15).
Language bonus: [scoring] language_bonus when the repo is in one of your languages.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

OUTREACH_BONUS = {"help wanted": 10, "good first issue": 5}
DOCS_LABEL_BONUS = 5
MAX_ISSUE_BONUS = 15


def issue_bonus(issues: list[dict[str, Any]]) -> int:
    outreach = {o for issue in issues for o in issue.get("outreach") or []}
    bonus = sum(OUTREACH_BONUS.get(o, 0) for o in outreach)
    if any("doc" in str(label).lower() for issue in issues for label in issue.get("labels") or []):
        bonus += DOCS_LABEL_BONUS
    return min(MAX_ISSUE_BONUS, bonus)


@dataclass
class Score:
    total: float
    gap: float
    health: float
    type_confidence: float
    issue_bonus: int = 0
    language_bonus: int = 0

    def breakdown(self) -> str:
        text = f"gap {self.gap:.0f} × health {self.health:.2f} × type {self.type_confidence:.2f}"
        if self.issue_bonus:
            text += f" + help requested {self.issue_bonus}"
        if self.language_bonus:
            text += f" + your language {self.language_bonus}"
        return text

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def opportunity_score(
    gap: float,
    health: float,
    type_confidence: float,
    issues: list[dict[str, Any]],
    language_match: bool | None,
    language_bonus: int = 5,
) -> Score:
    bonus_issues = issue_bonus(issues)
    bonus_language = language_bonus if language_match else 0
    base = gap * (0.5 + 0.5 * health) * type_confidence
    total = round(min(100.0, base + bonus_issues + bonus_language), 1)
    return Score(total, gap, health, type_confidence, bonus_issues, bonus_language)
