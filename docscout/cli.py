"""Command-line entry points.

``init`` and ``profile`` set up and show what the user wants. Stage M0 commands:
``discover`` (draw a sample to label), ``eval`` (measure accuracy on the labeled sample)
and ``bench-llm`` (measure LLM speed and memory).
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from pathlib import Path

from docscout import __version__
from docscout.config import Config, load_config, log_dir, user_config_path
from docscout.errors import ConfigError

log = logging.getLogger("docscout")


def _cmd_init(cfg: Config, args: argparse.Namespace) -> int:
    from docscout import setup_wizard

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
    print("\nNext: docscout discover --sample 60 --csv sample.csv")
    return 0


def _cmd_set(cfg: Config, args: argparse.Namespace) -> int:
    from docscout import setup_wizard

    if not profile_overrides(args) and not llm_overrides(args):
        print('Nothing to change. For example: docscout set --languages "python, go" --sizes small,medium', file=sys.stderr)
        return 2
    _save_and_show(cfg, setup_wizard.answers_from_config(cfg), args.config or user_config_path())
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
    from docscout import setup_wizard
    from docscout.apitypes import enabled_types
    from docscout.profile import describe

    print()
    for message in setup_wizard.save(answers, cfg, path):
        print(message)
    saved = load_config(path)
    print()
    print(describe(saved.values, enabled_types(saved["api_types"]), has_token=bool(saved.github_token), config_path=str(path)))


def _cmd_profile(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.apitypes import enabled_types
    from docscout.profile import describe

    path = str(cfg.path) if cfg.path else None
    print(describe(cfg.values, enabled_types(cfg["api_types"]), has_token=bool(cfg.github_token), config_path=path))
    print('\nChange these with docscout set, e.g. docscout set --languages "python, go"')
    return 0


def _cmd_discover(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.discover import LABELS, draw_sample, write_rejected, write_sample
    from docscout.github import GitHub
    from docscout.health import utcnow

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
    print(f"\nNext: open {out}, fill the 'label' column with one of: {', '.join(LABELS)}")
    print(f"Then run: docscout eval {out}")
    return 0 if sample.passed else 1


def _cmd_eval(cfg: Config, args: argparse.Namespace) -> int:
    from docscout.evaluate import TARGET_PRECISION, evaluate_csv, format_report

    report = evaluate_csv(Path(args.csv))
    print(format_report(report))
    precision = report.overall.precision
    return 0 if precision is not None and precision >= TARGET_PRECISION else 1


def _cmd_bench_llm(cfg: Config, args: argparse.Namespace) -> int:
    from docscout import bench
    from docscout.llm import make_client

    llm_cfg = dict(cfg["llm"])
    if args.provider:
        llm_cfg["provider"] = args.provider
    if args.model:
        llm_cfg["model"] = args.model
    if args.base_url:
        llm_cfg["base_url"] = args.base_url
    client = make_client(llm_cfg, api_key=cfg.secret(llm_cfg["api_key_env"]))
    if client is None:
        print("LLM provider is 'none'; nothing to benchmark.", file=sys.stderr)
        return 1
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
    group.add_argument("--llm", choices=["ollama", "openai_compatible", "none"], help="LLM provider")
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
    p.set_defaults(func=_cmd_set)

    p = sub.add_parser("profile", help="show what DocScout is looking for, in plain words")
    p.set_defaults(func=_cmd_profile)

    p = sub.add_parser("discover", help="draw a sample of repos to label (stage M0)")
    _add_profile_flags(p)
    p.add_argument("--sample", type=int, default=60, help="how many gate-passing repos to collect (default 60)")
    p.add_argument("--csv", default="sample.csv", help="output CSV (default sample.csv)")
    p.add_argument("--sources", help="comma-separated sources (default: [discovery] sources)")
    p.add_argument("--seed", type=int, default=None, help="random seed, to reproduce a sample")
    p.set_defaults(func=_cmd_discover)

    p = sub.add_parser("eval", help="measure classifier accuracy on a labeled sample CSV")
    p.add_argument("csv")
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
        return 2


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
