import csv
import random

from conftest import iso

from docscout.find.discover import draw_sample, evaluate, write_sample
from docscout.measure.evaluate import evaluate_csv, format_report
from docscout.find.github import RateLimited
from docscout.find.sources import Candidate

GOOD_REPO = {
    "full_name": "org/app",
    "description": "Self-hosted bookmark manager with a REST API",
    "topics": ["self-hosted"],
    "archived": False,
    "fork": False,
    "license": {"spdx_id": "MIT"},
    "stargazers_count": 300,
    "pushed_at": iso(3),
    "created_at": iso(900),
    "default_branch": "main",
    "language": "Go",
}


class FakeGitHub:
    """Stands in for GitHub; records which endpoints were used."""

    def __init__(self, repo=GOOD_REPO, outsiders=3, committers=("a", "b", "c")):
        self.repo = repo
        self.outsiders = outsiders
        self.committers = committers
        self.used: list[str] = []

    def get_repo(self, name):
        self.used.append("repo")
        return dict(self.repo, full_name=name)

    def list_closed_pulls(self, name):
        self.used.append("pulls")
        return [
            {"user": {"login": f"u{i}", "type": "User"}, "author_association": "CONTRIBUTOR",
             "created_at": iso(12), "closed_at": iso(10), "merged_at": iso(10), "title": "x", "head": {"ref": "x"}}
            for i in range(self.outsiders)
        ]  # fmt: skip

    def list_commits(self, name, since):
        self.used.append("commits")
        return [{"author": {"login": c}, "commit": {"author": {"email": f"{c}@x"}}} for c in self.committers]

    def get_tree(self, name, ref):
        self.used.append("tree")
        return [{"path": "docker-compose.yml", "type": "blob", "size": 5}, {"path": "CONTRIBUTING.md", "type": "blob", "size": 5}], False

    def get_readme(self, name):
        self.used.append("readme")
        return "GET /api/bookmarks\nPOST /api/bookmarks\nGET /api/tags"


def test_healthy_app_passes_every_gate(cfg, now):
    gh = FakeGitHub()
    ev = evaluate(gh, Candidate("org/app", "awesome_selfhosted", {"full_name": "org/app", "description": "Bookmarks"}, prior=0.2), cfg, now)
    assert ev.rejected is None
    assert ev.classification.project_type == "serves_api"
    assert ev.health and ev.health > 0.5
    assert gh.used == ["repo", "pulls", "commits", "tree", "readme"]


def test_solo_repo_rejected_before_tree_is_fetched(cfg, now):
    gh = FakeGitHub(outsiders=0, committers=("only-me",))
    ev = evaluate(gh, Candidate("org/app", "repo_search", GOOD_REPO), cfg, now)
    assert ev.rejected and "committers" in ev.rejected
    assert "tree" not in gh.used and "repo" not in gh.used  # search results already had full metadata


def test_obvious_tooling_rejected_without_any_api_call(cfg, now):
    gh = FakeGitHub()
    meta = dict(GOOD_REPO, description="OpenAPI code generator and validator SDK", topics=["codegen", "generator"])
    ev = evaluate(gh, Candidate("org/gen", "repo_search", meta), cfg, now)
    assert ev.rejected.startswith("prefilter")
    assert gh.used == []


def test_rate_limit_keeps_partial_sample(cfg, now, monkeypatch):
    import docscout.find.discover as discover

    def fake_source(name, gh, cfg, rng, today, api_types, policy=None):
        yield Candidate("org/one", name, dict(GOOD_REPO))
        raise RateLimited("search", 3600)

    monkeypatch.setattr(discover, "source_candidates", fake_source)
    sample = draw_sample(FakeGitHub(), cfg, ["repo_search"], 10, rng=random.Random(1), now=now)
    assert [e.candidate.full_name for e in sample.passed] == ["org/one"]
    assert sample.stopped_early and "rate limit" in sample.stopped_early


def test_eval_computes_precision_per_source(cfg, now, tmp_path):
    gh = FakeGitHub()
    ev = evaluate(gh, Candidate("org/app", "repo_search", GOOD_REPO), cfg, now)
    path = tmp_path / "sample.csv"
    write_sample(path, [ev])
    rows = list(csv.DictReader(open(path)))
    rows[0]["label"] = "serves_api"
    rows.append(dict(rows[0], full_name="org/b", label="api_tooling"))
    rows.append(dict(rows[0], full_name="org/c", label="", source="help_requested"))
    rows.append(dict(rows[0], full_name="org/d", label="nonsense"))
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    report = evaluate_csv(path)
    assert report.overall.labeled == 2
    assert report.overall.precision == 0.5
    assert report.invalid_labels == ["org/d: 'nonsense'"]
    text = format_report(report)
    assert "NOT YET" in text and "repo_search" in text


def help_wanted_issue():
    return {"html_url": "https://github.com/org/app/issues/7", "number": 7, "title": "Document the REST endpoints",
            "labels": ["documentation", "help wanted"], "author_association": "OWNER", "outreach": ["help wanted"]}  # fmt: skip


def test_maintainer_asking_for_help_loosens_the_activity_gate(cfg, now):
    # A solo maintainer with no outside PRs yet is rejected normally...
    solo = FakeGitHub(outsiders=0, committers=("only-me",))
    ev = evaluate(solo, Candidate("org/app", "repo_search", GOOD_REPO), cfg, now)
    assert ev.rejected and "committers" in ev.rejected

    # ...but passes when they've labeled a docs issue "help wanted".
    solo = FakeGitHub(outsiders=0, committers=("only-me",))
    cand = Candidate("org/app", "help_requested", GOOD_REPO, issues=[help_wanted_issue()])
    ev = evaluate(solo, cand, cfg, now)
    assert ev.rejected is None
    assert "maintainers asked for REST API docs help" in ev.classification.reasons


def test_help_request_never_bypasses_the_metadata_gate(cfg, now):
    archived = dict(GOOD_REPO, archived=True)
    cand = Candidate("org/app", "help_requested", archived, issues=[help_wanted_issue()])
    assert evaluate(FakeGitHub(), cand, cfg, now).rejected == "archived"
    unlicensed = dict(GOOD_REPO, license=None)
    cand = Candidate("org/app", "help_requested", unlicensed, issues=[help_wanted_issue()])
    assert evaluate(FakeGitHub(), cand, cfg, now).rejected == "no license"


def test_issue_from_outsider_without_outreach_label_keeps_the_strict_gate(cfg, now):
    issue = help_wanted_issue() | {"labels": ["docs"], "author_association": "NONE", "outreach": []}
    cand = Candidate("org/app", "help_requested", GOOD_REPO, issues=[issue])
    ev = evaluate(FakeGitHub(outsiders=0, committers=("only-me",)), cand, cfg, now)
    assert ev.rejected and "committers" in ev.rejected


def test_a_failing_repo_is_skipped_and_sampling_continues(cfg, now, monkeypatch):
    import docscout.find.discover as discover
    from docscout.find.github import NotFound

    class FlakyGitHub(FakeGitHub):
        def list_closed_pulls(self, name):
            if name == "org/broken":
                raise NotFound(404, "Not Found")
            return super().list_closed_pulls(name)

    def fake_source(name, gh, cfg, rng, today, api_types, policy=None):
        yield Candidate("org/broken", name, dict(GOOD_REPO))
        yield Candidate("org/fine", name, dict(GOOD_REPO))

    monkeypatch.setattr(discover, "source_candidates", fake_source)
    sample = draw_sample(FlakyGitHub(), cfg, ["repo_search"], 10, rng=random.Random(1), now=now)
    assert [e.candidate.full_name for e in sample.passed] == ["org/fine"]
    assert sample.rejected[0].rejected.startswith("error: GitHub API error 404")
    assert sample.summaries[0].rejections == {"error": 1}
    assert sample.stopped_early is None


def test_ctrl_c_keeps_what_was_gathered(cfg, now, monkeypatch):
    import docscout.find.discover as discover

    def fake_source(name, gh, cfg, rng, today, api_types, policy=None):
        yield Candidate("org/one", name, dict(GOOD_REPO))
        raise KeyboardInterrupt

    monkeypatch.setattr(discover, "source_candidates", fake_source)
    sample = draw_sample(FakeGitHub(), cfg, ["repo_search"], 10, rng=random.Random(1), now=now)
    assert [e.candidate.full_name for e in sample.passed] == ["org/one"]
    assert sample.stopped_early == "interrupted (Ctrl+C)"


def test_curated_repo_outside_the_star_range_costs_no_api_calls(cfg, now):
    gh = FakeGitHub()
    seed = {"full_name": "org/huge", "description": "Self-hosted tracker", "stargazers_count": 29455}
    ev = evaluate(gh, Candidate("org/huge", "awesome_selfhosted", seed, prior=0.2), cfg, now)
    assert ev.rejected == "29455 stars is outside your project sizes"
    assert gh.used == []


def test_spam_visible_only_in_full_metadata_is_still_caught(cfg, now):
    class SpamGitHub(FakeGitHub):
        def get_repo(self, name):
            self.used.append("repo")
            return dict(GOOD_REPO, full_name=name, created_at=iso(10), topics=[f"t{i}" for i in range(18)])

    gh = SpamGitHub()
    ev = evaluate(gh, Candidate("org/new", "help_requested", {"full_name": "org/new"}), cfg, now)
    assert ev.rejected.startswith("spam: new repo with 18 topics")
    assert gh.used == ["repo"]
