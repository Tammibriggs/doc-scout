"""M6 step 6d: on the website, open picks stay listed and are kept true. Every run looks at every
listed pick and acts on what changed; the first run of the day is the main one, the others only
look. No test reaches GitHub or a model."""

import random
import re
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import AgreeingModel, iso
from test_help_requests import details_with, issue, save
from test_report_pipeline import RunGitHub, fake_sources
from test_review import TYPES

from docscout.hosted.picks import open_picks
from docscout.llm.base import HelpAnswer
from docscout.run import keep_open, pipeline, watch
from docscout.run.db import Store, StoredFinding
from docscout.settings.config import Config, load_defaults

GOOD = (Path(__file__).parent / "fixtures" / "specs" / "good.yaml").read_bytes()


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("DOCSCOUT_GITHUB_TOKEN", "test-token")
    values = load_defaults()
    values["report"]["dir"] = str(tmp_path / "reports")
    values["report"]["min_effort_units"] = 1  # the sample spec has 4 operations
    return Config(values=values, path=None, secrets_path=tmp_path / "secrets.env")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "docscout.db")
    yield s
    s.close()


def node(name, *, docs="d1", archived=False, pushed_days=1, prs=(0, None), issues=None):
    """What the look's GraphQL answer says about one repo."""
    n = {"nameWithOwner": name, "isArchived": archived, "pushedAt": iso(pushed_days), "defaultBranchRef": {"target": {"oid": "h" * 40}},
         "pullRequests": {"totalCount": prs[0], "nodes": [{"updatedAt": prs[1]}] if prs[1] else []}, "docs": {"oid": docs}}  # fmt: skip
    for number, (state, updated, comments) in (issues or {}).items():
        n[f"i{number}"] = {"state": state, "updatedAt": updated, "comments": {"totalCount": comments}}
    return n


class Looking(RunGitHub):
    """RunGitHub, plus the look: ``states`` maps a repo to its answer (None: gone; missing: all quiet)."""

    def __init__(self, states=None, spec=None):
        super().__init__()
        self.states, self.spec, self.looks, self.repos_fetched = dict(states or {}), spec, 0, 0

    def graphql_batch(self, query):
        self.looks += 1
        data, missing = {}, set()
        for alias, owner, name in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', query):
            full = f"{owner}/{name}"
            answer = self.states[full] if full in self.states else node(full)
            if answer is None:
                missing.add(alias)
            else:
                data[alias] = answer
        return data, missing

    def get_repo(self, name):
        self.repos_fetched += 1
        return super().get_repo(name)

    def get_file(self, name, path, ref=None, max_bytes=None):
        if self.spec is not None and path == "api/openapi.yaml":
            return self.spec
        return super().get_file(name, path, ref, max_bytes)


def reported(cfg, store, now, monkeypatch, *names):
    """Run DocScout once, laptop-style, so ``names`` are reported as they would be."""
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources(*names))
    pipeline.run(RunGitHub(), cfg, store, now, limit=10, sources=["repo_search"], rng=random.Random(1))
    return {f.full_name: f for f in store.reported_since(now - timedelta(days=1))}


def step(gh, store, cfg, now, caps=None, model=None):
    model = model or AgreeingModel()
    return keep_open.step(gh, store, cfg, now, lambda: model, TYPES, caps or keep_open.caps_for(cfg, daily=True))


# ---------------------------------------------------------------------- the look


def test_one_look_answers_for_many_picks_and_says_what_changed(now):
    f = StoredFinding("org/app", 50, {"gap": {"location": "api/openapi.yaml"}, "issues": [{"number": 12}]}, 1)
    gone = StoredFinding("org/gone", 40, {"gap": {}}, 1)
    gh = Looking({"org/app": node("Org/App", prs=(2, iso(1)), issues={12: ("OPEN", iso(2), 3)}), "org/gone": None})
    states = watch.look(gh, [f, gone])
    assert states["org/gone"] is None and gh.looks == 1
    assert states["org/app"]["name"] == "Org/App" and states["org/app"]["docs"] == "d1" and states["org/app"]["prs"][0] == 2
    assert states["org/app"]["issues"]["12"][0] == "OPEN"
    assert watch.changed(None, states["org/app"]) == {"docs", "prs", "issue 12"}  # the first look: everything
    later = {**states["org/app"], "docs": "d2"}
    assert watch.changed(states["org/app"], states["org/app"]) == set() and watch.changed(states["org/app"], later) == {"docs"}


def test_a_look_github_cant_answer_is_split_and_unanswered_picks_wait(cfg, store, now, monkeypatch):
    from docscout.find.github import GitHubError

    class Busy(Looking):  # GitHub answers 502 to batches of more than 4 repos (6 Nov: once, for 60)
        def graphql_batch(self, query):
            if query.count(": repository(") > self.most:
                raise GitHubError(502, "gave up after repeated failures")
            return super().graphql_batch(query)

    picks = [StoredFinding(f"org/app{i}", 50, {"gap": {}}, 1) for i in range(8)]
    gh = Busy()
    gh.most = 4
    assert len(watch.look(gh, picks, batch=8)) == 8 and gh.looks == 2  # 8 failed; 4 and 4 answered
    gh.most = 0
    assert watch.look(gh, picks, batch=8) == {}  # not one answer: none of them is gone
    reported(cfg, store, now, monkeypatch, "org/spec-app")
    out = step(gh, store, cfg, now + timedelta(hours=6))
    assert out.waiting == 1 and out.left == [] and store.repo("org/spec-app")["status"] == "reported"


# ---------------------------------------------------------------------- acting on it


def test_the_first_look_checks_a_pick_again_and_lists_it_and_the_next_costs_nothing(cfg, store, now, monkeypatch):
    reported(cfg, store, now, monkeypatch, "org/spec-app")
    gh = Looking()
    out = step(gh, store, cfg, now + timedelta(hours=6))
    assert (out.rechecked, out.claims_checked, out.left) == (1, 1, [])
    f = store.latest_finding("org/spec-app")
    assert f.details["watch"]["listed"] and f.details["watch"]["docs"] == "d1" and f.details["history"][-1]["work"] == 4
    assert [g["check"] for g in f.details["gap"]["findings"]][:2] == ["description", "parameters"]  # measured under the 6 Nov rules
    again = Looking()
    out = step(again, store, cfg, now + timedelta(hours=12))
    assert (out.rechecked, out.claims_checked) == (0, 0) and again.looks == 1 and again.repos_fetched == 0  # nothing changed


def test_picks_that_are_gone_archived_quiet_or_renamed(cfg, store, now, monkeypatch):
    reported(cfg, store, now, monkeypatch, "org/spec-app", "org/spec-app-2", "org/spec-app-3", "org/spec-app-4")
    gh = Looking({"org/spec-app": None, "org/spec-app-2": node("org/spec-app-2", archived=True),
                  "org/spec-app-3": node("org/spec-app-3", pushed_days=90), "org/spec-app-4": node("org/spec-app-renamed")})  # fmt: skip
    out = step(gh, store, cfg, now + timedelta(hours=6))
    assert store.repo("org/spec-app")["status"] == "ignored" and "deleted or made private" in store.repo("org/spec-app")["status_reason"]
    assert (store.repo("org/spec-app-2")["status"], store.repo("org/spec-app-2")["status_reason"]) == ("new", "failed the health checks: archived")
    assert store.repo("org/spec-app-3")["status_reason"] == "failed the health checks: no push in 60 days"
    assert out.renamed == [("org/spec-app-4", "org/spec-app-renamed")] and store.repo("org/spec-app-renamed")["status"] == "reported"
    assert [f.full_name for f in store.reported_since(now - timedelta(days=1))] == ["org/spec-app-renamed"]
    assert store.pending_findings(now + timedelta(hours=6), 0, 10) == []  # those that left don't come back as new picks


def test_a_pick_whose_docs_got_fixed_leaves_and_returns_to_the_pool(cfg, store, now, monkeypatch):
    reported(cfg, store, now, monkeypatch, "org/spec-app")
    step(Looking(), store, cfg, now + timedelta(hours=6))
    cfg.values["report"]["min_effort_units"] = 2
    fixed = Looking({"org/spec-app": node("org/spec-app", docs="d2")}, spec=GOOD)  # someone documented it
    out = step(fixed, store, cfg, now + timedelta(hours=12))
    assert out.left and out.left[0][1].startswith("docs fixed")
    repo = store.repo("org/spec-app")
    assert repo["status"] == "new" and repo["last_checked"] == (now + timedelta(hours=12)).isoformat(timespec="seconds")  # checked again in 90 days


def test_a_closed_help_request_takes_off_a_pick_listed_only_for_it(cfg, store, now):
    asks = {**issue(12, "Document the API"), "help": {"verdict": "this_work", "verified": True}}
    d = details_with([asks], kind="elsewhere", check_manually=["Project website: app.example"], findings=())
    save(store, now, "org/elsewhere", d)
    f = store.latest_finding("org/elsewhere")
    store.set_review(f.finding_id, "accepted", f.score, f.details)
    store.set_status("org/elsewhere", "reported", now)
    out = step(Looking({"org/elsewhere": node("org/elsewhere", issues={12: ("CLOSED", iso(0), 4)})}), store, cfg, now + timedelta(hours=1))
    assert out.left == [("org/elsewhere", "its docs may be elsewhere, and no help request asks for API docs work")]


def test_a_help_request_stored_without_its_text_is_read_before_gemma_is_asked(cfg, store, now):
    # writerslogic/warm #10, 8 Nov: judged from its title alone ("Node.js API reference with usage
    # examples"), it counted as a request for the REST spec's examples; its text is about a library.
    title_only = {"number": 10, "title": "Node.js API reference with usage examples", "labels": ["documentation"], "outreach": ["good first issue"],
                  "html_url": "https://github.com/org/app/issues/10", "help": {"verdict": "this_work", "verified": True, "signature": "from-the-title"}}  # fmt: skip
    save(store, now, "org/app", details_with([title_only]))
    f = store.latest_finding("org/app")
    store.set_review(f.finding_id, "accepted", f.score, f.details)
    store.set_status("org/app", "reported", now)

    class Reading:
        name, texts = "openai_compatible:gemma-4-31b-it", []

        def help_request(self, ctx):
            self.texts.append(ctx.text)
            return HelpAnswer(verdict="other_api_docs", quote="Node.js API reference", reason="a library's functions")

        def unload(self):
            pass

        def close(self):
            pass

    model = Reading()
    cfg.values["llm"]["provider"] = "openai_compatible"  # as on Render: no local-memory check
    step(Looking({"org/app": node("org/app", issues={10: ("OPEN", iso(3), 0)})}), store, cfg, now + timedelta(hours=1), model=model)
    assert model.texts == ["The endpoints need descriptions and examples."]  # the issue's text, fetched first
    stored = store.latest_finding("org/app").details["issues"][0]
    assert stored["text"] and stored["help"]["verdict"] == "other_api_docs"


def test_caps_leave_the_rest_for_the_next_run_free_picks_first(cfg, store, now, monkeypatch):
    reported(cfg, store, now, monkeypatch, "org/spec-app", "org/spec-app-2", "org/spec-app-3")
    best = max(store.reported_since(now - timedelta(days=1)), key=lambda f: f.score).full_name
    out = step(Looking(), store, cfg, now + timedelta(hours=6), caps=keep_open.Caps(rechecks=1, claims=5, gemma=5))
    assert out.rechecked == 1 and out.waiting == 2
    assert store.latest_finding(best).details["watch"]["rechecked"]  # the best of the week first: free visitors see it


def test_notes_quoting_old_numbers_are_rewritten(cfg, store, now, monkeypatch):
    found = reported(cfg, store, now, monkeypatch, "org/spec-app")["org/spec-app"]
    d = found.details
    d["gap"]["effort_units"] = 20  # found when 20 operations needed work; 4 do now
    store.update_details(found.run_id, "org/spec-app", d)
    model = AgreeingModel()
    out = step(Looking(), store, cfg, now + timedelta(hours=6), model=model)
    review = store.latest_finding("org/spec-app").details["review"]
    assert out.rewritten == 1 and review["rewritten"] and "stale_notes" not in review and model.reviewed == ["org/spec-app"]


# ---------------------------------------------------------------------- the list on the website


def test_every_open_pick_is_listed_and_the_free_three_are_the_best_this_week(store, now):
    def add(name, score, days_ago, *, listed=True, claimed_out=False):
        run = store.start_run(now - timedelta(days=days_ago))
        store.save_repo(name, now)
        checks = {"claimed": ["x"] if claimed_out else [], "claim_checked": True, "claimed_out": claimed_out}
        details = {"gap": {"kind": "spec", "score": 60, "findings": [], "effort_units": 20}, "checks": checks, "claims": {}, "watch": {"listed": listed}}
        store.save_finding(run, name, now, api_type="rest", kind="spec", gap=60, score=score, effort="M", details=details)
        store.set_status(name, "reported", now - timedelta(days=days_ago))

    add("org/old-best", 90, 30)
    add("org/old-unchecked", 95, 30, listed=False)  # not through its first checks yet: waits
    add("org/week-a", 60, 1)
    add("org/week-taken", 99, 2, claimed_out=True)
    add("org/old-ok", 50, 20)
    picks = open_picks(store, now, 5)
    assert [p["full_name"] for p in picks] == ["org/old-best", "org/week-a", "org/old-ok", "org/week-taken"]
    assert [p["full_name"] for p in picks if p["free"]] == ["org/old-best", "org/week-a", "org/old-ok"]  # the week has 1 startable: topped up


def test_visitors_see_the_free_picks_and_when_each_was_checked(now):
    from test_hosted import FakeAtlas, client, sample_picks

    picks = sample_picks(5)
    for i, p in enumerate(picks):
        p.update(free=i in (1, 3), found="5 Nov", checked=(now - timedelta(hours=3)).isoformat())
    text = client(FakeAtlas(picks), now=now.timestamp()).get("/").text
    assert "org/app2<" in text and "org/app4<" in text and "org/app1<" not in text  # the free ones, not the first ones
    assert text.count("Found 5 Nov · checked 3 hours ago") == 2
    assert "Open picks" in text and "every 6 hours" in text and "Comment on the issue, or open one, before you start" in text


# ---------------------------------------------------------------------- the job, every 6 hours


def test_the_first_run_of_the_day_is_the_main_one_and_the_others_look(now, monkeypatch):
    from test_hosted import atlas_with_db, report

    from docscout import cli
    from docscout.find import health
    from docscout.hosted import job
    from docscout.hosted.atlas_store import AtlasStore

    clock = [now]
    monkeypatch.setattr(health, "utcnow", lambda: clock[0])
    atlas = atlas_with_db()
    seen = []

    def fake_main(argv):
        seen.append(argv[2])
        report(AtlasStore(atlas.db), clock[0], f"org/app{len(seen)}")  # a finished run, as `docscout run` or `look` leaves
        return 0

    monkeypatch.setattr(cli, "main", fake_main)
    assert job.main(atlas=atlas) == 0 and seen == ["run"]
    clock[0] = now + timedelta(hours=6)
    assert job.main(atlas=atlas) == 0 and seen == ["run", "look"]  # the day's main run is done
    clock[0] = now + timedelta(days=1)
    assert job.main(atlas=atlas) == 0 and seen == ["run", "look", "run"]  # a new day
    store = AtlasStore(atlas.db)
    store.start_run(clock[0] - timedelta(hours=1))  # a run still going
    clock[0] = clock[0] + timedelta(minutes=5)
    assert job.main(atlas=atlas) == 0 and seen == ["run", "look", "run"]  # stops at once


def test_a_dry_run_names_its_own_database_everywhere(monkeypatch):
    from docscout.hosted import atlas_database

    assert atlas_database() == "docscout"
    monkeypatch.setenv("DOCSCOUT_ATLAS_DATABASE", "docscout_dryrun")
    assert atlas_database() == "docscout_dryrun"  # read by the job, the commands it starts and the website
