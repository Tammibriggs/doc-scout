"""The SQLite store (the command-line tool) and the Atlas store (the hosted version) must behave
the same: every test here runs against both. Atlas is replaced by mongomock, so no test reaches
a real database. The Atlas half is skipped unless pymongo and mongomock are installed."""

from datetime import timedelta

import pytest

from docscout.run.db import Store


@pytest.fixture(params=["sqlite", "atlas"])
def store(request, tmp_path):
    if request.param == "sqlite":
        s = Store(tmp_path / "docscout.db")
    else:
        mongomock = pytest.importorskip("mongomock")
        pytest.importorskip("pymongo")
        from docscout.hosted.atlas_store import AtlasStore

        s = AtlasStore(mongomock.MongoClient().db)
    yield s
    s.close()


def finding(store, run, now, name, score, *, review=None, details=None, days_ago=0):
    store.save_repo(name, now - timedelta(days=days_ago), source="repo_search", stars=100)
    store.save_finding(run, name, now - timedelta(days=days_ago), api_type="rest", kind="spec", gap=60, score=score, effort="M",
                       details=details or {"gap": {"kind": "spec"}, "n": score})  # fmt: skip
    found = store.latest_finding(name)
    if review is not None:
        store.set_review(found.finding_id, review, score, found.details)
    return found


def test_runs_are_numbered_finished_and_listed(store, now):
    first = store.start_run(now - timedelta(days=1), run_limit=60, started_by="schedule")
    second = store.start_run(now)
    assert second == first + 1
    store.update_progress(first, 12)
    store.finish_run(first, now - timedelta(hours=23), status="ok", analyzed=60, new_items=3, api_calls=197, report_path="r.md", reviewed=3)
    assert store.close_stale_runs(now) == 1  # the second was still running
    recent = store.recent_runs(5)
    assert [r["id"] for r in recent] == [second, first]
    assert (recent[1]["status"], recent[1]["analyzed"], recent[1]["run_limit"], recent[1]["started_by"], recent[1]["reviewed"]) == ("ok", 60, 60, "schedule", 3)
    assert recent[0]["status"] == "partial" and "stopped before finishing" in recent[0]["error"]
    assert [r["id"] for r in store.runs_since(now - timedelta(hours=1))] == [second]
    assert store.reviewed_since(now - timedelta(days=2)) == 3


def test_state_and_search_cursor(store, now):
    assert store.get_state("last_check") is None
    store.set_state("last_check", "a", now)
    store.set_state("last_check", "b", now)
    assert store.get_state("last_check") == "b"
    assert store.slice_position("topic:x") == (1, 0, None)
    store.touch_slice("topic:x", now)
    assert store.slice_position("topic:x")[:2] == (1, 0)
    store.save_slice("topic:x", page=3, cycle=1)
    assert store.slice_position("topic:x") == (3, 1, now.isoformat(timespec="seconds"))


def test_repos_are_remembered_and_skipped(store, now):
    assert store.skip_reason("Org/App", now, 90) is None
    store.save_repo("Org/App", now - timedelta(days=5), source="repo_search", stars=50, rejected="no license")
    row = store.repo("org/app")
    assert (row["key"], row["full_name"], row["status"], row["stars"], row["rejected"]) == ("org/app", "Org/App", "new", 50, "no license")
    assert store.skip_reason("org/app", now, 90) == "checked recently"
    assert store.skip_reason("org/app", now + timedelta(days=100), 90) is None
    store.set_status("Org/App", "reported", now)
    assert store.repo("Org/App")["last_reported"] == now.isoformat(timespec="seconds")
    assert store.skip_reason("org/app", now, 90) == "already reported"
    store.set_status("Other/Thing", "ignored", now, reason="not an API")  # a repo never checked
    assert store.skip_reason("other/thing", now, 90) == "ignored" and store.repo("other/thing")["status_reason"] == "not an API"
    with pytest.raises(ValueError):
        store.save_repo("org/app", now, colour="blue")


def test_findings_wait_for_review_then_for_the_report(store, now):
    run = store.start_run(now)
    finding(store, run, now, "org/high", 80)
    finding(store, run, now, "org/low", 30)
    finding(store, run, now, "org/tiny", 10)  # below min_score
    finding(store, run, now, "org/stale", 90, days_ago=20)  # older than 14 days
    assert [f.full_name for f in store.findings_to_review(now, 25, 10)] == ["org/high", "org/low"]
    assert store.count_waiting(now, 25) == 2
    high = store.latest_finding("org/high")
    store.set_review(high.finding_id, "accepted", 82, {**high.details, "review": {"model": "gemma"}})
    store.set_review(store.latest_finding("org/low").finding_id, "rejected", 30, {})
    pending = store.pending_findings(now, 25, 10)
    assert [(f.full_name, f.score, f.details["review"]["model"]) for f in pending] == [("org/high", 82, "gemma")]
    assert store.count_waiting(now, 25) == 0
    store.update_details(run, "org/high", {**pending[0].details, "checks": {"claimed": []}})
    assert store.latest_finding("org/high").details["checks"] == {"claimed": []}


def test_only_the_latest_finding_of_each_repo_counts(store, now):
    first = store.start_run(now - timedelta(days=2))
    finding(store, first, now, "org/app", 90, review="accepted", days_ago=2)
    second = store.start_run(now)
    finding(store, second, now, "org/app", 40)  # checked again: waiting for review
    assert store.pending_findings(now, 25, 10) == []
    assert [f.score for f in store.findings_to_review(now, 25, 10)] == [40]


def test_reported_projects_are_listed_until_marked(store, now):
    old = store.start_run(now - timedelta(days=10))
    finding(store, old, now, "org/old", 70, review="accepted", days_ago=10)
    store.set_status("org/old", "reported", now - timedelta(days=10))
    run = store.start_run(now)
    finding(store, run, now, "org/a", 50, review="accepted")
    finding(store, run, now, "org/b", 60, review="accepted")
    store.set_status("org/a", "reported", now)
    store.set_status("org/b", "reported", now)
    week = store.reported_since(now - timedelta(days=7))
    assert [(f.full_name, f.reported) for f in week] == [("org/b", now.isoformat(timespec="seconds")), ("org/a", now.isoformat(timespec="seconds"))]
    assert [f.full_name for f in store.still_open(run, 5)] == ["org/old"]  # reported by an earlier run
    store.set_status("org/old", "done", now)
    assert [f.full_name for f in store.still_open(run + 1, 5)] == ["org/b", "org/a"]  # done: no longer listed


def test_the_atlas_store_takes_over_a_sqlite_memory(tmp_path, now):
    mongomock = pytest.importorskip("mongomock")
    pytest.importorskip("pymongo")
    from docscout.hosted.atlas_store import AtlasStore

    old = Store(tmp_path / "old.db")
    run = old.start_run(now - timedelta(days=1), run_limit=60, started_by="schedule")
    finding(old, run, now, "org/app", 70, review="accepted", details={"gap": {"kind": "spec"}, "checks": {"claimed": []}})
    old.set_status("org/app", "reported", now)
    old.save_repo("org/seen", now, rejected="no license")
    old.save_slice("topic:x", page=4, cycle=2)
    old.set_state("quiet_days", "3", now)
    old.finish_run(run, now, status="ok", analyzed=60, new_items=1, api_calls=200)
    old.close()

    atlas = AtlasStore(mongomock.MongoClient().db)
    assert atlas.is_empty()
    counts = atlas.import_sqlite(tmp_path / "old.db")
    assert counts == {"repos": 2, "runs": 1, "findings": 1, "run_state": 1, "sweep": 1} and not atlas.is_empty()
    assert [f.full_name for f in atlas.reported_since(now - timedelta(days=7))] == ["org/app"]
    assert atlas.reported_since(now - timedelta(days=7))[0].details["checks"] == {"claimed": []}  # an embedded document now
    assert atlas.skip_reason("org/seen", now, 90) == "checked recently" and atlas.slice_position("topic:x")[:2] == (4, 2)
    assert atlas.get_state("quiet_days") == "3" and atlas.recent_runs(1)[0]["analyzed"] == 60
    assert atlas.start_run(now) == run + 1  # numbering continues after the imported runs
