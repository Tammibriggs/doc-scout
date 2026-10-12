"""``docscout init``: a short setup that writes the user's profile.

It asks at most three questions, and usually fewer: what to document (only when there's
a choice), which LLM, and a GitHub token (only when none is set). Everything else has a
default that a flag can change (``--languages``, ``--sizes``, ``--model``, ...); a flag
also skips its question. Answers go to the user's config.toml (``[profile]`` and
``[llm]``), secrets to secrets.env. With ``--yes`` nothing is asked.
"""

from __future__ import annotations

import getpass
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from docscout import profile as profile_mod
from docscout.apitypes import REGISTRY, enabled_types
from docscout.config import GITHUB_TOKEN_VARS, Config, save_secrets, save_user_config
from docscout.errors import ConfigError
from docscout.github import AuthError, GitHub
from docscout.languages import parse_list

Prompt = Callable[[str], str]

TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"
DEFAULT_OLLAMA_MODEL = "gemma4:e2b"
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_HOSTED_URL = "https://openrouter.ai/api/v1"
PLANNED_TYPES = "GraphQL, gRPC, event APIs and library/SDK docs are planned"
CONFIG_HEADER = (
    "# DocScout settings, written by `docscout init`. Run it again to change them, or edit this file.\n"
    "# Any key from the package's default_config.toml can be added here to override it.\n\n"
)


@dataclass
class Answers:
    api_types: list[str]
    languages: list[str]
    language_filter: str
    project_sizes: list[str]
    llm: dict[str, str]
    github_token: str | None = None  # None: keep whatever is set
    llm_api_key: str | None = None
    notes: list[str] = field(default_factory=list)  # things to tell the user after saving


def answers_from_config(cfg: Config) -> Answers:
    """The current settings (including any command-line flags), for --yes."""
    profile = cfg["profile"]
    llm = cfg["llm"]
    return Answers(
        api_types=list(profile["api_types"]),
        languages=list(profile["languages"]),
        language_filter=profile["language_filter"],
        project_sizes=list(profile["project_sizes"]),
        llm={"provider": llm["provider"], "model": llm["model"], "base_url": llm["base_url"]},
    )


# ---------------------------------------------------------------------- parsing helpers


def parse_choices(text: str, options: list[str]) -> list[str]:
    """'1,3' or 'ollama, none' -> ['ollama', 'none'], in the options' order."""
    picked = set()
    for item in text.replace(" ", ",").split(","):
        item = item.strip().lower()
        if not item:
            continue
        if item.isdigit() and 1 <= int(item) <= len(options):
            picked.add(options[int(item) - 1])
        elif item in options:
            picked.add(item)
        else:
            raise ValueError(item)
    return [o for o in options if o in picked]


def _ask_until_valid(ask: Prompt, say: Callable[[str], None], prompt: str, parse: Callable[[str], Any]) -> Any:
    while True:
        try:
            return parse(ask(prompt))
        except ValueError as exc:
            say(f"  Sorry, I didn't understand {str(exc)!r}. Please try again.")


# ---------------------------------------------------------------------- checks


def list_ollama_models(base_url: str) -> list[str] | None:
    """Installed Ollama models, or None if Ollama isn't reachable."""
    try:
        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=3)
        resp.raise_for_status()
    except httpx.HTTPError:
        return None
    return [m.get("name", "") for m in resp.json().get("models", [])]


def verify_github_token(token: str) -> tuple[bool | None, str]:
    """(True, message) if GitHub accepts the token, (False, ...) if it rejects it, (None, ...) if unknown."""
    try:
        with GitHub(token) as gh:
            limit = gh.rate_limit()["core"]["limit"]
    except AuthError:
        return False, "GitHub rejected this token, so it was not saved. Check it was copied completely."
    except (httpx.HTTPError, KeyError) as exc:
        return None, f"Couldn't check the token with GitHub ({exc.__class__.__name__}); saved it anyway."
    return True, f"GitHub token works ({limit} requests an hour)."


# ---------------------------------------------------------------------- questions

MAX_QUESTIONS = 3


def plan_questions(cfg: Config, fixed: frozenset[str] = frozenset()) -> list[str]:
    """Which questions this setup will ask, in order. Everything else uses a default.

    - "api_type": only when there's more than one API type to choose from.
    - "llm": unless --llm was given.
    - "token": only when no GitHub token is set yet.
    ``fixed`` holds settings given as command-line flags (e.g. "llm.provider").
    """
    steps = []
    if len(REGISTRY) > 1 and "api_types" not in fixed:
        steps.append("api_type")
    if "llm.provider" not in fixed:
        steps.append("llm")
    if not cfg.github_token:
        steps.append("token")
    return steps


def ask_interactively(
    cfg: Config,
    *,
    fixed: frozenset[str] = frozenset(),
    ask: Prompt = input,
    ask_secret: Prompt = getpass.getpass,
    say: Callable[[str], None] = print,
    ollama_models: Callable[[str], list[str] | None] = list_ollama_models,
) -> Answers:
    """Ask at most three questions; follow-ups only appear when the chosen option needs them
    (a language for library/SDK docs, a model and API key for a hosted LLM)."""
    current = answers_from_config(cfg)
    steps = plan_questions(cfg, fixed)
    assert len(steps) <= MAX_QUESTIONS
    if steps:
        count = f"{len(steps)} question{'s' if len(steps) > 1 else ''}"
        say(f"DocScout setup: {count}. Press Enter to accept the default in [brackets].")

    def header(step: str, text: str) -> None:
        say(f"\n{steps.index(step) + 1}/{len(steps)}. {text}")

    notes: list[str] = []

    # What to document
    api_types = current.api_types
    if "api_type" in steps:
        available = list(REGISTRY)
        header("api_type", "What do you want to document?")
        for i, key in enumerate(available, 1):
            say(f"   {i}) {REGISTRY[key].label}")
        default = ",".join(str(available.index(k) + 1) for k in current.api_types if k in available) or "1"
        api_types = _ask_until_valid(ask, say, f"   Choose one or more [{default}]: ", lambda t: parse_choices(t or default, available))
    types = enabled_types({"enabled": api_types})

    # Follow-up: only types that need your language (library/SDK docs) ask for it.
    languages = current.languages
    if any(t.language_mode == "require" for t in types) and not languages and "languages" not in fixed:
        while not languages:
            text = ask("   Which programming languages? e.g. python, go: ")
            languages = [lang.name for lang in parse_list(text)]

    # LLM
    llm = dict(current.llm)
    if "llm" in steps:
        providers = ["ollama", "openai_compatible", "none"]
        header("llm", "Which LLM should review projects and suggest first steps?")
        say(f"   1) Local, with Ollama ({DEFAULT_OLLAMA_MODEL}): free and private, but slow on small machines")
        say("   2) Hosted: an OpenAI-compatible API such as OpenRouter (needs an API key)")
        say("   3) None: code-based results only")
        default = str(providers.index(current.llm["provider"]) + 1)
        llm["provider"] = _ask_until_valid(ask, say, f"   Choice [{default}]: ", lambda t: _one(parse_choices(t or default, providers), t))
    switched = llm["provider"] != current.llm["provider"]
    llm_api_key = None
    if llm["provider"] == "ollama":
        if switched:
            llm["base_url"] = DEFAULT_OLLAMA_URL
            if "llm.model" not in fixed:
                llm["model"] = DEFAULT_OLLAMA_MODEL
        installed = ollama_models(llm["base_url"])
        if installed is None:
            notes.append(f"Ollama isn't running at {llm['base_url']}. Install it from https://ollama.com, or choose a hosted model.")
        elif llm["model"] not in installed:
            notes.append(f"The LLM model isn't installed yet. Run: ollama pull {llm['model']}")
        else:
            notes.append(f"Ollama model {llm['model']} is installed.")
    elif llm["provider"] == "openai_compatible":
        if switched:
            if "llm.base_url" not in fixed:
                llm["base_url"] = DEFAULT_HOSTED_URL
            if "llm.model" not in fixed:
                llm["model"] = ""
        while not llm["model"]:
            llm["model"] = ask(f"   Model name, as {_host(llm['base_url'])} writes it: ").strip()
        key_env = cfg["llm"]["api_key_env"]
        if not cfg.secret(key_env):
            llm_api_key = ask_secret("   API key (hidden): ").strip() or None
            if not llm_api_key:
                notes.append(f"No API key saved. Run `docscout init` again, or set {key_env}.")

    # GitHub token
    github_token = None
    if "token" in steps:
        header("token", "GitHub token, so DocScout can search more than 60 times an hour.")
        say(f"   Create one with read-only access to public repositories: {TOKEN_URL}")
        github_token = ask_secret("   Paste it (hidden), or press Enter to skip: ").strip() or None

    return Answers(api_types, languages, current.language_filter, current.project_sizes, llm, github_token, llm_api_key, notes)


def _one(choices: list[str], text: str) -> str:
    if len(choices) != 1:
        raise ValueError(text)
    return choices[0]


def _host(base_url: str) -> str:
    return base_url.split("//", 1)[-1].split("/", 1)[0]


# ---------------------------------------------------------------------- saving


def save(
    answers: Answers,
    cfg: Config,
    config_path: Path,
    *,
    verify_token: Callable[[str], tuple[bool | None, str]] = verify_github_token,
) -> list[str]:
    """Write config.toml and secrets.env. Returns messages for the user."""
    messages = list(answers.notes)
    updates = {
        "profile": {
            "api_types": answers.api_types,
            "languages": answers.languages,
            "language_filter": answers.language_filter,
            "project_sizes": answers.project_sizes,
        },
        "llm": answers.llm,
    }
    # Validate before writing anything.
    profile_mod.apply({"profile": dict(updates["profile"])})
    enabled_types({"enabled": answers.api_types})

    backup = save_user_config(config_path, updates, header=CONFIG_HEADER)
    messages.append(f"Saved your settings to {config_path}" + (f" (previous version: {backup.name})" if backup else ""))

    secrets: dict[str, str] = {}
    if answers.github_token:
        ok, message = verify_token(answers.github_token)
        messages.append(message)
        if ok is not False:
            secrets[GITHUB_TOKEN_VARS[1]] = answers.github_token
    if answers.llm_api_key:
        secrets[cfg["llm"]["api_key_env"]] = answers.llm_api_key
    if secrets:
        save_secrets(cfg.secrets_path, secrets)
        messages.append(f"Saved secrets to {cfg.secrets_path} (readable only by you).")
    return messages


__all__ = ["MAX_QUESTIONS", "Answers", "ConfigError", "answers_from_config", "ask_interactively", "plan_questions", "save", "verify_github_token"]
