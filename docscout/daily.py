"""Unattended daily runs: ``docscout run --if-due``.

The schedule starts this every 15 minutes. It exits within a second unless today's run
is due and the computer is online. A day's run checks up to ``daily_repo_budget`` repos;
when it's cut short (a shutdown, a lost connection, a rate limit), the next check
continues it, skipping the repos already checked.

Problems that need you (no token, an expired token, repeated failures) always cause a
notification, at most once a day each. The start and finish notifications can be
turned off in ``[notifications]``.
"""

from __future__ import annotations

import json
import logging
import math
import statistics
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path

import httpx

from docscout import lock, pipeline
from docscout.config import Config
from docscout.db import Store
from docscout.github import AuthError, GitHub
from docscout.notify import Notifier

log = logging.getLogger(__name__)

MAX_SCHEDULED_RUNS_PER_DAY = 8  # a run that keeps getting cut short doesn't retry all day
RETRY_AFTER_FAILURE = timedelta(hours=1)
FAILURES_BEFORE_ALERT = 3
DEFAULT_SECONDS_PER_REPO = 10  # for the "about N minutes" estimate before there's any history

CONTINUING = "continuing today's run"
NOT_STARTED = "today's run hasn't happened yet"
TOKEN_MISSING = "Run docscout init to add one. Until then, the daily run can't start."
TOKEN_REJECTED = "GitHub rejected your token (it may have expired). Run docscout init to add a new one."


@dataclass
class Due:
    due: bool
    reason: str
    remaining: int = 0  # repos left in today's budget


def day_start(now: datetime, tz: tzinfo | None = None) -> datetime:
    """Midnight at the start of the local day containing ``now``, in UTC."""
    local = now.astimezone(tz)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def _when(value: str | datetime) -> datetime:
    return datetime.fromisoformat(value) if isinstance(value, str) else value


def clock_time(value: str | datetime, tz: tzinfo | None = None) -> str:
    return _when(value).astimezone(tz).strftime("%H:%M")


def check_due(store: Store, cfg: Config, now: datetime, tz: tzinfo | None = None) -> Due:
    """Whether a scheduled run should start now, and how many repos it may check."""
    budget = int(cfg["discovery"]["daily_repo_budget"])
    today = store.runs_since(day_start(now, tz))
    running = [r for r in today if r["status"] == "running"]
    if running:
        return Due(False, f"a run is in progress (started {clock_time(running[-1]['started'], tz)})")
    used = sum(r["analyzed"] or 0 for r in today)
    if used >= budget:
        return Due(False, "today's run is done")
    scheduled = [r for r in today if r["started_by"] == "schedule"]
    for r in scheduled:
        # Finished without using its whole allowance: the sources had nothing more today.
        if r["status"] in ("ok", "empty") and r["run_limit"] and (r["analyzed"] or 0) < r["run_limit"]:
            return Due(False, "today's run is done; there were no more candidates")
    if len(scheduled) >= MAX_SCHEDULED_RUNS_PER_DAY:
        return Due(False, f"stopped for today after {len(scheduled)} tries; the runs below say why")
    last = today[-1] if today else None
    if last is not None and last["status"] == "failed" and last["finished"]:
        retry = _when(last["finished"]) + RETRY_AFTER_FAILURE
        if retry > now:
            return Due(False, f"the last run failed; trying again after {clock_time(retry, tz)}")
    if last is not None and last["resume_after"] and _when(last["resume_after"]) > now:
        return Due(False, f"waiting for GitHub's rate limit; continuing after {clock_time(last['resume_after'], tz)}")
    if used:
        return Due(True, CONTINUING, budget - used)
    return Due(True, NOT_STARTED, budget)


def estimated_minutes(store: Store, repos: int) -> int:
    """How long checking ``repos`` repos should take, from recent finished runs."""
    rates = []
    for r in store.recent_runs(20):
        if r["status"] in ("ok", "empty") and r["finished"] and (r["analyzed"] or 0) >= 5:
            seconds = (_when(r["finished"]) - _when(r["started"])).total_seconds()
            if seconds > 0:
                rates.append(seconds / r["analyzed"])
        if len(rates) == 5:
            break
    rate = statistics.median(rates) if rates else DEFAULT_SECONDS_PER_REPO
    return max(1, math.ceil(rate * repos / 60))


def connection(gh: GitHub) -> str:
    """'online', 'offline' or 'token rejected', from one free request."""
    try:
        status = gh.ping()
    except httpx.TransportError:
        return "offline"
    if status == 401:
        return "token rejected"
    if status >= 500:  # GitHub is having problems: same as offline, try again later
        return "offline"
    return "online"


# ---------------------------------------------------------------------- remembering checks and alerts


def _record(store: Store, now: datetime, outcome: str) -> None:
    store.set_state("last_check", json.dumps({"at": now.isoformat(timespec="seconds"), "outcome": outcome}), now)


def last_check(store: Store) -> tuple[datetime, str] | None:
    raw = store.get_state("last_check")
    if not raw:
        return None
    data = json.loads(raw)
    return _when(data["at"]), data["outcome"]


def alert(store: Store, notifier: Notifier, now: datetime, key: str, title: str, body: str, tz: tzinfo | None = None) -> None:
    """A problem that needs you: shown at most once a day per kind of problem."""
    log.warning("%s: %s", title, body)
    today = now.astimezone(tz).date().isoformat()
    if store.get_state(f"alerted:{key}") == today:
        return
    notifier(title, body, urgent=True)
    store.set_state(f"alerted:{key}", today, now)


def _count_failure(store: Store, notifier: Notifier, now: datetime, failed: bool, tz: tzinfo | None) -> None:
    if not failed:
        store.set_state("failures_in_a_row", "0", now)
        return
    count = int(store.get_state("failures_in_a_row") or 0) + 1
    store.set_state("failures_in_a_row", str(count), now)
    if count >= FAILURES_BEFORE_ALERT:
        alert(store, notifier, now, "failing", "DocScout needs attention", f"The last {count} runs failed. Run docscout status to see why.", tz)


def _track_dry_days(store: Store, notifier: Notifier, cfg: Config, now: datetime, result: pipeline.RunResult, tz: tzinfo | None) -> None:
    """One notification when several days in a row found nothing new."""
    today = now.astimezone(tz).date().isoformat()
    state = json.loads(store.get_state("dry_days") or '{"days": 0, "last_day": null, "warned": false}')
    if result.report_path:
        state = {"days": 0, "last_day": today, "warned": False}
    elif result.status == "empty" and state["last_day"] != today:
        state["days"] += 1
        state["last_day"] = today
    limit = int(cfg["report"]["dry_pool_warning_days"])
    if state["days"] >= limit and not state["warned"]:
        notifier(
            f"DocScout hasn't found anything new for {state['days']} days",
            "Try more project sizes or languages, e.g. docscout set --sizes small,medium,large,huge",
        )
        state["warned"] = True
    store.set_state("dry_days", json.dumps(state), now)


def _short_path(path: Path) -> str:
    home = str(Path.home())
    text = str(path)
    return "~" + text[len(home) :] if text.startswith(home + "/") else text


def _notify_finished(notifier: Notifier, result: pipeline.RunResult, tz: tzinfo | None) -> None:
    stopped = result.summary.stopped_early or ""
    if stopped == "interrupted":  # shutting down or stopped on purpose: no need to say so
        return
    later = ""
    if stopped == pipeline.CONNECTION_LOST:
        later = "Lost the internet connection. The rest continues when you're back online."
    elif result.resume_after is not None:
        later = f"Reached GitHub's rate limit. The rest continues after {clock_time(result.resume_after, tz)}."
    if result.report_path:
        count = len(result.findings)
        body = f"Report: {_short_path(result.report_path)}" + (f"\n{later}" if later else "")
        notifier(f"DocScout found {count} new project{'s' if count != 1 else ''}", body)
    elif result.status == "partial":
        notifier("DocScout paused today's check", later or "It continues automatically.")
    elif result.status == "failed":
        notifier("DocScout stopped because of an error", "Run docscout status to see what happened.")
    else:
        notifier("DocScout is done", "Nothing new today.")


# ---------------------------------------------------------------------- the scheduled entry point


def run_if_due(
    cfg: Config,
    store: Store,
    *,
    lock_path: Path,
    github: Callable[[str], AbstractContextManager[GitHub]],
    notifier: Notifier,
    clock: Callable[[], datetime],
    sources: list[str],
    tz: tzinfo | None = None,
) -> int:
    """Run today's check if it's due. Returns the exit code for the scheduler."""
    try:
        with lock.hold(lock_path):
            return _run_locked(cfg, store, github, notifier, clock, sources, tz)
    except lock.Busy:
        log.info("another DocScout run is in progress; nothing to do")
        return 0


def _run_locked(
    cfg: Config,
    store: Store,
    github: Callable[[str], AbstractContextManager[GitHub]],
    notifier: Notifier,
    clock: Callable[[], datetime],
    sources: list[str],
    tz: tzinfo | None,
) -> int:
    now = clock()
    if store.close_stale_runs(now):
        log.info("an earlier run was cut off; this run continues it")
    due = check_due(store, cfg, now, tz)
    if not due.due:
        log.info("nothing to do: %s", due.reason)
        _record(store, now, f"nothing to do: {due.reason}")
        return 0
    token = cfg.github_token
    if not token:
        _record(store, now, "no GitHub token")
        alert(store, notifier, now, "token-missing", "DocScout needs a GitHub token", TOKEN_MISSING, tz)
        return 1
    settings = cfg["notifications"]
    with github(token) as gh:
        state = connection(gh)
        if state == "offline":
            log.info("offline; trying again at the next check")
            _record(store, now, "offline; trying again in 15 minutes")
            return 0
        if state == "token rejected":
            _record(store, now, "GitHub rejected the token")
            alert(store, notifier, now, "token-rejected", "DocScout needs attention", TOKEN_REJECTED, tz)
            return 1
        _record(store, now, f"started a run: {due.reason}")
        if settings["run_started"]:
            minutes = estimated_minutes(store, due.remaining)
            title = "DocScout is continuing today's check" if due.reason == CONTINUING else "DocScout is checking projects"
            notifier(title, f"Your computer may be slower for about {minutes} minute{'s' if minutes != 1 else ''}.")
        try:
            result = pipeline.run(gh, cfg, store, now, limit=due.remaining, sources=sources, started_by="schedule", progress=log.info)
        except AuthError:
            _count_failure(store, notifier, clock(), True, tz)
            alert(store, notifier, clock(), "token-rejected", "DocScout needs attention", TOKEN_REJECTED, tz)
            return 1
        except Exception:  # the run keeps what it found; this is an error outside its main loop
            log.exception("the daily run stopped with an unexpected error")
            _count_failure(store, notifier, clock(), True, tz)
            if settings["run_finished"]:
                notifier("DocScout stopped because of an error", "Run docscout status to see what happened.")
            return 1
    log.info("run finished: %s, %d new", result.status, len(result.findings))
    if settings["run_finished"]:
        _notify_finished(notifier, result, tz)
    _count_failure(store, notifier, clock(), result.status == "failed", tz)
    _track_dry_days(store, notifier, cfg, clock(), result, tz)
    return 1 if result.status == "failed" else 0


# ---------------------------------------------------------------------- docscout status


def status_report(
    store: Store, cfg: Config, now: datetime, *, running: bool, scheduled: bool = True, tz: tzinfo | None = None, runs: int = 7
) -> str:
    """Today's progress, what happens next, the last check and recent runs, in plain words."""
    budget = int(cfg["discovery"]["daily_repo_budget"])
    today = store.runs_since(day_start(now, tz))
    used = sum(r["analyzed"] or 0 for r in today)
    stale = any(r["status"] == "running" for r in today) and not running
    if running:
        state = "a run is in progress right now"
    elif stale:
        state = "the last run was cut off; the next check continues it"
    else:
        due = check_due(store, cfg, now, tz)
        if not due.due:
            state = due.reason
        elif not scheduled:
            state = NOT_STARTED if due.reason == NOT_STARTED else "today's run stopped early; docscout run continues it"
        elif due.reason == CONTINUING:
            state = "the next check continues today's run"
        else:
            state = "today's run starts at the next check"
    lines = [f"Today: {used} of {budget} repos checked. {state[0].upper()}{state[1:]}."]
    checked = last_check(store)
    if checked:
        lines.append(f"Last scheduled check: {checked[0].astimezone(tz).strftime('%d %b %H:%M')}, {checked[1]}.")
    recent = store.recent_runs(runs)
    if recent:
        lines += ["", "Recent runs:"]
        for r in recent:
            when = _when(r["started"]).astimezone(tz).strftime("%d %b %H:%M")
            status = "cut off" if r["status"] == "running" and not running else r["status"]
            detail = r["report_path"] or r["error"] or ""
            lines.append(
                f"  {when}  {r['started_by']:<8}  {status:<8} {r['analyzed'] or 0:>3} repos  {r['new_items'] or 0:>2} new  {detail}".rstrip()
            )
    else:
        lines += ["", "No runs yet."]
    return "\n".join(lines)
