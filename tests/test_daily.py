"""Stage M3: daily runs without manual starts (run --if-due, lock, offline, alerts, schedule)."""

import os
import subprocess
import sys
from datetime import timedelta, timezone
from pathlib import Path

import httpx
import pytest
from test_discover_eval import GOOD_REPO
from test_report_pipeline import RunGitHub, fake_sources

from docscout.run import daily, lock, notify, pipeline
from docscout.settings.config import Config, load_defaults
from docscout.run.db import Store
from docscout.find.sources import Candidate, code_search, repo_search

UTC = timezone.utc


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("DOCSCOUT_GITHUB_TOKEN", "test-token")
    values = load_defaults()
    values["report"]["dir"] = str(tmp_path / "reports")
    values["report"]["min_effort_units"] = 1  # the sample spec has 4 operations; the size cutoff has its own test
    return Config(values=values, path=None, secrets_path=tmp_path / "secrets.env")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "docscout.db")
    yield s
    s.close()


class Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


class DailyGitHub(RunGitHub):
    def __init__(self, ping=200):
        super().__init__()
        self._ping = ping

    def ping(self, timeout=10.0):
        if isinstance(self._ping, Exception):
            raise self._ping
        return self._ping

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None


class Notifications(list):
    def __call__(self, title, body, urgent=False):
        self.append((title, body, urgent))
        return True


def run_if_due(cfg, store, tmp_path, clock, notes, gh=None):
    gh = gh or DailyGitHub()
    return daily.run_if_due(
        cfg, store, lock_path=tmp_path / "run.lock", github=lambda token: gh, notifier=notes, clock=clock, sources=["repo_search"], tz=UTC
    )


def add_run(store, when, *, status, analyzed, run_limit=60, started_by="schedule", resume_after=None, finished=None):
    run_id = store.start_run(when, run_limit=run_limit, started_by=started_by)
    store.finish_run(run_id, finished or when, status=status, analyzed=analyzed, new_items=0, api_calls=0, resume_after=resume_after)


# ---------------------------------------------------------------------- when a run is due


def test_a_day_is_done_when_its_budget_is_used_or_nothing_is_left(cfg, store, now):
    due = daily.check_due(store, cfg, now, UTC)
    assert due.due and due.remaining == 60 and due.reason == "today's run hasn't happened yet"

    add_run(store, now, status="partial", analyzed=20)
    due = daily.check_due(store, cfg, now, UTC)
    assert due.due and due.remaining == 40 and due.reason == "continuing today's run"

    add_run(store, now, status="ok", analyzed=40, run_limit=40)
    assert not daily.check_due(store, cfg, now, UTC).due
    assert daily.check_due(store, cfg, now + timedelta(days=1), UTC).remaining == 60  # a new day


def test_a_scheduled_run_that_ran_out_of_candidates_ends_the_day_but_a_short_manual_run_doesnt(cfg, store, now):
    add_run(store, now, status="ok", analyzed=5, run_limit=5, started_by="you")
    assert daily.check_due(store, cfg, now, UTC).remaining == 55
    add_run(store, now, status="empty", analyzed=10, run_limit=55)
    due = daily.check_due(store, cfg, now, UTC)
    assert not due.due and due.reason == "today's run is done; there were no more candidates"


def test_failures_and_rate_limits_wait_before_trying_again(cfg, store, now):
    add_run(store, now, status="failed", analyzed=3)
    due = daily.check_due(store, cfg, now + timedelta(minutes=15), UTC)
    assert not due.due and due.reason == "the last run failed; trying again after 13:00"
    assert daily.check_due(store, cfg, now + timedelta(minutes=61), UTC).due

    add_run(store, now + timedelta(hours=2), status="partial", analyzed=3, resume_after=now + timedelta(hours=2, minutes=40))
    due = daily.check_due(store, cfg, now + timedelta(hours=2, minutes=15), UTC)
    assert not due.due and due.reason == "waiting for GitHub's rate limit; continuing after 14:40"
    assert daily.check_due(store, cfg, now + timedelta(hours=2, minutes=45), UTC).due


def test_a_run_cut_short_again_and_again_stops_for_the_day(cfg, store, now):
    for _ in range(daily.MAX_SCHEDULED_RUNS_PER_DAY):
        add_run(store, now, status="partial", analyzed=1)
    due = daily.check_due(store, cfg, now, UTC)
    assert not due.due and due.reason.startswith("stopped for today after 8 tries")


def test_the_estimate_comes_from_earlier_runs(store, now):
    assert daily.estimated_minutes(store, 60) == 10  # no history yet
    add_run(store, now, status="ok", analyzed=30, finished=now + timedelta(minutes=3))  # 6 s per repo
    assert daily.estimated_minutes(store, 60) == 6
    assert daily.estimated_minutes(store, 5) == 1


# ---------------------------------------------------------------------- run --if-due


def test_offline_checks_do_nothing_and_leave_the_run_due(cfg, store, tmp_path, now):
    notes = Notifications()
    gh = DailyGitHub(ping=httpx.ConnectError("no network"))
    assert run_if_due(cfg, store, tmp_path, Clock(now), notes, gh) == 0
    assert notes == [] and store.recent_runs(5) == []
    assert daily.last_check(store)[1] == "offline; trying again in 15 minutes"
    assert daily.check_due(store, cfg, now, UTC).due


def test_due_run_notifies_when_it_starts_and_finishes_then_rests_until_tomorrow(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app", "org/plain-app"))
    notes, clock = Notifications(), Clock(now)
    assert run_if_due(cfg, store, tmp_path, clock, notes) == 0
    assert notes[0] == ("DocScout is checking projects", "Your computer may be slower for about 20 minutes.", False)  # 60 repos + 13 reviews
    assert notes[1][0] == "DocScout found 1 new project" and notes[1][1].endswith("reports/2026-10-12.md")
    assert store.recent_runs(1)[0]["started_by"] == "schedule"

    clock.advance(minutes=15)  # the sources had nothing more today
    assert run_if_due(cfg, store, tmp_path, clock, notes) == 0
    assert len(notes) == 2

    clock.advance(days=1)  # tomorrow: nothing new, so no report, but the finish is still announced
    assert run_if_due(cfg, store, tmp_path, clock, notes) == 0
    assert [n[0] for n in notes[2:]] == ["DocScout is checking projects", "DocScout is done"]
    assert notes[3][1] == "Nothing new today."


def test_start_and_finish_notifications_can_be_turned_off(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    cfg.values["notifications"] = {"run_started": False, "run_finished": False}
    notes = Notifications()
    assert run_if_due(cfg, store, tmp_path, Clock(now), notes) == 0
    assert notes == [] and store.recent_runs(1)[0]["new_items"] == 1


def test_token_problems_alert_once_a_day_and_no_run_starts(cfg, store, tmp_path, now, monkeypatch):
    notes, clock = Notifications(), Clock(now)
    assert run_if_due(cfg, store, tmp_path, clock, notes, DailyGitHub(ping=401)) == 1
    clock.advance(minutes=15)
    assert run_if_due(cfg, store, tmp_path, clock, notes, DailyGitHub(ping=401)) == 1
    assert notes == [("DocScout needs attention", daily.TOKEN_REJECTED, True)]
    assert store.recent_runs(5) == []
    clock.advance(days=1)
    run_if_due(cfg, store, tmp_path, clock, notes, DailyGitHub(ping=401))
    assert len(notes) == 2

    monkeypatch.delenv("DOCSCOUT_GITHUB_TOKEN")
    assert run_if_due(cfg, store, tmp_path, clock, notes) == 1
    assert notes[-1] == ("DocScout needs a GitHub token", daily.TOKEN_MISSING, True)


def test_three_failed_runs_in_a_row_ask_for_attention(cfg, store, tmp_path, now, monkeypatch):
    def broken(name, gh, cfg, rng, today, api_types, policy=None, **kwargs):
        raise RuntimeError("a bug")
        yield  # pragma: no cover

    monkeypatch.setattr(pipeline, "source_candidates", broken)
    cfg.values["notifications"]["run_started"] = False
    notes, clock = Notifications(), Clock(now)
    for _ in range(3):
        assert run_if_due(cfg, store, tmp_path, clock, notes) == 1
        clock.advance(minutes=61)  # failed runs wait an hour before the next try
    assert [n[0] for n in notes] == ["DocScout stopped because of an error"] * 3 + ["DocScout needs attention"]
    assert notes[-1][1] == "The last 3 runs failed. Run docscout status to see why." and notes[-1][2]


def test_a_cut_off_run_is_continued_and_its_findings_still_reported(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app"))
    real_render = pipeline.render
    monkeypatch.setattr(pipeline, "render", lambda *a: (_ for _ in ()).throw(SystemExit("power cut")))
    with pytest.raises(SystemExit):
        pipeline.run(RunGitHub(), cfg, store, now, limit=60, sources=["repo_search"], started_by="schedule")
    cut = store.recent_runs(1)[0]
    assert cut["status"] == "running" and cut["analyzed"] == 1  # progress was saved as it went

    monkeypatch.setattr(pipeline, "render", real_render)
    notes, clock = Notifications(), Clock(now + timedelta(minutes=30))
    assert run_if_due(cfg, store, tmp_path, clock, notes) == 0
    runs = store.recent_runs(2)
    assert runs[1]["status"] == "partial" and "stopped before finishing" in runs[1]["error"]
    assert notes[0][0] == "DocScout is continuing today's check"
    assert notes[1][0] == "DocScout found 1 new project"
    assert "org/spec-app" in (tmp_path / "reports" / "latest.md").read_text()


def test_losing_the_connection_mid_run_pauses_without_skipping_repos(cfg, store, tmp_path, now, monkeypatch):
    class Drops(DailyGitHub):
        def list_closed_pulls(self, name):
            if name == "org/second":
                raise httpx.ConnectError("network is unreachable")
            return super().list_closed_pulls(name)

    monkeypatch.setattr(pipeline, "source_candidates", fake_sources("org/spec-app", "org/second", "org/third"))
    notes = Notifications()
    assert run_if_due(cfg, store, tmp_path, Clock(now), notes, Drops()) == 0
    assert store.recent_runs(1)[0]["status"] == "partial"
    assert store.repo("org/second") is None and store.repo("org/third") is None  # checked when it's back
    assert notes[1][0] == "DocScout found 1 new project"
    assert notes[1][1].endswith("Lost the internet connection. The rest continues when you're back online.")
    assert daily.check_due(store, cfg, now + timedelta(minutes=15), UTC).due


def test_days_without_anything_new_lead_to_one_hint(cfg, store, tmp_path, now, monkeypatch):
    monkeypatch.setattr(pipeline, "source_candidates", fake_sources())
    cfg.values["notifications"] = {"run_started": False, "run_finished": False}
    notes, clock = Notifications(), Clock(now)
    for _ in range(9):
        run_if_due(cfg, store, tmp_path, clock, notes)
        clock.advance(days=1)
    assert [n[0] for n in notes] == ["DocScout hasn't found anything new for 7 days"]


def test_status_explains_the_day_in_plain_words(cfg, store, now):
    add_run(store, now, status="partial", analyzed=20)
    text = daily.status_report(store, cfg, now, running=False, tz=UTC)
    assert text.startswith("Today: 20 of 60 repos checked. The next check continues today's run.")
    assert "12 Oct 12:00  schedule  partial   20 repos   0 new" in text
    unscheduled = daily.status_report(store, cfg, now, running=False, scheduled=False, tz=UTC)
    assert unscheduled.startswith("Today: 20 of 60 repos checked. Today's run stopped early; docscout run continues it.")
    store.start_run(now)  # a run row left behind by a killed process
    assert "The last run was cut off; the next check continues it." in daily.status_report(store, cfg, now, running=False, tz=UTC)


# ---------------------------------------------------------------------- the lock


def test_only_one_run_at_a_time(tmp_path, cfg, store, now):
    path = tmp_path / "run.lock"
    with lock.hold(path):
        assert lock.is_held(path)
        with pytest.raises(lock.Busy):
            with lock.hold(path):
                pass
        notes = Notifications()
        assert run_if_due(cfg, store, tmp_path, Clock(now), notes) == 0  # quietly leaves it to the other run
        assert store.recent_runs(1) == []
    assert not lock.is_held(path)


@pytest.mark.skipif(os.name == "nt", reason="kill -9 is tested on Unix; Windows comes in M5")
def test_a_killed_run_never_blocks_the_next_one(tmp_path):
    path = tmp_path / "run.lock"
    holder = "import sys, time\nfrom pathlib import Path\nfrom docscout.run import lock\nheld = lock.hold(Path(sys.argv[1]))\nheld.__enter__()\nprint('held', flush=True)\ntime.sleep(60)\n"
    proc = subprocess.Popen([sys.executable, "-c", holder, str(path)], stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout.readline().strip() == "held"
        assert lock.is_held(path)
    finally:
        proc.kill()  # SIGKILL: no cleanup code runs
        proc.wait()
    assert not lock.is_held(path)


# ---------------------------------------------------------------------- the search cursor


class SearchGitHub:
    def __init__(self, results):
        self.results = results  # query word -> repo names
        self.searched = []

    def search_repos(self, query, *, page=1, per_page=100, sort="updated"):
        word = query.split()[0]
        self.searched.append((word, page, sort))
        names = self.results[word]
        items = names[(page - 1) * per_page : page * per_page]
        return len(names), [{"full_name": n} for n in items]


def test_repo_search_moves_on_through_pages_and_slices_across_days(store, now, monkeypatch):
    monkeypatch.setattr(repo_search, "PER_PAGE", 2)
    gh = SearchGitHub({"topic:a": ["a1", "a2", "a3", "a4", "a5"], "topic:b": ["b1"]})
    slices = repo_search.all_slices(["topic:a", "topic:b"], [[20, 200]])

    def day(n, take):
        stream = repo_search.sweep(gh, slices, store, per_run=1, pushed_within_days=60, today=now.date(), now=now + timedelta(days=n))
        return [c.full_name for _, c in zip(range(take), stream)]

    assert day(0, 3) == ["a1", "a2", "a3"]  # page 1 handed out in full, page 2 started
    assert store.slice_position(slices[0].key)[:2] == (2, 0)
    assert day(1, 5) == ["b1"]  # the least recently used slice comes next
    assert day(2, 9) == ["a3", "a4", "a5"]  # continues from page 2, then starts over
    assert store.slice_position(slices[0].key)[:2] == (1, 1)
    assert {sort for _, _, sort in gh.searched} == {"stars"}  # stable pages from one day to the next


def test_daily_runs_use_the_cursor(cfg, store, now, monkeypatch):
    from docscout.analyze import apitypes
    from docscout.find.discover import source_candidates

    seen = []
    monkeypatch.setattr(repo_search, "sweep", lambda *a, **k: iter(seen.append(k["per_run"]) or []))
    monkeypatch.setattr(code_search, "sweep", lambda gh, names, bands, cursor, **k: iter(seen.append((len(names), len(bands), k["per_run"])) or []))
    for source in ("repo_search", "code_search"):
        list(source_candidates(source, None, cfg, None, now.date(), apitypes.enabled_types(cfg["api_types"]), cursor=store, now=now))
    assert seen == [4, (4, 4, 8)]  # 4 file names in 4 size bands to start from, 8 bands a run


class CodeSearchGitHub:
    """Code search over files of known sizes, plus the batched GraphQL look-up of each page's repos."""

    def __init__(self, files, gone=(), fail_batches=False):
        self.files, self.gone, self.fail_batches = files, set(gone), fail_batches  # file name -> [(repo, size)]
        self.searched = []

    def search_code(self, query, *, page=1, per_page=100):
        import re

        name = re.search(r"filename:(\S+)", query).group(1)
        low, high = map(int, re.search(r"size:(\d+)\.\.(\d+)$", query).groups())
        self.searched.append((name, low, high, page))
        repos = [repo for repo, size in self.files[name] if low <= size <= high]
        items = repos[(page - 1) * per_page : page * per_page]
        return len(repos), [{"repository": {"full_name": n.lstrip("~"), "fork": n.startswith("~")}} for n in items]

    def graphql_batch(self, query):
        import re

        from docscout.find.github import GitHubError

        if self.fail_batches:
            raise GitHubError(502, "Bad gateway")
        data, missing = {}, set()
        for alias, owner, name in re.findall(r'(r\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\)', query):
            if f"{owner}/{name}" in self.gone:
                data[alias] = None
                missing.add(alias)
            else:
                data[alias] = {"stargazerCount": 42, "isArchived": False, "isFork": False, "pushedAt": "2026-11-01T00:00:00Z", "licenseInfo": {"spdxId": "MIT"}}
        return data, missing


def bands(store):
    import json

    return [tuple(b) for b in json.loads(store.get_state(code_search.STATE_KEY))["bands"]]


def test_code_search_size_bands():
    assert code_search.size_range("<5000") == (0, 4999)
    assert code_search.size_range("5000..20000") == (5000, 20000)
    assert code_search.size_range(">100000") == (100001, 393216)  # nothing bigger is indexed
    assert code_search.start_bands(["a.yaml"], ["<10"])[0].query == "filename:a.yaml size:0..9"
    start = code_search.start_bands(["a.yaml", "b.json"], ["<10", "10..20"])
    assert [(b.filename, b.low) for b in start] == [("a.yaml", 10), ("b.json", 10), ("a.yaml", 0), ("b.json", 0)]  # largest first


def test_code_search_works_through_its_bands_in_turn(store, now, monkeypatch):
    monkeypatch.setattr(code_search, "PER_PAGE", 2)
    gh = CodeSearchGitHub({"a.yaml": [("o/a1", 5), ("~o/fork", 5), ("o/a2", 5), ("o/gone", 5), ("o/a3", 5)], "b.yaml": [("o/b1", 5)]}, gone={"o/gone"})

    def run(n, take):
        stream = code_search.sweep(gh, ["a.yaml", "b.yaml"], ["<10"], store, per_run=1, now=now + timedelta(days=n))
        return [c for _, c in zip(range(take), stream)]

    first = run(0, 2)
    assert [c.full_name for c in first] == ["o/a1", "o/a2"]  # the fork is skipped; page 2 started
    assert first[0].meta["stargazers_count"] == 42 and first[0].meta["license"] == {"spdx_id": "MIT"}  # in REST's field names
    assert store.slice_position("code:filename:a.yaml size:0..9")[:2] == (2, 0)
    assert [c.full_name for c in run(1, 9)] == ["o/a2", "o/a3"]  # a band being read stays first (the gone repo is dropped)
    assert bands(store) == [("b.yaml", 0, 9), ("a.yaml", 0, 9)] and store.slice_position("code:filename:a.yaml size:0..9")[:2] == (1, 1)
    assert [c.full_name for c in run(2, 9)] == ["o/b1"]  # a finished band goes to the back
    assert [c.full_name for c in run(3, 1)] == ["o/a1"]  # and starts over


def test_a_band_with_more_results_than_a_search_returns_is_split_until_each_part_can_be_read(store, now, monkeypatch):
    monkeypatch.setattr(code_search, "PER_PAGE", 2)
    monkeypatch.setattr(code_search, "MAX_RESULTS", 4)
    gh = CodeSearchGitHub({"a.yaml": [(f"o/r{size}", size) for size in range(7)]})

    def run(per_run=1):
        return [c.full_name for c in code_search.sweep(gh, ["a.yaml"], ["<8"], store, per_run=per_run, now=now)]

    assert run() == ["o/r0", "o/r1", "o/r2", "o/r3"]  # 7 results in 0..7: split, and the lower half read
    assert bands(store) == [("a.yaml", 4, 7), ("a.yaml", 0, 3)]  # the upper half waits its turn
    assert run() == ["o/r4", "o/r5", "o/r6"]
    gh.files["a.yaml"] += [(f"o/s{k}", 6) for k in range(4)]  # a band grows past what a search returns
    assert run(per_run=2) == ["o/r0", "o/r1", "o/r2", "o/r3", "o/r4", "o/r5"]
    assert bands(store)[-2:] == [("a.yaml", 0, 3), ("a.yaml", 4, 5)] and bands(store)[0] == ("a.yaml", 6, 7)
    list(code_search.sweep(gh, ["a.yaml"], ["<16"], store, per_run=1, now=now))  # new settings start the queue again
    assert bands(store) == [("a.yaml", 4, 7), ("a.yaml", 8, 15), ("a.yaml", 0, 3)]  # 0..15 split twice


def test_code_search_carries_on_when_github_cant_answer_the_look_up(store, now):
    gh = CodeSearchGitHub({"a.yaml": [("o/a1", 5), ("o/a2", 5)]}, fail_batches=True)
    found = list(code_search.sweep(gh, ["a.yaml"], ["<10"], store, per_run=1, now=now))
    assert [c.full_name for c in found] == ["o/a1", "o/a2"]
    assert "stargazers_count" not in found[0].meta  # so the run fetches each repo, as before



# ---------------------------------------------------------------------- systemd


def test_systemd_units_quote_odd_paths(tmp_path):
    from docscout.run.scheduler.linux import _exec_start, quote, service_text

    assert quote("/usr/bin/python3") == "/usr/bin/python3"
    assert quote("/home/a b/50%$x") == '"/home/a b/50%%$$x"'
    cmd = ["/home/a b/.venv/bin/python", "-m", "docscout", "--config", "/home/a b/my 100%.toml", "run", "--if-due"]
    assert _exec_start(service_text(cmd)) == cmd


class FakeSystemctl:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def __call__(self, cmd):
        self.calls.append(cmd)
        if self.fail and self.fail in cmd:
            return subprocess.CompletedProcess(cmd, 1, "", "Failed to connect to bus: No medium found")
        out = {"is-enabled": "enabled", "is-active": "active"}.get(cmd[2], "")
        if "NextElapseUSecRealtime" in cmd:
            out = "Tue 2026-10-13 11:00:00 WAT"
        return subprocess.CompletedProcess(cmd, 0, out + "\n", "")


def test_schedule_install_status_and_uninstall(tmp_path):
    from docscout.run.scheduler import SchedulerError, command
    from docscout.run.scheduler.linux import Systemd

    systemctl = FakeSystemctl()
    sched = Systemd(runner=systemctl, directory=tmp_path / "units")
    cmd = command()
    assert cmd[0] == sys.executable and cmd[-2:] == ["run", "--if-due"]

    preview = sched.install(cmd, dry_run=True)
    assert not (tmp_path / "units").exists() and systemctl.calls == []
    assert "Would run: systemctl --user enable --now docscout.timer" in preview

    sched.install(cmd)
    timer = (tmp_path / "units" / "docscout.timer").read_text()
    assert "OnCalendar=*:0/15" in timer and "Persistent=true" in timer and "OnStartupSec=2min" in timer
    assert "Nice=10" in (tmp_path / "units" / "docscout.service").read_text()
    assert systemctl.calls[-1] == ["systemctl", "--user", "enable", "--now", "docscout.timer"]

    status = sched.status(cmd)
    assert status.running and status.next_check == "Tue 2026-10-13 11:00:00 WAT" and status.problems == []
    other_name = [str(Path(sys.executable).with_name("python-other")), *cmd[1:]]
    assert sched.status(other_name).problems == []  # python vs python3 in the same environment
    moved = sched.status(["/gone/python", "-m", "docscout", "run", "--if-due"])
    assert "a different DocScout installation" in moved.problems[0]

    sched.uninstall()
    assert not (tmp_path / "units" / "docscout.timer").exists()
    assert sched.status(cmd).installed is False

    with pytest.raises(SchedulerError, match="cron"):
        Systemd(runner=FakeSystemctl(fail="daemon-reload"), directory=tmp_path / "u2").install(cmd)


def test_scheduling_on_other_systems_says_when_it_comes(monkeypatch):
    from docscout.run import scheduler

    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(scheduler.Unsupported, match="macOS come in a later version"):
        scheduler.for_this_os()


# ---------------------------------------------------------------------- notifications


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux notifications")
def test_notifications_pass_text_as_arguments(monkeypatch):
    sent = []
    monkeypatch.setattr(notify.shutil, "which", lambda name: "/usr/bin/notify-send")
    monkeypatch.setattr(notify.subprocess, "run", lambda args, **kw: sent.append((args, kw)))
    assert notify.send("DocScout is done", "Report: ~/a & <b>.md", urgent=True)
    args, kwargs = sent[0]
    assert args == ["/usr/bin/notify-send", "--app-name=DocScout", "--urgency=critical", "--", "DocScout is done", "Report: ~/a &amp; &lt;b&gt;.md"]
    assert "shell" not in kwargs

    monkeypatch.setattr(notify.shutil, "which", lambda name: None)
    assert notify.send("x", "y") is False


def test_set_turns_notifications_off(tmp_path, monkeypatch):
    import tomllib

    from docscout import cli

    path = tmp_path / "config.toml"
    assert cli.main(["--config", str(path), "set", "--start-notification", "off"]) == 0
    saved = tomllib.loads(path.read_text())
    assert saved["notifications"] == {"run_started": False}
    assert cli.main(["--config", str(path), "set", "--finish-notification", "off"]) == 0
    assert tomllib.loads(path.read_text())["notifications"] == {"run_started": False, "run_finished": False}
