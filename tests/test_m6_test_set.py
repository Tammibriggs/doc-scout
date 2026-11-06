"""The M6 test set (docs/PLAN.md section 21, step 6a) stays well formed: the labels Gemma's new
questions are measured against. Nothing here calls a model or GitHub."""

import json
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "m6"
RANK = {"A": 0, "B": 1, "C": 2}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_every_listed_help_request_is_labeled():
    issues = load("help_requests.json")["issues"]
    assert len(issues) == 25 and len({(i["repo"], i["number"]) for i in issues}) == 25
    for issue in issues:
        assert issue["label"] in RANK and issue["labeled_by"] in ("you", "first pass") and issue["reason"]
        assert issue["state"] in ("open", "closed", "deleted") and len(issue["text"]) <= 1500
        assert issue["title"] and (issue["text"] or issue["state"] == "deleted")


def test_the_counts_the_plan_quotes():
    # Per pick, its best help request: 5 ask for the work DocScout found, 8 for other API-docs work,
    # 10 aren't about API docs (plan section 21, as labeled on 6 Nov).
    best = {}
    for issue in load("help_requests.json")["issues"]:
        best[issue["repo"]] = min(best.get(issue["repo"], "C"), issue["label"], key=RANK.get)
    counts = {label: sum(1 for v in best.values() if v == label) for label in RANK}
    assert len(best) == 23 and counts == {"A": 5, "B": 8, "C": 10}
    bounty = {i["repo"] for i in load("help_requests.json")["issues"] if i["bounty"]}
    assert bounty == {"EarnQuestOne/stellar_Earn", "Emmy123222/Stellar-MarketPay-", "Agora-Events/agora"}
