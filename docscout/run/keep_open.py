"""Open picks stay listed, and stay true (M6 step 6d, docs/PLAN.md section 21).

On the website (``[picks] keep_open``), a pick has no age limit: it stays listed while it's open.
Every run looks at every listed pick (:mod:`docscout.run.watch`) and acts on what changed:

- **gone, archived or quiet:** a deleted or private repo is dropped; an archived one, or one with
  no push for ``[health] pushed_within_days``, goes back into the pool;
- **renamed:** the pick follows the new name;
- **help requests:** a closed or deleted one comes off the card, an edited one is asked about
  again (:mod:`docscout.llm.help_requests`), and a pick listed only because of one leaves;
- **re-checked** with the checks a new candidate gets (health, then the docs, measured again)
  when its docs file changed, and at least every 7 days: a pick whose docs got fixed, or that
  fails the health checks, goes back into the pool;
- **claims** are checked again when its PRs or comments changed (:mod:`docscout.llm.claims`).

A pick that goes back into the pool is checked again after ``recheck_after_days``, like any repo,
so one that comes back to life can return. Each run has caps; within them, the picks free visitors
see come first, then the newest. What doesn't fit waits for the next run.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

from docscout.analyze.apitypes import ApiType
from docscout.analyze.apitypes.base import DocsContext
from docscout.analyze.gaps import effort_label
from docscout.analyze.scoring import opportunity_score
from docscout.analyze.tree import has_contributing
from docscout.find.github import GitHub, GitHubError
from docscout.find.health import gate_activity, gate_metadata, health_score, parse_time, pr_stats
from docscout.llm import LLMClient, LLMError, LLMUnavailable, memory
from docscout.llm import claims as claims_mod
from docscout.llm import help_requests
from docscout.llm.base import review_with_retry
from docscout.llm.review import context_for
from docscout.run import watch
from docscout.run.db import Store, StoredFinding
from docscout.settings.config import Config

log = logging.getLogger(__name__)

RECHECK_DAYS = 7  # a full re-check at least this often, even when the docs file didn't change
REWRITE_SHARE = 0.2  # when the work needed moves by this share, Gemma rewrites its notes
WEEK = timedelta(days=7)
FREE = 3  # the picks free visitors see, checked first


@dataclass
class Caps:
    rechecks: int
    claims: int
    gemma: int  # questions for Gemma: help requests, claims, rewrites


def caps_for(cfg: Config, daily: bool) -> Caps:
    picks, llm = cfg["picks"], cfg["llm"]
    if daily:
        return Caps(int(picks["rechecks_per_run"]), int(picks["claims_per_run"]), int(llm["checks_per_run"]))
    return Caps(int(picks["rechecks_per_look"]), int(picks["claims_per_look"]), int(llm["checks_per_look"]))


@dataclass
class Outcome:
    looked: int = 0
    rechecked: int = 0
    claims_checked: int = 0
    help_asked: int = 0
    rewritten: int = 0
    gemma_asked: int = 0
    waiting: int = 0  # picks with a check left for a later run: a cap was reached
    renamed: list[tuple[str, str]] = field(default_factory=list)
    left: list[tuple[str, str]] = field(default_factory=list)  # (repo, why)
    skipped: str | None = None  # why Gemma's questions waited


def _when(finding: StoredFinding) -> datetime | None:
    return parse_time(finding.reported) if finding.reported else None


def priority(picks: list[StoredFinding], now: datetime) -> list[StoredFinding]:
    """The picks free visitors see first (the best 3 found in the last 7 days), then the newest."""
    week = [f for f in picks if (_when(f) or now - 2 * WEEK) > now - WEEK]
    free = {f.full_name for f in sorted(week, key=lambda f: -f.score)[:FREE]}
    return sorted(picks, key=lambda f: (f.full_name not in free, -((_when(f) or now - 520 * WEEK).timestamp())))


def leave(store: Store, finding: StoredFinding, now: datetime, reason: str, *, gone: bool = False) -> None:
    """Take a pick off the list. A gone repo is ignored from then on; any other goes back into the
    pool, checked again after ``recheck_after_days`` from now."""
    d = {**finding.details, "left": {"date": now.isoformat(timespec="seconds"), "reason": reason}}
    if finding.finding_id is not None:
        store.set_review(finding.finding_id, "rejected", finding.score, d)
    store.set_status(finding.full_name, "ignored" if gone else "new", now, reason=reason)
    if not gone:
        store.save_repo(finding.full_name, now)
    log.info("%s leaves the list: %s", finding.full_name, reason)


def recheck(gh: GitHub, cfg: Config, finding: StoredFinding, now: datetime, api_type: ApiType) -> tuple[str | None, dict[str, Any]]:
    """The checks a new candidate gets: health (from GitHub now), then the docs, measured again.
    Returns (why the pick leaves, or None; what was measured). Raises GitHubError."""
    name, d = finding.full_name, finding.details
    repo = gh.get_repo(name)
    reason = gate_metadata(repo, cfg["health"], now)
    if reason:
        return f"failed the health checks: {reason}", {}
    pulls = gh.list_closed_pulls(name)
    commits = gh.list_commits(name, (now - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    stats = pr_stats(pulls, commits, now)
    counted = [i for i in d.get("issues") or [] if help_requests.counts(i)]
    health_cfg = cfg["health"]
    thresholds = health_cfg | health_cfg.get("help_requested", {}) if any(i.get("outreach") for i in counted) else health_cfg
    reason = gate_activity(stats, thresholds)
    if reason:
        return f"failed the health checks: {reason}", {}
    tree, _truncated = gh.get_tree(name, repo.get("default_branch") or "HEAD")
    readme = gh.get_readme(name)
    head = commits[0].get("sha") if commits else d.get("head_sha")
    confidence = float((d.get("score") or {}).get("type_confidence", d.get("code_confidence", 0.6)))
    gap = api_type.analyze(DocsContext(gh=gh, full_name=name, repo=repo, tree=tree or [], readme=readme, head_sha=head, type_confidence=confidence))
    min_units = int(cfg["report"]["min_effort_units"])
    if gap is None:
        return "docs fixed: DocScout finds no gap in them any more", {}
    if gap.check_manually and not counted:
        return "its docs may be elsewhere, and no help request asks for API docs work", {}
    if gap.effort_units is not None and gap.effort_units < min_units:
        before = (d.get("gap") or {}).get("effort_units")
        if gap.effort_units == 0:
            return "docs fixed: no operation or endpoint needs work any more", {}
        if before is not None and before >= min_units:
            return f"docs mostly fixed: only {gap.effort_units} operations or endpoints still need work, of {before}", {}
        return f"too small: only {gap.effort_units} operations or endpoints need work (the cutoff is {min_units})", {}
    return None, {"gap": gap, "stats": stats, "health": health_score(stats, has_contributing(tree or [])), "head": head, "repo": repo, "counted": counted}


def apply_recheck(d: dict[str, Any], result: dict[str, Any], cfg: Config, now: datetime) -> tuple[float, bool]:
    """Put the re-check's numbers on the pick, keeping its found date, review and place. Returns
    (its new score, whether the work needed moved enough for Gemma to rewrite its notes)."""
    gap = result["gap"]
    old = (d.get("gap") or {}).get("effort_units")
    parts = d.get("score") or {}
    score = opportunity_score(
        gap.score, result["health"], float(parts.get("type_confidence", d.get("code_confidence", 0.6))), result["counted"],
        (d.get("repo") or {}).get("language_match"), int(cfg["scoring"]["language_bonus"]),
        int(cfg["scoring"]["published_docs_bonus"]) if gap.published else 0,
    )  # fmt: skip
    repo = result["repo"]
    d.update(gap=gap.as_dict(), effort=effort_label(gap.effort_units), stats=result["stats"].as_dict(), head_sha=result["head"],
             score=score.as_dict(), breakdown=score.breakdown())  # fmt: skip
    d["repo"] = {**(d.get("repo") or {}), "stars": repo.get("stargazers_count"), "pushed_at": repo.get("pushed_at"), "description": repo.get("description")}
    d["history"] = (list(d.get("history") or []) + [{"date": now.isoformat(timespec="seconds"), "work": gap.effort_units, "score": round(score.total, 1)}])[-10:]
    moved = bool(old) and gap.effort_units is not None and abs(gap.effort_units - old) / old >= REWRITE_SHARE
    return score.total, moved


def rewrite(client: LLMClient, cfg: Config, finding: StoredFinding, api_type: ApiType, now: datetime) -> None:
    """Gemma rewrites why the docs matter and the first steps, which quote the numbers. Its verdict
    and the pick's place stay as they were. Raises LLMError."""
    review = review_with_retry(client, context_for(finding, [api_type.label]), int(cfg["llm"].get("readme_chars", 1500)), False)
    notes = finding.details.setdefault("review", {})
    notes.update(why=review.why, first_steps=review.first_steps, rewritten=now.isoformat(timespec="seconds"), model=client.name)
    notes.pop("stale_notes", None)


def step(
    gh: GitHub,
    store: Store,
    cfg: Config,
    now: datetime,
    reviewer: Callable[[], LLMClient],
    types_by_key: dict[str, ApiType],
    caps: Caps,
    progress: Callable[[str], None] = lambda message: None,
) -> Outcome:
    """Look at every listed pick and act on what changed, within ``caps``."""
    out = Outcome()
    picks = store.reported_since(now - 520 * WEEK)
    if not picks:
        return out
    states = watch.look(gh, picks)
    out.looked = len(picks)
    denylist = list(cfg["discovery"]["issue_label_denylist"])
    pushed_days = int(cfg["health"]["pushed_within_days"])
    min_units = int(cfg["report"]["min_effort_units"])
    opened: list[LLMClient] = []

    def model() -> LLMClient | None:
        """Gemma, opened on first use; None once it can't be used this run."""
        if opened:
            return opened[0]
        if out.skipped:
            return None
        out.skipped = memory.shortage(cfg["llm"])
        if out.skipped is None:
            try:
                opened.append(reviewer())
            except LLMError as exc:
                out.skipped = str(exc)
        return opened[0] if opened else None

    try:
        for finding in priority(picks, now):
            if finding.full_name.lower() not in states:  # GitHub couldn't answer for it this time
                out.waiting += 1
                continue
            state = states[finding.full_name.lower()]
            if state is None:
                leave(store, finding, now, "the repo was deleted or made private", gone=True)
                out.left.append((finding.full_name, "the repo was deleted or made private"))
                continue
            if state["name"] and state["name"] != finding.full_name:
                store.rename(finding.full_name, state["name"])
                out.renamed.append((finding.full_name, state["name"]))
                finding = replace(finding, full_name=state["name"])
            pushed = parse_time(state.get("pushed"))
            quiet = f"failed the health checks: no push in {pushed_days} days" if pushed and now - pushed > timedelta(days=pushed_days) else None
            reason = "failed the health checks: archived" if state.get("archived") else quiet
            if reason:
                leave(store, finding, now, reason)
                out.left.append((finding.full_name, reason))
                continue
            d = finding.details
            old = d.get("watch") or {}
            what = watch.changed(old, state)

            # Help requests: closed or deleted ones come off; edited ones are asked about again.
            help_changed = False
            for issue in d.get("issues") or []:
                number = str(int(issue["number"]))
                if f"issue {number}" not in what:
                    continue
                now_state = (state.get("issues") or {}).get(number) or ["DELETED", None, 0]
                if now_state[0] in ("CLOSED", "DELETED"):
                    issue["state"] = now_state[0].lower()
                    issue["help"] = {"verdict": issue["state"]}
                    help_changed = True
                elif old and ((old.get("issues") or {}).get(number) or [None, None])[1] != now_state[1]:
                    help_requests.fetch_text(gh, finding.full_name, issue)  # its text may have changed
            # Gemma reads each request's text, so fetch it where it's missing: picks reported before
            # 6 Nov were stored without it, and until 8 Nov every request on the website was judged
            # from its title alone (writerslogic/warm #10, "Node.js API reference with usage
            # examples", counted as a request for the REST spec's examples). A fetched text changes
            # the request's signature, so it's asked about again.
            for issue in d.get("issues") or []:
                if "text" not in issue and issue.get("state") not in ("closed", "deleted") and not help_requests.is_bounty(issue, denylist):
                    help_requests.fetch_text(gh, finding.full_name, issue)
            if caps.gemma > 0 and any(help_requests.due(i, denylist) for i in d.get("issues") or []) and model() is not None:
                try:
                    asked = help_requests.check(opened[0], d, finding.full_name, denylist)
                    caps.gemma, out.help_asked, out.gemma_asked = caps.gemma - asked, out.help_asked + asked, out.gemma_asked + asked
                    help_changed = help_changed or bool(asked)
                except LLMUnavailable as exc:
                    out.skipped, caps.gemma = str(exc), 0
                except LLMError as exc:
                    log.info("couldn't ask about %s's help requests: %s", finding.full_name, exc)
            counted, reason = help_requests.effects(d, cfg["health"])
            if reason:
                leave(store, finding, now, reason)
                out.left.append((finding.full_name, reason))
                continue

            # The re-check: when the docs file changed, the first time, and at least weekly.
            api_type = types_by_key.get(d.get("api_type", ""))
            last = parse_time(old.get("rechecked"))
            rechecked, gap_changed, score = old.get("rechecked"), False, finding.score
            if api_type is not None and ("docs" in what or last is None or now - last >= timedelta(days=RECHECK_DAYS)):
                if caps.rechecks <= 0:
                    out.waiting += 1
                else:
                    caps.rechecks -= 1
                    try:
                        reason, result = recheck(gh, cfg, finding, now, api_type)
                    except GitHubError as exc:
                        log.info("couldn't re-check %s: %s", finding.full_name, exc)
                        reason, result = None, {}
                    if reason:
                        leave(store, finding, now, reason)
                        out.left.append((finding.full_name, reason))
                        continue
                    if result:
                        score, moved = apply_recheck(d, result, cfg, now)
                        rechecked, gap_changed, out.rechecked = now.isoformat(timespec="seconds"), True, out.rechecked + 1
                        if moved:
                            d.setdefault("review", {})["stale_notes"] = True
            elif help_changed:
                score = help_requests.rescore(d, cfg, counted).total

            # Claims: when its PRs or comments changed, its gaps changed, or never checked per gap.
            if "prs" in what or any(w.startswith("issue ") for w in what) or gap_changed or "claims" not in d:
                if caps.claims <= 0 or model() is None:
                    out.waiting += 1
                else:
                    caps.claims -= 1
                    before = d.get("claims_signature")
                    try:  # most need no question (PRs are measured): only one with comments to judge waits for Gemma's budget
                        if claims_mod.check(gh, opened[0], finding, now, min_units, can_ask=caps.gemma > 0):
                            out.claims_checked += 1
                            if d.get("claims_signature") != before and d.get("claims_model"):
                                caps.gemma, out.gemma_asked = caps.gemma - 1, out.gemma_asked + 1
                        else:
                            out.waiting += 1
                    except LLMUnavailable as exc:
                        out.skipped, caps.gemma = str(exc), 0

            # Gemma's notes quote the numbers: rewritten after claims, which matter more.
            if (d.get("review") or {}).get("stale_notes") and api_type is not None and caps.gemma > 0 and model() is not None:
                try:
                    rewrite(opened[0], cfg, finding, api_type, now)
                    caps.gemma, out.rewritten, out.gemma_asked = caps.gemma - 1, out.rewritten + 1, out.gemma_asked + 1
                except LLMUnavailable as exc:
                    out.skipped, caps.gemma = str(exc), 0
                except LLMError as exc:
                    log.info("couldn't rewrite the notes on %s: %s", finding.full_name, exc)

            # Listed once it has had its first re-check, a claim check per gap and its help requests answered.
            listed = bool(old.get("listed")) or (bool(rechecked) and "claims" in d and not any(help_requests.due(i, denylist) for i in d.get("issues") or []))
            d["watch"] = {**state, "looked": now.isoformat(timespec="seconds"), "rechecked": rechecked, "listed": listed}
            if finding.finding_id is not None:
                store.set_review(finding.finding_id, "accepted", score, d)
        progress(f"looked at {out.looked} listed picks: {out.rechecked} re-checked, {out.claims_checked} claim checks, {len(out.left)} left the list")
    finally:
        for client in opened:
            client.unload()
            client.close()
    return out
