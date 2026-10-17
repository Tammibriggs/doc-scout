from conftest import iso

from docscout.find.health import PRStats, gate_activity, gate_metadata, health_score, pr_stats

HEALTH_CFG = {"star_ranges": [(20, 200), (200, 1000), (1000, 5000)], "pushed_within_days": 60, "min_human_committers_90d": 2, "min_outsider_merged_prs_180d": 1}


def pr(assoc, merged_days_ago=None, closed_days_ago=10, created_days_ago=14, login="alice", user_type="User", title="Fix bug", merged_by=None):
    return {
        "merged_by": {"login": merged_by} if merged_by else None,
        "user": {"login": login, "type": user_type},
        "author_association": assoc,
        "created_at": iso(created_days_ago),
        "closed_at": iso(closed_days_ago),
        "merged_at": iso(merged_days_ago) if merged_days_ago is not None else None,
        "title": title,
        "head": {"ref": "fix"},
    }


def commit(login=None, email=None):
    return {"author": {"login": login} if login else None, "commit": {"author": {"email": email or f"{login}@x.org"}}}


def test_outsiders_counted_insiders_and_bots_ignored(now):
    pulls = [
        pr("CONTRIBUTOR", merged_days_ago=10),
        pr("FIRST_TIME_CONTRIBUTOR", merged_days_ago=5, title="docs: describe endpoints"),
        pr("NONE"),  # closed without merging
        pr("COLLABORATOR", merged_days_ago=3),  # insider
        pr("MEMBER", merged_days_ago=3),  # insider
        pr("CONTRIBUTOR", merged_days_ago=3, login="dependabot[bot]", user_type="Bot"),
        pr("CONTRIBUTOR", merged_days_ago=200, closed_days_ago=200, created_days_ago=210),  # too old
    ]
    commits = [commit("alice"), commit("bob"), commit("alice"), commit("renovate[bot]"), commit(None, "carol@x.org")]
    stats = pr_stats(pulls, commits, now)
    assert stats.outsider_merged_180d == 2
    assert stats.outsider_closed_unmerged_180d == 1
    assert round(stats.outsider_merge_rate, 2) == 0.67
    assert stats.docs_prs_merged == 1
    assert stats.human_committers_90d == 3
    assert stats.median_ttm_days is not None


def test_people_who_merge_prs_are_not_outsiders_whatever_github_calls_them(now):
    # zowe/api-layer (17 Oct): maintainers with private org membership show as CONTRIBUTOR.
    pulls = [
        pr("CONTRIBUTOR", merged_days_ago=10, login="pablo", merged_by="richard"),
        pr("CONTRIBUTOR", merged_days_ago=9, login="richard", merged_by="Pablo"),  # both merge PRs here
        pr("CONTRIBUTOR", merged_days_ago=8, login="elijah", merged_by="pablo"),  # a real outsider
        pr("CONTRIBUTOR", merged_days_ago=7, login="zowe-robot", merged_by="pablo"),  # a bot on a user account
        pr("CONTRIBUTOR", merged_days_ago=6, login="abbot", merged_by="pablo"),  # a person whose name ends in "bot"
    ]
    stats = pr_stats(pulls, [], now)
    assert stats.outsider_merged_180d == 2


def test_metadata_gate(now):
    good = {"archived": False, "fork": False, "license": {"spdx_id": "MIT"}, "stargazers_count": 50, "pushed_at": iso(5)}
    assert gate_metadata(good, HEALTH_CFG, now) is None
    assert gate_metadata(good | {"license": None}, HEALTH_CFG, now) == "no license"
    assert gate_metadata(good | {"stargazers_count": 3}, HEALTH_CFG, now).startswith("fewer than")
    assert gate_metadata(good | {"stargazers_count": 9000}, HEALTH_CFG, now) == "9000 stars is outside your project sizes"
    gaps = HEALTH_CFG | {"star_ranges": [(20, 200), (1000, None)]}
    assert gate_metadata(good | {"stargazers_count": 500}, gaps, now) == "500 stars is outside your project sizes"
    assert gate_metadata(good | {"stargazers_count": 90000}, gaps, now) is None
    assert gate_metadata(good | {"pushed_at": iso(90)}, HEALTH_CFG, now).startswith("no push")
    assert gate_metadata(good | {"fork": True}, HEALTH_CFG, now) == "fork"


def test_activity_gate_rejects_solo_projects():
    solo = PRStats(outsider_merged_180d=0, human_committers_90d=1)
    assert gate_activity(solo, HEALTH_CFG) is not None
    healthy = PRStats(outsider_merged_180d=3, human_committers_90d=4)
    assert gate_activity(healthy, HEALTH_CFG) is None


def test_health_score_bounds():
    best = PRStats(outsider_merged_180d=10, outsider_closed_unmerged_180d=0, median_ttm_days=1, human_committers_90d=9)
    assert health_score(best, has_contributing=True) == 1.0
    assert health_score(PRStats(), has_contributing=False) == 0.0
