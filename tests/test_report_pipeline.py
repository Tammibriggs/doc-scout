import random
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from conftest import AgreeingModel
from conftest import iso
from test_discover_eval import GOOD_REPO, FakeGitHub

from docscout.run import pipeline
from docscout.settings.config import Config, load_defaults
from docscout.run.db import Store
from docscout.find.github import AuthError, RateLimited
from docscout.run.report import write
from docscout.run.sanitize import code, link, text
from docscout.analyze.scoring import issue_bonus, opportunity_score
from docscout.find.sources import Candidate

SPEC = (Path(__file__).parent / "fixtures" / "specs" / "bare.yaml").read_bytes()


@pytest.fixture
def cfg(tmp_path):
    values = load_defaults()
    values["report"]["dir"] = str(tmp_path / "reports")
    values["report"]["min_effort_units"] = 1  # the sample spec has 4 operations; the size cutoff has its own test
    return Config(values=values, path=None, secrets_path=tmp_path / "secrets.env")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "docscout.db")
    yield s
    s.close()


# ---------------------------------------------------------------------- scoring and safety


def test_score_formula_and_bonuses():
    issues = [{"outreach": ["help wanted"], "labels": ["documentation", "help wanted"]}]
    assert issue_bonus(issues) == 15
    assert issue_bonus([{"outreach": ["good first issue"], "labels": []}]) == 5
    s = opportunity_score(80, 0.5, 0.9, issues, language_match=True, language_bonus=5)
    assert s.total == round(80 * 0.75 * 0.9 + 15 + 5, 1)
    assert s.breakdown() == "gap 80 × health 0.50 × type 0.90 + help requested 15 + your language 5"
    assert opportunity_score(100, 1, 1, issues, True).total == 100  # capped


def test_docs_published_as_pages_raise_the_score_and_docker_is_not_a_docs_label():
    s = opportunity_score(40, 1, 1, [], language_match=False, published_bonus=10)
    assert s.total == 50 and s.breakdown() == "gap 40 × health 1.00 × type 1.00 + docs published 10"
    assert issue_bonus([{"outreach": [], "labels": ["docker"]}]) == 0
    assert issue_bonus([{"outreach": [], "labels": ["type: docs"]}]) == 5


def test_untrusted_text_cannot_inject_markdown_links_or_controls():
    evil = "Click [here](https://evil.example)\n# Heading <img src=x onerror=alert(1)> \u202e\x1b[31m"
    out = text(evil)
    assert re.search(r"(?<!\\)[<>\[\]()#`]", out) is None  # every Markdown/HTML special character is escaped
    assert "\n" not in out
    assert "\u202e" not in out and "\x1b" not in out
    assert code("a`b") == "`a'b`"
    assert link("x", "https://evil.example/a") == "x"
    assert link("x", "https://github.com/org/app/issues/12") == "[x](https://github.com/org/app/issues/12)"
    assert link("x", "https://github.com/org/app/blob/HEAD/a b.yaml") == "x"  # unencoded space: refused


def test_report_files_are_never_overwritten(tmp_path, now):
    first = write(tmp_path, now, "one")
    second = write(tmp_path, now, "two")
    assert (first.name, second.name) == ("2026-10-12.md", "2026-10-12_2.md")
    assert first.read_text() == "one" and (tmp_path / "latest.md").read_text() == "two"


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="needs time.tzset (Unix)")
def test_report_file_is_named_after_your_day_not_utcs(tmp_path, monkeypatch):
    # Seen 15 Oct: the daily run at 00:15 in Lagos wrote 2026-10-14_3.md.
    monkeypatch.setenv("TZ", "Africa/Lagos")  # UTC+1, no daylight saving time
    time.tzset()
    try:
        just_after_midnight = datetime(2026, 10, 14, 23, 15, tzinfo=timezone.utc)
        assert write(tmp_path, just_after_midnight, "x").name == "2026-10-15.md"
    finally:
        monkeypatch.undo()
        time.tzset()


def test_run_with_limit_0_only_reviews(tmp_path, monkeypatch):
    # `--limit 0` used to fall back to the daily budget and start a full search.
    from contextlib import nullcontext

    from docscout import cli

    class Called(Exception):
        pass

    def fake_run(gh, cfg, store, now, *, limit, **kw):
        raise Called(limit)

    monkeypatch.setattr(cli, "store_path", lambda: tmp_path / "docscout.db")
    monkeypatch.setattr(cli, "lock_path", lambda: tmp_path / "run.lock")
    monkeypatch.setattr(cli, "_github", lambda cfg: nullcontext())
    monkeypatch.setattr(pipeline, "run", fake_run)
    config = str(tmp_path / "config.toml")
    with pytest.raises(Called) as called:
        cli.main(["--config", config, "run", "--limit", "0"])
    assert called.value.args == (0,)
    with pytest.raises(Called) as called:
        cli.main(["--config", config, "run"])
    assert called.value.args == (int(load_defaults()["discovery"]["daily_repo_budget"]),)


# ---------------------------------------------------------------------- storage


def test_store_skips_handled_and_recent_repos(store, now):
    assert store.skip_reason("org/a", now, 90) is None
    store.save_repo("Org/A", now, source="repo_search", rejected="no license")
    assert store.skip_reason("org/a", now, 90) == "checked recently"
    assert store.skip_reason("org/a", now + timedelta(days=91), 90) is None
    store.set_status("org/b", "ignored", now, "not REST")
    assert store.skip_reason("ORG/B", now + timedelta(days=500), 90) == "ignored"
    with pytest.raises(ValueError):
        store.save_repo("org/c", now, **{"status = 'done' --": 1})


def test_database_upgrades_keep_earlier_history(tmp_path, now):
    import sqlite3

    from docscout.run.db import MIGRATIONS

    path = tmp_path / "old.db"
    old = sqlite3.connect(path)  # a database from before the daily schedule existed
    old.executescript(MIGRATIONS[0])
    old.execute("PRAGMA user_version = 1")
    old.execute("INSERT INTO runs (started, status, analyzed) VALUES ('2026-10-12T09:00:00+00:00', 'ok', 12)")
    old.commit()
    old.close()
    store = Store(path)
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == len(MIGRATIONS)
    run = store.recent_runs(1)[0]
    assert (run["analyzed"], run["started_by"], run["run_limit"]) == (12, "you", None)
    store.close()


# ---------------------------------------------------------------------- full run


class RunGitHub(FakeGitHub):
    """Fake GitHub for full runs: repos named org/spec-app* have a bare spec; others have no API docs."""

    def __init__(self):
        super().__init__()
        self.calls = {"core": 0}

    def get_tree(self, name, ref):
        self.used.append("tree")
        if name.startswith("org/spec-app"):
            return [{"path": "api/openapi.yaml", "type": "blob", "size": len(SPEC)}, {"path": "CONTRIBUTING.md", "type": "blob", "size": 5}], False
        return [{"path": "Dockerfile", "type": "blob", "size": 5}], False

    def get_readme(self, name):
        return "# App\\nSelf-hosted app."

    def list_commits(self, name, since):
        commits = super().list_commits(name, since)
        return [dict(c, sha="0123456789abcdef0123456789abcdef01234567") for c in commits]

    def get_file(self, name, path, ref=None, max_bytes=None):
        return SPEC if path == "api/openapi.yaml" else None

    def list_owner_repos(self, owner):
        return []

    def list_open_pulls(self, name):
        return [{"number": 7, "title": "docs: describe the checks endpoints", "head": {"ref": "docs-checks"}}] if name == "org/claimed" else []

    def list_issue_comments(self, name, number):
        return []


def fake_sources(*names):
    def source(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        for full_name in names:
            yield Candidate(full_name, name, dict(GOOD_REPO, full_name=full_name, description="Self-hosted uptime app with a REST API"))

    return source


def test_full_run_writes_a_safe_report_and_remembers_it(cfg, store, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app", "org/plain-app"))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"], rng=random.Random(1))
    assert result.status == "ok"
    by_name = {f.full_name: f for f in result.findings}
    # No spec or endpoints at all: not reported, since that rests only on not finding docs.
    assert set(by_name) == {"org/spec-app"}
    report = result.report_path.read_text()
    assert "### 1. [org/spec-app](https://github.com/org/spec-app) · score" in report
    assert "**REST API spec with gaps:** [`api/openapi.yaml`]" in report
    assert "org/plain-app" not in report
    assert "\n\n> Self-hosted uptime app with a REST API\n\n" in report  # its own paragraph
    assert "[`api/openapi.yaml`](https://github.com/org/spec-app/blob/0123456789abcdef0123456789abcdef01234567/api/openapi.yaml)" in report
    assert "4/4 operations have no summary or description (e.g. `GET /checks`, `POST /checks`, +2 more)" in report
    assert "Looking for: REST API docs · any language · small, medium, large projects" in report
    assert store.repo("org/spec-app")["status"] == "reported"

    # A second run the same day skips everything already checked and writes no file.
    again = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"], rng=random.Random(1))
    assert again.status == "empty" and again.report_path is None and again.summary.evaluated == 0


def test_gaps_too_small_to_be_worth_a_contribution_are_skipped(cfg, store, now, monkeypatch):
    cfg.values["report"]["min_effort_units"] = 5  # the default; the sample spec's 4 operations all need work
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"], rng=random.Random(1))
    assert result.status == "empty" and result.findings == []
    assert store.repo("org/spec-app")["status"] == "new"  # checked again later, in case the API grows


def test_done_projects_drop_out_and_reported_ones_stay_listed(cfg, store, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"])
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app-2"))
    later = now + timedelta(days=1)
    result = pipeline.run(RunGitHub(), cfg, store, later, limit=10, sources=["repo_search"])
    assert [f.full_name for f in result.still_open] == ["org/spec-app"]
    assert "## Still open from earlier" in result.report_path.read_text()
    store.set_status("org/spec-app", "done", later)
    assert "org/spec-app" not in [f.full_name for f in store.still_open(999, 5)]


def test_earlier_picks_are_checked_again_for_claims_once_a_day(cfg, store, now, monkeypatch):
    class Claimed(RunGitHub):  # after org/spec-app was reported, someone opened a docs PR
        def list_open_pulls(self, name):
            return [{"number": 9, "title": "docs: describe every endpoint", "head": {"ref": "docs"}}] if name == "org/spec-app" else []

    def claims(name):
        return next(f for f in store.reported_since(now - timedelta(days=7)) if f.full_name == name).details["checks"]["claimed"]

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    first = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"])
    assert first.summary.claims_rechecked == 0 and claims("org/spec-app") == []  # checked when reported
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app-2"))
    later = now + timedelta(days=1)
    second = pipeline.run(Claimed(), cfg, store, later, limit=10, sources=["repo_search"])
    assert second.summary.claims_rechecked == 1
    assert claims("org/spec-app") == ['Open PR #9 "docs: describe every endpoint": it documents the API endpoints']
    report = second.report_path.read_text()
    assert "## Still open from earlier" in report and "⚠️ Open PR" in report and "earlier picks checked again for claims" in report
    model = AgreeingModel()
    earlier = store.reported_since(now - timedelta(days=7))
    assert pipeline.recheck_claims(Claimed(), store, earlier, later + timedelta(hours=2), model) == 0  # once a day
    assert pipeline.recheck_claims(Claimed(), store, earlier, later + timedelta(days=1), model) == 2
    assert model.claim_checks == []  # nothing changed on GitHub, so the model wasn't asked again
    assert pipeline.recheck_claims(RunGitHub(), store, store.reported_since(now - timedelta(days=7)), later + timedelta(days=2), model) == 2
    assert claims("org/spec-app") == []  # the PR was closed: nothing left to read, so no question needed


def test_claims_stay_unchecked_when_the_model_cannot_answer(cfg, store, now, monkeypatch):
    from docscout.llm import LLMError

    class Busy(AgreeingModel):
        def claims(self, ctx):
            raise LLMError("503 after retries, and the fallback model too")

    class WithPR(RunGitHub):
        def list_open_pulls(self, name):
            return [{"number": 9, "title": "docs: describe every endpoint", "head": {"ref": "docs"}}]

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    result = pipeline.run(WithPR(), cfg, store, now, limit=10, sources=["repo_search"], reviewer=Busy)
    checks = result.findings[0].details["checks"]
    assert checks["claim_checked"] is False and "claims_checked" not in result.findings[0].details  # asked again next run
    report = result.report_path.read_text()
    assert "✅ not claimed" not in report and "❔ not checked yet for anyone already on it" in report


def test_rate_limit_keeps_results_and_auth_failure_is_raised(cfg, store, now, monkeypatch):
    class Limited(RunGitHub):
        def list_closed_pulls(self, name):
            if name == "org/spec-app-2":
                raise RateLimited("core", 3600)
            return super().list_closed_pulls(name)

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app", "org/spec-app-2"))
    result = pipeline.run(Limited(), cfg, store, now, limit=10, sources=["repo_search"])
    assert result.status == "partial" and "rate limit" in result.summary.stopped_early
    assert [f.full_name for f in result.findings] == ["org/spec-app"]

    class Expired(RunGitHub):
        def get_repo(self, name):
            raise AuthError(401, "Bad credentials")

        def list_closed_pulls(self, name):
            raise AuthError(401, "Bad credentials")

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/other"))
    with pytest.raises(AuthError):
        pipeline.run(Expired(), cfg, store, now, limit=10, sources=["repo_search"])
    assert store.conn.execute("SELECT status FROM runs ORDER BY id DESC").fetchone()[0] == "failed"


def test_limit_counts_only_repos_that_cost_api_calls(cfg, store, now, monkeypatch):
    def source(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        yield Candidate("org/gen", name, dict(GOOD_REPO, description="OpenAPI code generator and validator SDK", topics=["codegen"]))
        yield Candidate("org/spec-app", name, dict(GOOD_REPO, full_name="org/spec-app"))

    monkeypatch.setattr(pipeline, "source_candidates", source)
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=1, sources=["repo_search"])
    assert result.summary.evaluated == 2 and result.summary.analyzed == 1
    assert store.repo("org/gen")["rejected"].startswith("prefilter")


def test_pushed_date_is_shown_relative_to_the_run(cfg, store, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"])
    assert GOOD_REPO["pushed_at"] == iso(3)
    assert "pushed 3 days ago" in result.report_path.read_text()


def test_rejections_that_cost_api_calls_count_toward_the_limit(cfg, store, now, monkeypatch):
    class Solo(RunGitHub):
        def list_commits(self, name, since):
            return [{"author": {"login": "only-me"}, "commit": {"author": {"email": "me@x"}}, "sha": "a" * 40}]

    def source(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        yield Candidate("org/huge", name, {"full_name": "org/huge", "stargazers_count": 90000})  # free
        yield Candidate("org/solo", name, dict(GOOD_REPO, full_name="org/solo"))  # costs calls, then rejected
        yield Candidate("org/never", name, dict(GOOD_REPO, full_name="org/never"))

    monkeypatch.setattr(pipeline, "source_candidates", source)
    result = pipeline.run(Solo(), cfg, store, now, limit=1, sources=["repo_search"])
    assert result.summary.evaluated == 2 and result.summary.analyzed == 1
    assert store.repo("org/never") is None


def test_before_you_start_checks_appear_in_the_report(cfg, store, now, monkeypatch):
    class WithContributing(RunGitHub):
        def get_tree(self, name, ref):
            tree, truncated = super().get_tree("org/spec-app", ref)
            return tree + [{"path": "docker-compose.yml", "type": "blob", "size": 5}], truncated

        def get_file(self, name, path, ref=None, max_bytes=None):
            if path == "CONTRIBUTING.md":
                return b"Thanks! All contributors must sign our Contributor License Agreement before we can merge."
            return super().get_file(name, path, ref, max_bytes)

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/claimed", "org/spec-app"))
    result = pipeline.run(WithContributing(), cfg, store, now, limit=10, sources=["repo_search"])
    report = result.report_path.read_text()
    assert '**Before you start:** ⚠️ Open PR \\#7 "docs: describe the checks endpoints": it documents the API endpoints' in report
    assert "✅ not claimed · ⚠️ CLA required" in report
    assert "in CONTRIBUTING.md\\) · local setup: easy \\(docker-compose\\)" in report


def test_checks_quote_requirements_and_ignore_unrelated_ai_mentions():
    from docscout.analyze.checks import find_requirements

    assert find_requirements("We use AI to rank search results.", "README") == []
    found = find_requirements("Pull requests generated by AI tools will be closed without review. Sign off with Signed-off-by.", "CONTRIBUTING.md")
    assert found[0].startswith('Commits need sign-off (DCO) ("')
    assert found[1].startswith('AI-contribution policy ("Pull requests generated by AI tools will be closed without review."')
    # free-llm-api-hub (17 Oct): its contributors badge was quoted as an AI policy.
    badge = "[![Contributors](https://img.shields.io/github/contributors/org/free-llm-api-hub)](https://github.com/org/free-llm-api-hub/graphs/contributors)"
    assert find_requirements(badge + "\nContributions to free-llm-api-hub are welcome.", "README") == []
    assert find_requirements("[![CLA assistant](https://cla-assistant.io/readme/badge/org/app)](https://cla-assistant.io/org/app)", "README")[0].startswith("CLA required")


def test_a_failing_source_is_skipped_and_noted(cfg, store, now, monkeypatch):
    from docscout.find.sources import SourceUnavailable

    def source(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        if name == "awesome_selfhosted":
            raise SourceUnavailable("couldn't download the curated list")
            yield  # pragma: no cover
        yield Candidate("org/spec-app", name, dict(GOOD_REPO, full_name="org/spec-app"))

    monkeypatch.setattr(pipeline, "source_candidates", source)
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["awesome_selfhosted", "repo_search"])
    assert result.status == "ok" and [f.full_name for f in result.findings] == ["org/spec-app"]
    assert "Skipped the awesome\\_selfhosted source this run" in result.report_path.read_text()


def test_docs_that_may_live_elsewhere_are_reported_only_when_maintainers_asked(cfg, store, now, monkeypatch):
    class WithWebsite(RunGitHub):
        def get_tree(self, name, ref):
            return [{"path": "Dockerfile", "type": "blob", "size": 5}], False

        def get_readme(self, name):
            return "# App\nSelf-hosted app with a REST API. Full docs at [our docs](https://docs.withsite.example)."

    def source(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        for full_name, issues in (("org/withsite", []), ("org/withsite-help", [{"number": 3, "title": "Document the API", "outreach": ["help wanted"], "labels": ["docs"], "html_url": "https://github.com/org/withsite-help/issues/3"}])):
            yield Candidate(full_name, name, dict(GOOD_REPO, full_name=full_name, homepage="https://withsite.example"), issues=issues)

    monkeypatch.setattr(pipeline, "source_candidates", source)
    result = pipeline.run(WithWebsite(), cfg, store, now, limit=10, sources=["help_requested"])
    assert [f.full_name for f in result.findings] == ["org/withsite-help"]
    assert result.findings[0].details["gap"]["check_manually"]
