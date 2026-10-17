"""Command-line entry points.

- Setup: ``init``, ``set``, ``profile``.
- Daily use: ``run`` (find projects and write a report), ``draft`` (a first message to the
  maintainers of a project you picked), ``done`` / ``ignore`` (hide a project from future
  reports), ``score`` (analyze one spec file or repo).
- Running unattended: ``schedule install`` / ``uninstall`` / ``status``, ``status``, and
  ``run --if-due``, which the schedule starts every 15 minutes.
- Stage M0 checks: ``discover``, ``eval``, ``bench-llm``.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import signal
import sys
from pathlib import Path

from docscout import __version__
from docscout.settings.config import Config, data_dir, load_config, log_dir, user_config_path
from docscout.errors import ConfigError

log = logging.getLogger("docscout")


def _cmd_init(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.settings import setup_wizard

    path = args.config or user_config_path()
    if args.yes:
        answers = setup_wizard.answers_from_config(cfg)
    else:
        # Settings given as flags are answers already, so their questions are skipped.
        fixed = frozenset(profile_overrides(args)) | frozenset(f"llm.{k}" for k in llm_overrides(args))
        try:
            answers = setup_wizard.ask_interactively(cfg, fixed=fixed)
        except (KeyboardInterrupt, EOFError):
            print("\nSetup cancelled; nothing was saved.", file=sys.stderr)
            return 130
    _save_and_show(cfg, answers, path)
    print("\nEverything else uses a default. To change languages, project sizes or the model:")
    print('  docscout set --languages "python, go"     (see "Changing other settings" in the README)')
    print("\nNext:")
    print("  docscout run                 a first report now (about 10 minutes)")
    print("  docscout schedule install    then it runs every day by itself")
    return 0


def _cmd_set(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.settings import setup_wizard
    from docscout.settings.config import save_user_config

    notifications = {
        key: value == "on"
        for key, value in (("run_started", args.start_notification), ("run_finished", args.finish_notification))
        if value is not None
    }
    if not profile_overrides(args) and not llm_overrides(args) and not notifications:
        print('Nothing to change. For example: docscout set --languages "python, go" --sizes small,medium', file=sys.stderr)
        return 2
    path = args.config or user_config_path()
    if notifications:
        save_user_config(path, {"notifications": notifications}, header=setup_wizard.CONFIG_HEADER)
        words = {"run_started": "when the daily run starts", "run_finished": "when it finishes"}
        for key, on in notifications.items():
            print(f"Notifications {words[key]}: {'on' if on else 'off'}.")
        if not profile_overrides(args) and not llm_overrides(args):
            return 0
    _save_and_show(cfg, setup_wizard.answers_from_config(cfg), path)
    llm = cfg["llm"]
    if llm_overrides(args) and llm["provider"] == "ollama":
        installed = setup_wizard.list_ollama_models(llm["base_url"])
        if installed is None:
            print(f"\nNote: Ollama isn't running at {llm['base_url']}, so the model couldn't be checked.")
        elif llm["model"] not in installed:
            print(f"\nNote: {llm['model']} isn't downloaded yet. Run: ollama pull {llm['model']}")
            print(f"Downloaded models: {', '.join(installed) or 'none'}")
    return 0


def _save_and_show(cfg: Config, answers, path: Path) -> None:
    from docscout.settings import setup_wizard
    from docscout.analyze.apitypes import enabled_types
    from docscout.settings.profile import describe

    print()
    for message in setup_wizard.save(answers, cfg, path):
        print(message)
    saved = load_config(path)
    print()
    print(describe(saved.values, enabled_types(saved["api_types"]), has_token=bool(saved.github_token), config_path=str(path)))


def _cmd_profile(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.analyze.apitypes import enabled_types
    from docscout.settings.profile import describe

    path = str(cfg.path) if cfg.path else None
    print(describe(cfg.values, enabled_types(cfg["api_types"]), has_token=bool(cfg.github_token), config_path=path))
    print('\nChange these with docscout set, e.g. docscout set --languages "python, go"')
    return 0


def _cmd_discover(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.find.discover import LABELS, draw_sample, write_rejected, write_sample
    from docscout.find.github import GitHub
    from docscout.find.health import utcnow

    token = cfg.github_token
    sources = args.sources.split(",") if args.sources else list(cfg["discovery"]["sources"])
    if not token:
        print(
            "No GitHub token found (set GITHUB_TOKEN). Without one GitHub allows only 60 requests an hour,\n"
            "so the sample will be small. Create a fine-grained token with read-only access to public repos.",
            file=sys.stderr,
        )
        if "code_search" in sources:
            sources.remove("code_search")
            print("code_search needs a token; skipping it.", file=sys.stderr)

    out = Path(args.csv)
    rng = random.Random(args.seed)
    with GitHub(token) as gh:
        sample = draw_sample(gh, cfg, sources, args.sample, rng=rng, now=utcnow(), progress=lambda m: print(m, file=sys.stderr))
        calls = dict(gh.calls)

    write_sample(out, sample.passed)
    rejected_path = out.with_name(out.stem + ".rejected.csv")
    write_rejected(rejected_path, sample.rejected)

    print(f"\n{len(sample.passed)} repos passed the health gate -> {out}")
    print(f"{len(sample.rejected)} rejected (for reference, no need to label) -> {rejected_path}")
    for s in sample.summaries:
        reasons = ", ".join(f"{k}: {v}" for k, v in sorted(s.rejections.items(), key=lambda kv: -kv[1])[:4])
        print(f"  {s.source:<20} tried {s.tried:>3}, passed {s.passed:>3}  {reasons}")
    print(f"GitHub API calls: {calls}")
    if sample.stopped_early:
        print(f"Stopped early: {sample.stopped_early}", file=sys.stderr)
    for note in sample.notes:
        print(f"Note: {note}", file=sys.stderr)
    print(f"\nNext: open {out}, fill the 'label' column with one of: {', '.join(LABELS)}")
    print(f"Then run: docscout eval {out}")
    return 0 if sample.passed else 1


def store_path() -> Path:
    return data_dir() / "docscout.db"


def lock_path() -> Path:
    return data_dir() / "run.lock"


def _stop_on_sigterm() -> None:
    """The schedule stops a run with SIGTERM (e.g. at shutdown): end it like Ctrl+C, keeping its results."""

    def handler(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handler)


def _github(cfg: Config):
    from docscout.find.github import GitHub

    if not cfg.github_token:
        print("No GitHub token found, so GitHub allows only 60 requests an hour. Run `docscout init` to add one.", file=sys.stderr)
    return GitHub(cfg.github_token)


def _cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.run import pipeline
    from docscout.run.db import Store
    from docscout.find.github import AuthError
    from docscout.find.health import utcnow

    from docscout.run import lock

    sources = args.sources.split(",") if args.sources else list(cfg["discovery"]["sources"])
    if not cfg.github_token and "code_search" in sources:
        sources.remove("code_search")
    _stop_on_sigterm()
    if args.if_due:
        return _run_if_due(cfg, sources)
    limit = int(cfg["discovery"]["daily_repo_budget"]) if args.limit is None else max(0, args.limit)
    store = Store(store_path())
    try:
        with lock.hold(lock_path()), _github(cfg) as gh:
            print(f"Checking up to {limit} repos...", file=sys.stderr)
            result = pipeline.run(gh, cfg, store, utcnow(), limit=limit, sources=sources, progress=lambda m: print("  " + m, file=sys.stderr))
    except lock.Busy:
        print("DocScout is already running (probably the daily run). Try again when it's done; `docscout status` shows progress.", file=sys.stderr)
        return 1
    except AuthError:
        print("GitHub rejected the token (it may have expired). Run `docscout init` to add a new one.", file=sys.stderr)
        return 1
    finally:
        store.close()
    s = result.summary
    print(f"\nChecked {s.evaluated} repos: {s.passed} passed the health checks, {s.with_gaps} have docs gaps.")
    if s.model:
        print(f"{s.model} reviewed {s.reviewed} ({s.accepted} accepted).")
    if s.stopped_early:
        print(f"Stopped early: {s.stopped_early}")
    for note in s.notes:
        print(f"Note: {note}")
    if result.report_path:
        print(f"Report with {len(result.findings)} new projects: {result.report_path}")
    else:
        print("Nothing new scored high enough for a report this time.")
    return 0


def _run_if_due(cfg: Config, sources: list[str]) -> int:
    from docscout.run import daily, notify
    from docscout.run.db import Store
    from docscout.find.github import GitHub
    from docscout.find.health import utcnow

    store = Store(store_path())
    try:
        return daily.run_if_due(
            cfg, store, lock_path=lock_path(), github=GitHub, notifier=notify.send, clock=utcnow, sources=sources
        )
    finally:
        store.close()


def _schedule_line(cfg: Config, args: argparse.Namespace) -> tuple[list[str], object | None]:
    from docscout.run import scheduler

    try:
        sched = scheduler.for_this_os()
    except scheduler.Unsupported as exc:
        return [f"Daily runs: {exc}"], None
    st = sched.status(scheduler.command(args.config))
    if not st.installed:
        lines = ["Daily runs: off. Turn them on with: docscout schedule install"]
    elif st.running:
        nxt = f" Next check: {st.next_check}." if st.next_check else ""
        lines = [f"Daily runs: on. Every 15 minutes while you're logged in, DocScout checks whether today's run is due.{nxt}"]
    else:
        lines = ["Daily runs: installed, but not running."]
    return lines + [f"  ⚠️  {p}" for p in st.problems], sched if st.installed else None


def _cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.run import daily, lock
    from docscout.run.db import Store
    from docscout.find.health import utcnow

    lines, sched = _schedule_line(cfg, args)
    print("\n".join(lines))
    if not cfg.github_token:
        print("  ⚠️  No GitHub token, so runs can't start. Add one with: docscout init")
    store = Store(store_path())
    try:
        print()
        print(daily.status_report(store, cfg, utcnow(), running=lock.is_held(lock_path()), scheduled=sched is not None))
    finally:
        store.close()
    print(f"\nReports: {cfg.reports_dir} (latest.md is the newest)")
    if sched is not None:
        print(f"Log: {sched.log_hint()}")
    return 0


def _cmd_schedule(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.run import notify, scheduler

    if args.action == "status":
        return _cmd_status(cfg, args)
    try:
        sched = scheduler.for_this_os()
        if args.action == "install":
            messages = sched.install(scheduler.command(args.config), dry_run=args.dry_run)
        else:
            messages = sched.uninstall(dry_run=args.dry_run)
    except scheduler.SchedulerError as exc:
        print(exc, file=sys.stderr)
        return 1
    print("\n".join(messages))
    if args.action == "uninstall" or args.dry_run:
        if args.action == "uninstall" and not args.dry_run:
            print("DocScout won't run by itself any more. Your reports and history are kept.")
        return 0
    print(
        "\nDocScout now checks every 15 minutes, while you're logged in, whether today's run is due.\n"
        "- No manual starts: it also runs after a restart, and waits if you're offline.\n"
        "- You'll get a notification when a run starts and when it finishes.\n"
        "  Turn either off with: docscout set --start-notification off (or --finish-notification off)\n"
        "- Check on it any time with: docscout status"
    )
    if not cfg.github_token:
        print("\n⚠️  No GitHub token yet, so runs can't start. Add one with: docscout init")
    if not notify.send("DocScout daily runs are on", "You'll see a notification like this when a run starts and when it finishes."):
        print("\n⚠️  Couldn't show a desktop notification here (see the message above). Runs still work; check them with docscout status.")
    return 0


def _cmd_mark(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.run.db import Store
    from docscout.find.health import utcnow
    from docscout.find.sources import github_full_name

    name = github_full_name(args.repo) or args.repo.strip().strip("/")
    if name.count("/") != 1:
        print(f"Expected OWNER/REPO or a GitHub URL, got {args.repo!r}", file=sys.stderr)
        return 2
    store = Store(store_path())
    try:
        store.set_status(name, args.status, utcnow(), getattr(args, "reason", None))
    finally:
        store.close()
    word = "done" if args.status == "done" else "ignored"
    print(f"Marked {name} as {word}; it won't appear in future reports.")
    return 0


def _cmd_score(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.analyze.apitypes.openapi import score_spec
    from docscout.analyze.apitypes.rest_prose import analyze_docs

    target = Path(args.target)
    if target.is_file():
        content = target.read_bytes()
        report = score_spec(content, str(target))
        if report is not None:
            print(f"{target}: {report.version}, {report.operations} operations, {'generated' if report.generated else 'hand-written'}")
            print(f"Gap score: {report.gap:.0f}/100 (higher = worse docs)")
            for check, points in report.points.items():
                print(f"  +{points:g} {check}")
            _print_findings(report.findings)
            return 0
        prose = analyze_docs([(str(target), content.decode("utf-8", "replace"))])
        if prose.endpoints:
            print(f"{target}: {len(prose.endpoints)} endpoints, {prose.completeness:.0%} complete")
            _print_findings(prose.findings())
            return 0
        print(f"{target}: not an OpenAPI/Swagger spec (with at least 3 operations), and no endpoints found in it.")
        return 1
    return _score_repo(cfg, args.target)


def _print_findings(findings) -> None:
    for f in findings:
        examples = f" (e.g. {', '.join(f.examples)}{f', +{f.more} more' if f.more else ''})" if f.examples else ""
        print(f"  - {f.text}{examples}")


def _score_repo(cfg: Config, target: str) -> int:
    from docscout.analyze import apitypes
    from docscout.run.db import StoredFinding
    from docscout.find.health import utcnow
    from docscout.run.report import render_item
    from docscout.find.sources import github_full_name

    name = github_full_name(target) or target.strip().strip("/")
    if name.count("/") != 1:
        print(f"Expected a spec file, OWNER/REPO or a GitHub URL, got {target!r}", file=sys.stderr)
        return 2
    types = apitypes.enabled_types(cfg["api_types"])
    now = utcnow()
    with _github(cfg) as gh:
        result = _check_repo(cfg, gh, name, types, now, show=True)
        if result is not None and cfg["checks"]["claim_and_policy"]:
            from docscout.analyze.checks import Checks, paid_checks

            d = result.details
            checks = paid_checks(gh, name, Checks(**d["checks"]), d["check_paths"], d["issues"], d["head_sha"])
            d["checks"] = checks.as_dict()
    if result is None:
        print(f"Not reported: not enough evidence of an API with docs gaps, or fewer than {cfg['report']['min_effort_units']} operations or endpoints need work.")
        return 0
    finding = StoredFinding(name, result.score.total, result.details, 0)
    verdict = _review_one_repo(cfg, finding, {t.key: t for t in types})
    if verdict is None:
        return 1
    finding, accepted = verdict
    print()
    print("\n\n".join(render_item(1, finding, now)))
    if not accepted:
        print(f"\nNot reported: {finding.details['review']['project_type']}, according to the review.")
    return 0


def _check_repo(cfg: Config, gh, name: str, types, now, *, show: bool):
    """Health checks and docs analysis for one repo, as in a run; None if it wouldn't be reported."""
    from docscout.find.discover import evaluate
    from docscout.run.pipeline import analyze
    from docscout.find.sources import Candidate

    ev = evaluate(gh, Candidate(name, "manual", {"full_name": name}), cfg, now, types)
    if show:
        print(f"{name}: {ev.classification.project_type} ({ev.classification.api_type} {ev.classification.api_confidence:.2f})")
        for reason in ev.classification.reasons:
            print(f"  - {reason}")
    if ev.rejected:
        print(f"Not reported: {ev.rejected}")
        return None
    return analyze(gh, ev, cfg, {t.key: t for t in types})


def _cmd_draft(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.analyze import apitypes
    from docscout.llm import review
    from docscout.run.db import Store, StoredFinding
    from docscout.llm.draft import NEW_ISSUE, write_draft
    from docscout.find.health import utcnow
    from docscout.llm import LLMError, LLMUnavailable, memory
    from docscout.find.sources import github_full_name

    name = github_full_name(args.repo) or args.repo.strip().strip("/")
    if name.count("/") != 1:
        print(f"Expected OWNER/REPO or a GitHub URL, got {args.repo!r}", file=sys.stderr)
        return 2
    store = Store(store_path())
    try:
        finding = store.latest_finding(name)
    finally:
        store.close()
    types = apitypes.enabled_types(cfg["api_types"])
    by_key = {t.key: t for t in types}
    label = review.model_label(str(cfg["llm"]["model"]))
    with _github(cfg) as gh:
        if finding is None:
            print(f"{name} isn't in your reports, so DocScout checks it first...", file=sys.stderr)
            result = _check_repo(cfg, gh, name, types, utcnow(), show=False)
            if result is None:
                print("No API docs gaps found to write about.", file=sys.stderr)
                return 1
            finding = StoredFinding(name, result.score.total, result.details, 0)
        api_type = by_key.get(finding.details.get("api_type", ""))
        if api_type is None:
            print(f"{name} was found for an API type that's switched off now.", file=sys.stderr)
            return 1
        short = memory.shortage(cfg["llm"])
        if short:
            print(f"{label} can't write a draft now: {short}. Close some apps and try again.", file=sys.stderr)
            return 1
        print(f"Asking {label} for a draft (under a minute on most laptops)...", file=sys.stderr)
        client = review.open_reviewer(cfg)
        try:
            draft = write_draft(client, gh, finding, api_type.label)
        except (LLMUnavailable, LLMError) as exc:
            print(f"{label} couldn't write a draft: {exc}", file=sys.stderr)
            return 1
        finally:
            client.unload()
            client.close()
    print(f"\nPost it as a {'new issue' if draft.where == NEW_ISSUE else draft.where}:\n  {draft.url}")
    if draft.where == NEW_ISSUE:
        print(f"Title: {draft.title}")
    print("\n" + "-" * 60 + "\n" + draft.message + "\n" + "-" * 60)
    for warning in draft.warnings:
        print(f"⚠️  {warning}")
    print("\nEdit it so it sounds like you, then post it yourself. DocScout never posts anything.")
    return 0


def _review_one_repo(cfg: Config, finding, types_by_key) -> tuple | None:
    """The model's review of one finding, as in a run: (finding with the review, accepted), or None."""
    from docscout.llm import review
    from docscout.run.db import StoredFinding
    from docscout.llm import LLMError, LLMUnavailable, memory

    label = review.model_label(str(cfg["llm"]["model"]))
    short = memory.shortage(cfg["llm"])
    if short:
        print(f"\n{label} can't review it now: {short}. Close some apps and try again.", file=sys.stderr)
        return None
    print(f"\nAsking {label} to review it (under a minute on most laptops)...", file=sys.stderr)
    client = review.open_reviewer(cfg)
    try:
        assessed = review.assess(client, cfg, finding, types_by_key[finding.details["api_type"]])
    except LLMUnavailable as exc:
        print(f"{label} isn't available: {exc}", file=sys.stderr)
        return None
    except LLMError as exc:
        print(f"{label} didn't give a valid answer: {exc}", file=sys.stderr)
        return None
    finally:
        client.unload()
        client.close()
    return StoredFinding(finding.full_name, assessed.score, assessed.details, finding.run_id), assessed.accepted


def _cmd_eval(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.measure.evaluate import TARGET_PRECISION, evaluate_rows, format_report, read_rows

    rows = read_rows(Path(args.csv))
    report = evaluate_rows(rows)
    if args.with_llm:
        args.reclassify = True  # the model reviews the repo data reclassify caches
    if args.reclassify:
        from docscout.analyze import apitypes
        from docscout.find.health import utcnow
        from docscout.measure.reclassify import reclassify

        before = report.overall.precision
        types = apitypes.enabled_types(cfg["api_types"])
        with _github(cfg) as gh:
            rows, changed, missing = reclassify(rows, gh, data_dir() / "eval_cache.json", utcnow(), types, cfg["classify"]["min_confidence"])
        report = evaluate_rows(rows)
        print(f"Precision when sampled: {before:.0%}. With the current classifier:\n" if before is not None else "")
        print(format_report(report))
        if changed:
            print(f"\nPredictions that changed ({len(changed)}):")
            for c in changed:
                verdict = "now right" if c.after == c.label else ("now wrong" if c.before == c.label else "still wrong")
                print(f"  {c.full_name:<45} label {c.label:<12} {c.before} -> {c.after} ({c.confidence_after:.2f}) {verdict}")
        for m in missing:
            print(f"  couldn't fetch {m}")
    else:
        print(format_report(report))
    if args.with_llm:
        return _eval_llm(cfg, args, rows)
    precision = report.overall.precision
    return 0 if precision is not None and precision >= TARGET_PRECISION else 1


def _eval_llm(cfg: Config, args: argparse.Namespace, rows: list) -> int:
    from docscout.analyze import apitypes
    from docscout.measure import llm_eval
    from docscout.llm import review
    from docscout.llm import memory
    from docscout.measure.reclassify import load_cache

    label = review.model_label(str(cfg["llm"]["model"]))
    short = memory.shortage(cfg["llm"])
    if short:
        print(f"\n{label} can't run now: {short}. Close other apps and try again.", file=sys.stderr)
        return 1
    api_type = apitypes.enabled_types(cfg["api_types"])[0]
    floor = float(cfg["classify"]["drop_below"])
    count = sum(1 for r in rows if (r.get("label") or "").strip() and float(r.get("api_confidence") or 0) >= floor)
    think = args.think or str(cfg["llm"]["think"])
    print(
        f"\nReviewing {count} labeled repos with {label} (thinking: {think}). Reviews already cached are reused;\n"
        f"new ones take about 45 s each on a small laptop. Ctrl+C stops, keeping what's done.",
        file=sys.stderr,
    )
    client = review.open_reviewer(cfg)
    try:
        result = llm_eval.run(
            rows, load_cache(data_dir() / "eval_cache.json"), client, cfg, api_type,
            think=think, cache_path=data_dir() / "llm_eval_cache.json", progress=lambda m: print(m, file=sys.stderr),
        )  # fmt: skip
    except KeyboardInterrupt:
        print("\nStopped. The reviews so far are cached; run the same command to continue.", file=sys.stderr)
        return 130
    finally:
        client.close()
    before, after = llm_eval.compare(rows, result)
    print()
    print(llm_eval.format_result(result, before, after))
    return 0 if not result.stopped else 1


def _cmd_bench_llm(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.measure import bench
    from docscout.llm import make_client

    llm_cfg = dict(cfg["llm"])
    if args.provider:
        llm_cfg["provider"] = args.provider
    if args.model:
        llm_cfg["model"] = args.model
    if args.base_url:
        llm_cfg["base_url"] = args.base_url
    client = make_client(llm_cfg, api_key=cfg.secret(llm_cfg["api_key_env"]))
    print(f"Benchmarking {client.name} with {args.runs} sample reviews...", file=sys.stderr)
    try:
        result = bench.run(client, runs=args.runs, readme_chars=int(llm_cfg.get("readme_chars", 1500)))
    finally:
        client.close()
    print(bench.format_result(result, client.name))
    return 0 if result.seconds else 1


def _add_profile_flags(p: argparse.ArgumentParser) -> None:
    group = p.add_argument_group("profile overrides (for this command only; `init` saves them)")
    group.add_argument("--languages", help='languages you know, comma-separated, e.g. "python, go" ("any" to clear)')
    group.add_argument("--only-these-languages", action="store_true", help="exclude projects in other languages")
    group.add_argument("--sizes", help="project sizes: small, medium, large, huge (comma-separated)")
    group.add_argument("--llm", choices=["ollama", "openai_compatible"], help="the model that reviews projects: local (ollama) or hosted")
    group.add_argument("--model", dest="llm_model", help="LLM model name")
    group.add_argument("--base-url", dest="llm_base_url", help="LLM API address, e.g. https://api.groq.com/openai/v1")


def profile_overrides(args: argparse.Namespace) -> dict:
    overrides: dict = {}
    languages = getattr(args, "languages", None)
    if languages is not None:
        overrides["languages"] = [] if languages.strip().lower() == "any" else [x for x in languages.split(",") if x.strip()]
    if getattr(args, "only_these_languages", False):
        overrides["language_filter"] = "require"
    sizes = getattr(args, "sizes", None)
    if sizes:
        overrides["project_sizes"] = [x.strip().lower() for x in sizes.split(",") if x.strip()]
    return overrides


def llm_overrides(args: argparse.Namespace) -> dict:
    overrides: dict = {}
    if getattr(args, "llm", None):
        overrides["provider"] = args.llm
    if getattr(args, "llm_model", None):
        overrides["model"] = args.llm_model
    if getattr(args, "llm_base_url", None):
        overrides["base_url"] = args.llm_base_url
    return overrides


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="docscout", description="Find open-source APIs with documentation gaps you can fix (REST first)."
    )
    parser.add_argument("--version", action="version", version=f"docscout {__version__}")
    parser.add_argument("--config", type=Path, help="path to a config.toml (default: the user config folder)")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="set up DocScout (at most 3 questions)")
    p.add_argument("-y", "--yes", action="store_true", help="don't ask; save the current values plus any flags below")
    _add_profile_flags(p)
    p.set_defaults(func=_cmd_init)

    p = sub.add_parser("set", help="change settings without questions, e.g. set --languages go")
    _add_profile_flags(p)
    group = p.add_argument_group("notifications for the daily run")
    group.add_argument("--start-notification", choices=["on", "off"], help="notify when the daily run starts")
    group.add_argument("--finish-notification", choices=["on", "off"], help="notify when it finishes, with the report's location")
    p.set_defaults(func=_cmd_set)

    p = sub.add_parser("profile", help="show what DocScout is looking for, in plain words")
    p.set_defaults(func=_cmd_profile)

    p = sub.add_parser("run", help="find projects with API docs gaps and write a report")
    p.add_argument("--limit", type=int, help="repos to check this time (default: [discovery] daily_repo_budget); 0 only reviews the projects waiting for the model")
    p.add_argument("--sources", help="comma-separated sources (default: [discovery] sources)")
    p.add_argument("--if-due", action="store_true", help="only run if today's run is due (what the daily schedule uses)")
    _add_profile_flags(p)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("status", help="today's progress, the daily schedule and recent runs")
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("schedule", help="run DocScout every day by itself (Linux now; macOS and Windows later)")
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--dry-run", action="store_true", help="show what would change, without changing anything")
    p.set_defaults(func=_cmd_schedule)

    p = sub.add_parser("draft", help="a first message to the maintainers of a project you picked, for you to edit and post")
    p.add_argument("repo", help="OWNER/REPO or a GitHub URL")
    p.set_defaults(func=_cmd_draft)

    p = sub.add_parser("done", help="mark a project as done; it won't be reported again")
    p.add_argument("repo", help="OWNER/REPO or a GitHub URL")
    p.set_defaults(func=_cmd_mark, status="done")

    p = sub.add_parser("ignore", help="hide a project from future reports")
    p.add_argument("repo", help="OWNER/REPO or a GitHub URL")
    p.add_argument("--reason", help="why, e.g. \"not a REST API\" (kept for tuning DocScout)")
    p.set_defaults(func=_cmd_mark, status="ignored")

    p = sub.add_parser("score", help="analyze one OpenAPI spec file, Markdown file or repo (OWNER/REPO)")
    p.add_argument("target")
    _add_profile_flags(p)
    p.set_defaults(func=_cmd_score)

    p = sub.add_parser("discover", help="draw a sample of repos to label (stage M0)")
    _add_profile_flags(p)
    p.add_argument("--sample", type=int, default=60, help="how many gate-passing repos to collect (default 60)")
    p.add_argument("--csv", default="sample.csv", help="output CSV (default sample.csv)")
    p.add_argument("--sources", help="comma-separated sources (default: [discovery] sources)")
    p.add_argument("--seed", type=int, default=None, help="random seed, to reproduce a sample")
    p.set_defaults(func=_cmd_discover)

    p = sub.add_parser("eval", help="measure classifier accuracy on a labeled sample CSV")
    p.add_argument("csv")
    p.add_argument("--reclassify", action="store_true", help="re-run the current classifier on the labeled repos (data is cached after the first run)")
    p.add_argument("--llm", dest="with_llm", action="store_true", help="also measure the model's review on the labeled repos (about 45 s per repo on a small laptop; cached)")
    p.add_argument("--think", choices=["off", "borderline", "on"], help="thinking for --llm (default: [llm] think)")
    p.set_defaults(func=_cmd_eval)

    p = sub.add_parser("bench-llm", help="measure LLM speed and memory on this machine")
    p.add_argument("--runs", type=int, default=3, choices=[1, 2, 3])
    p.add_argument("--provider", choices=["ollama", "openai_compatible"])
    p.add_argument("--model")
    p.add_argument("--base-url")
    p.set_defaults(func=_cmd_bench_llm)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        cfg = load_config(args.config, profile_overrides(args))
        if llm := llm_overrides(args):
            cfg.values["llm"].update(llm)
        return args.func(cfg, args)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        if getattr(args, "if_due", False):  # nobody is watching the terminal: say so on screen
            _alert_config_error(exc)
        return 2


def _alert_config_error(exc: ConfigError) -> None:
    from docscout.run import daily, notify
    from docscout.run.db import Store
    from docscout.find.health import utcnow

    store = Store(store_path())
    try:
        daily.alert(store, notify.send, utcnow(), "config", "DocScout needs attention", f"Your settings have a problem, so the daily run can't start: {exc}")
    finally:
        store.close()


def main_bg() -> int:
    """Windowless entry point (``docscout-bg``): there is no console, so log to a file."""
    path = log_dir()
    path.mkdir(parents=True, exist_ok=True)
    stream = open(path / "docscout.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = stream
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    return main()


if __name__ == "__main__":
    sys.exit(main())
