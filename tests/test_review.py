"""Stage M2: the model decides which projects are reported, within limits set by code."""

import re
from datetime import timedelta

import pytest
from conftest import iso
from test_daily import Clock, Notifications, run_if_due
from test_report_pipeline import RunGitHub, fake_sources

from docscout import apitypes, daily, pipeline, review
from docscout.analyze.gaps import Finding, Gap
from docscout.config import Config, load_defaults
from docscout.db import Store
from docscout.errors import ConfigError
from docscout.llm import LLMError, LLMUnavailable, Review, make_client, memory
from docscout.scoring import opportunity_score


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("DOCSCOUT_GITHUB_TOKEN", "test-token")
    values = load_defaults()
    values["report"]["dir"] = str(tmp_path / "reports")
    return Config(values=values, path=None, secrets_path=tmp_path / "secrets.env")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "docscout.db")
    yield s
    s.close()


TYPES = {t.key: t for t in apitypes.enabled_types({"enabled": ["rest"]})}


class Scripted:
    """A model with a fixed verdict per repo: (project_type, confidence), or an exception to raise."""

    name = "ollama:gemma4:e2b"

    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls, self.thinking, self.unloaded = [], [], False

    def review(self, ctx, readme_chars=1500, think=False):
        self.calls.append(ctx.full_name)
        self.thinking.append(think)
        verdict = self.verdicts[ctx.full_name]
        if isinstance(verdict, Exception):
            raise verdict
        kind, confidence = verdict
        return Review(project_type=kind, api_style="rest", confidence=confidence, evidence="GET /api/items", why="w", first_steps=["s"])

    def unload(self):
        self.unloaded = True

    def close(self):
        pass


def add_finding(store, now, name, *, code_confidence, gap=60):
    """A finding as a run saves it, waiting for the model's review."""
    run_id = store.start_run(now)
    store.save_repo(name, now, source="repo_search")
    g = Gap(kind="spec", score=gap, summary="OpenAPI 3.0.3, 10 operations, hand-written", findings=[Finding("7/10 operations have no description")])
    potential = opportunity_score(gap, 0.8, max(code_confidence, 0.8), [], False)
    details = {
        "api_type": "rest", "api_label": "REST", "code_confidence": code_confidence, "readme_excerpt": "# App\nGET /api/items",
        "gap": g.as_dict(), "score": potential.as_dict(), "breakdown": potential.breakdown(), "effort": "S",
        "repo": {"stars": 300, "language": "Go", "language_match": False, "pushed_at": iso(3), "description": "An app", "topics": []},
        "issues": [], "head_sha": "a" * 40,
    }  # fmt: skip
    store.save_finding(run_id, name, now, api_type="rest", kind="spec", gap=gap, score=potential.total, effort="S", details=details)


def review_now(store, cfg, now, model, limit=13):
    return review.review_waiting(store, cfg, now, TYPES, limit=limit, reviewer=lambda: model)


# ---------------------------------------------------------------------- the model decides


def test_the_model_lets_borderline_projects_in_and_keeps_lookalikes_out(cfg, store, now):
    add_finding(store, now, "org/borderline", code_confidence=0.5)  # code alone would drop it
    add_finding(store, now, "org/lookalike", code_confidence=0.75)  # code alone would report it
    model = Scripted({"org/borderline": ("serves_api", 0.9), "org/lookalike": ("api_tooling", 0.9)})
    out = review_now(store, cfg, now, model)
    assert (out.reviewed, out.accepted, out.rejected, out.waiting) == (2, 1, 1, 0)
    reported = store.pending_findings(now, 25, 10)
    assert [f.full_name for f in reported] == ["org/borderline"]
    r = reported[0].details["review"]
    assert (r["code_confidence"], r["final_confidence"], r["agrees"]) == (0.5, 0.8, True)  # raised, but only to the cap
    assert "type 0.80" in reported[0].details["breakdown"]
    assert model.unloaded


def test_most_promising_first_and_the_rest_wait(cfg, store, now):
    add_finding(store, now, "org/small-gap", code_confidence=0.7, gap=40)
    add_finding(store, now, "org/big-gap", code_confidence=0.7, gap=90)
    model = Scripted({"org/big-gap": ("serves_api", 0.9), "org/small-gap": ("serves_api", 0.9)})
    out = review_now(store, cfg, now, model, limit=1)
    assert model.calls == ["org/big-gap"] and out.waiting == 1


def test_nothing_unreviewed_is_reported_and_low_memory_holds_projects(cfg, store, now, monkeypatch):
    add_finding(store, now, "org/app", code_confidence=0.9)
    monkeypatch.setattr(memory, "available_bytes", lambda: int(1.2e9))
    out = review_now(store, cfg, now, None)  # the model is never opened
    assert out.skipped == "only 1.2 GB of memory is free and gemma4:e2b needs about 2.5 GB"
    assert out.waiting == 1 and store.pending_findings(now, 25, 10) == []


def test_a_model_that_isnt_running_holds_projects_and_says_how_to_fix_it(cfg, store, now):
    add_finding(store, now, "org/app", code_confidence=0.9)
    out = review_now(store, cfg, now, Scripted({"org/app": LLMUnavailable("Ollama isn't running. Start it with `ollama serve`")}))
    assert "ollama serve" in out.skipped and out.waiting == 1


def test_a_project_the_model_cant_answer_for_is_dropped_after_two_runs(cfg, store, now):
    add_finding(store, now, "org/odd", code_confidence=0.9)
    model = Scripted({"org/odd": LLMError("invalid review JSON")})
    assert review_now(store, cfg, now, model).waiting == 1
    assert review_now(store, cfg, now, model).waiting == 0
    assert store.pending_findings(now, 25, 10) == []


def test_thinking_only_where_the_code_is_unsure(cfg, store, now):
    cfg.values["llm"]["think"] = "borderline"
    add_finding(store, now, "org/borderline", code_confidence=0.5, gap=90)
    add_finding(store, now, "org/clear", code_confidence=0.75, gap=40)
    model = Scripted({"org/borderline": ("serves_api", 0.9), "org/clear": ("serves_api", 0.9)})
    review_now(store, cfg, now, model)
    assert model.thinking == [True, False]


def test_there_is_no_model_free_mode():
    with pytest.raises(ConfigError, match="needs a model"):
        make_client({"provider": "none", "model": "x", "base_url": "x"})


# ---------------------------------------------------------------------- in the run and the report


def test_the_report_shows_the_review_and_first_steps(cfg, store, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"])
    report = result.report_path.read_text()
    assert '**Gemma\'s review:** an app or service with its own REST API ("GET /api/checks") · type confidence' in report
    assert "**Why it matters (Gemma):** Its users integrate through the API." in report
    assert "**First steps (Gemma):**\n\n1. Describe POST /checks\n2. Add examples" in report
    assert "Gemma reviewed 1 (1 accepted)" in report


def test_model_text_cannot_inject_links_into_the_report(cfg, store, now, monkeypatch):
    class Injected(Scripted):
        def review(self, ctx, readme_chars=1500, think=False):
            return Review(project_type="serves_api", api_style="rest", confidence=1.0, evidence="x",
                          why="[Click here](https://evil.example) <img src=x>", first_steps=["# Heading"])  # fmt: skip

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"], reviewer=lambda: Injected({}))
    report = result.report_path.read_text()
    assert re.search(r"(?<!\\)\]\(https://evil", report) is None  # no live link
    assert re.search(r"(?<!\\)<img", report) is None  # no live HTML
    assert "\\[Click here\\]" in report and "1. \\# Heading" in report


def test_a_run_whose_reviews_were_skipped_reports_nothing_and_says_why(cfg, store, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    monkeypatch.setattr(memory, "available_bytes", lambda: int(1.0e9))
    result = pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"])
    assert result.report_path is None and result.review.waiting == 1
    assert any("1 project is waiting for Gemma's review" in n for n in result.summary.notes)
    # Later, with memory free: a run that only reviews (it checks no repos) reports it.
    monkeypatch.setattr(memory, "available_bytes", lambda: 8 * 10**9)
    later = pipeline.run(RunGitHub(), cfg, store, now + timedelta(hours=1), limit=0, sources=["repo_search"])
    assert [f.full_name for f in later.findings] == ["org/spec-app"] and later.summary.evaluated == 0


# ---------------------------------------------------------------------- the daily schedule


def test_held_projects_are_reviewed_at_a_later_check_once_memory_is_free(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    monkeypatch.setattr(memory, "available_bytes", lambda: int(1.0e9))
    notes, clock = Notifications(), Clock(now)
    run_if_due(cfg, store, tmp_path, clock, notes)
    assert notes[-1][0] == "DocScout is waiting for Gemma" and "1.0 GB of memory is free" in notes[-1][1]

    clock.advance(minutes=15)  # still not enough memory: no run starts, and nothing is shown
    run_if_due(cfg, store, tmp_path, clock, notes)
    assert len(store.recent_runs(5)) == 1 and len(notes) == 2
    assert "1 projects waiting for Gemma: only 1.0 GB" in daily.last_check(store)[1]

    monkeypatch.setattr(memory, "available_bytes", lambda: 8 * 10**9)
    clock.advance(minutes=15)
    run_if_due(cfg, store, tmp_path, clock, notes)
    assert [n[0] for n in notes[2:]] == ["DocScout is reviewing 1 project with Gemma", "DocScout found 1 new project"]
    assert notes[2][1] == "Your computer may be slower for about 1 minute."
    assert store.recent_runs(1)[0]["reviewed"] == 1


def test_a_model_blocked_for_two_days_asks_for_attention(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    monkeypatch.setattr(memory, "available_bytes", lambda: int(1.0e9))
    cfg.values["notifications"] = {"run_started": False, "run_finished": False}
    notes, clock = Notifications(), Clock(now)
    for _ in range(3):
        run_if_due(cfg, store, tmp_path, clock, notes)
        clock.advance(days=1)
    assert [n for n in notes if n[2]] == [
        ("DocScout needs attention", "Gemma hasn't been able to review projects for 2 days, so 1 are waiting: "
         "only 1.0 GB of memory is free and gemma4:e2b needs about 2.5 GB.", True)
    ]  # fmt: skip
