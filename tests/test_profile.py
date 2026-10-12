import os
import random
import tomllib
from datetime import date

import pytest
from test_discover_eval import GOOD_REPO, FakeGitHub

from docscout import setup_wizard
from docscout.apitypes import REGISTRY, ApiType, enabled_types
from docscout.apitypes.rest import RestApi
from docscout.config import Config, load_config, load_defaults, save_secrets, save_user_config
from docscout.discover import evaluate, source_candidates
from docscout.errors import ConfigError
from docscout.languages import normalize, parse_list
from docscout.profile import describe, language_policy
from docscout.sources import Candidate


def make_cfg(tmp_path, **profile):
    values = load_defaults()
    values["profile"].update(profile)
    return Config(values=values, path=None, secrets_path=tmp_path / "secrets.env")


class LibraryDocs(ApiType):
    """Stand-in for a future library/SDK docs type, which needs the contributor's language."""

    key = "library"
    label = "Library/SDK"
    llm_style = "none"
    language_mode = "require"

    def evidence(self, signals):
        from docscout.evidence import Evidence

        return Evidence()


# ---------------------------------------------------------------------- languages


def test_language_aliases_and_unknown_names():
    assert [lang.name for lang in parse_list("py, golang, C#, ts, Python")] == ["Python", "Go", "C#", "TypeScript"]
    assert normalize("c++").slug == "cpp" and normalize("csharp").name == "C#"
    odd = normalize("Fortan")
    assert not odd.known and odd.name == "Fortan" and odd.slug == "fortan"
    assert normalize("Go").matches("go") and not normalize("Go").matches(None)


# ---------------------------------------------------------------------- profile -> settings


def test_project_sizes_set_search_bands_and_gate_ranges(tmp_path):
    cfg = make_cfg(tmp_path, project_sizes=["large", "small"])
    assert cfg["profile"]["project_sizes"] == ["small", "large"]
    assert cfg["discovery"]["star_bands"] == [(20, 50), (50, 200), (1000, 5000)]
    assert cfg["health"]["star_ranges"] == [(20, 200), (1000, 5000)]
    assert make_cfg(tmp_path, project_sizes=["huge"])["health"]["star_ranges"] == [(5000, None)]


def test_invalid_profile_values_are_reported(tmp_path):
    with pytest.raises(ConfigError, match="unknown project size"):
        make_cfg(tmp_path, project_sizes=["tiny"])
    with pytest.raises(ConfigError, match="language_filter"):
        make_cfg(tmp_path, language_filter="sometimes")
    with pytest.raises(ConfigError, match="at least one API type"):
        make_cfg(tmp_path, api_types=[])


def test_languages_are_preferred_for_rest_and_required_for_library_docs(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path, languages=["py", "golang"])
    assert cfg["profile"]["languages"] == ["Python", "Go"]
    rest = language_policy(cfg["profile"], [RestApi()])
    assert not rest.required and rest.search_qualifiers() == ""
    library = language_policy(cfg["profile"], [LibraryDocs()])
    assert library.required and library.search_qualifiers() == "language:python language:go"
    # An explicit choice overrides each type's default.
    strict = make_cfg(tmp_path, languages=["python"], language_filter="require")
    assert language_policy(strict["profile"], [RestApi()]).required


def test_describe_in_plain_words(tmp_path):
    cfg = make_cfg(tmp_path, languages=["python"], project_sizes=["small"])
    text = describe(cfg.values, [RestApi()], has_token=False, config_path=None)
    assert "Languages:      any, with Python ranked higher" in text
    assert "small (20–200★)" in text and "not set (run docscout init)" in text


def test_command_line_overrides_win_for_one_run(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[profile]\nlanguages = ["Go"]\n')
    assert load_config(path)["profile"]["languages"] == ["Go"]
    assert load_config(path, {"languages": ["rust"]})["profile"]["languages"] == ["Rust"]


# ---------------------------------------------------------------------- discovery


class LanguageGitHub(FakeGitHub):
    def __init__(self, breakdown, **kwargs):
        super().__init__(**kwargs)
        self.breakdown = breakdown

    def get_languages(self, name):
        self.used.append("languages")
        return self.breakdown


def test_required_language_rejects_other_languages_before_costly_calls(tmp_path, now):
    cfg = make_cfg(tmp_path, languages=["rust"], language_filter="require")
    gh = LanguageGitHub({"Go": 9000, "Rust": 100})
    ev = evaluate(gh, Candidate("org/app", "repo_search", GOOD_REPO), cfg, now)
    assert ev.rejected == "language: Go is not one of yours"
    assert "pulls" not in gh.used


def test_required_language_counts_a_large_share_not_just_the_main_language(tmp_path, now):
    cfg = make_cfg(tmp_path, languages=["python"], language_filter="require")
    repo = dict(GOOD_REPO, language="TypeScript")  # e.g. a Python backend with a big frontend
    gh = LanguageGitHub({"TypeScript": 6000, "Python": 4000})
    ev = evaluate(gh, Candidate("org/app", "repo_search", repo), cfg, now)
    assert ev.rejected is None and ev.language_match is True


def test_preferred_language_only_marks_the_match_and_costs_nothing(tmp_path, now):
    cfg = make_cfg(tmp_path, languages=["rust"])
    gh = LanguageGitHub({})
    ev = evaluate(gh, Candidate("org/app", "repo_search", GOOD_REPO), cfg, now)
    assert ev.rejected is None and ev.language_match is False
    assert "languages" not in gh.used


def test_required_languages_narrow_the_searches(tmp_path):
    cfg = make_cfg(tmp_path, languages=["python", "go"], language_filter="require")
    types = enabled_types(cfg["api_types"])
    seen = []

    class RecordingGitHub:
        def search_repos(self, query, **kwargs):
            seen.append(query)
            return 0, []

        def search_issues(self, query, **kwargs):
            seen.append(query)
            return 0, []

    policy = language_policy(cfg["profile"], types)
    for source in ("repo_search", "help_requested"):
        list(source_candidates(source, RecordingGitHub(), cfg, random.Random(1), date(2026, 10, 12), types, policy))
    assert seen and all("language:python language:go" in q for q in seen)


# ---------------------------------------------------------------------- saving settings


def test_save_user_config_keeps_other_settings_and_backs_up(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[discovery]\ndaily_repo_budget = 30\n\n[profile]\nlanguages = ["Go"]\n')
    backup = save_user_config(path, {"profile": {"languages": ["Python"]}})
    saved = tomllib.loads(path.read_text())
    assert saved["discovery"]["daily_repo_budget"] == 30
    assert saved["profile"]["languages"] == ["Python"]
    assert backup and 'languages = ["Go"]' in backup.read_text()


def test_save_secrets_updates_lines_and_is_private(tmp_path):
    path = tmp_path / "secrets.env"
    path.write_text("# mine\nGITHUB_TOKEN=old\nOTHER=1\n")
    save_secrets(path, {"GITHUB_TOKEN": "new", "DOCSCOUT_LLM_API_KEY": "k"})
    assert path.read_text() == "# mine\nGITHUB_TOKEN=new\nOTHER=1\nDOCSCOUT_LLM_API_KEY=k\n"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600


# ---------------------------------------------------------------------- the wizard


def scripted(answers):
    queue = list(answers)

    def ask(prompt):
        assert queue, f"unexpected question: {prompt!r}"
        return queue.pop(0)

    return ask


def run_wizard(cfg, asks, secrets=(), fixed=frozenset(), models=("gemma4:e2b",)):
    said = []
    answers = setup_wizard.ask_interactively(
        cfg,
        fixed=fixed,
        ask=scripted(asks),
        ask_secret=scripted(secrets),
        say=said.append,
        ollama_models=lambda url: list(models) if models is not None else None,
    )
    numbered = [line for line in said if line.lstrip("\n")[:2].rstrip(".").replace("/", "").isdigit()]
    return answers, said, numbered


@pytest.fixture(autouse=True)
def no_token_in_env(monkeypatch):
    for name in ("GITHUB_TOKEN", "DOCSCOUT_GITHUB_TOKEN", "DOCSCOUT_LLM_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_rest_today_asks_only_llm_and_token(tmp_path):
    cfg = make_cfg(tmp_path)
    answers, said, numbered = run_wizard(cfg, asks=[""], secrets=["ghp_example"])  # Enter = local Ollama
    assert said[0] == "DocScout setup: 2 questions. Press Enter to accept the default in [brackets]."
    assert [line.strip().split(".")[0] for line in numbered] == ["1/2", "2/2"]
    assert answers.llm["provider"] == "ollama" and answers.github_token == "ghp_example"
    # Defaults for everything that wasn't asked.
    assert answers.languages == [] and answers.project_sizes == ["small", "medium", "large"]

    path = tmp_path / "config.toml"
    messages = setup_wizard.save(answers, cfg, path, verify_token=lambda t: (True, "GitHub token works (5000 requests an hour)."))
    assert "GITHUB_TOKEN=ghp_example" in cfg.secrets_path.read_text()
    assert "Ollama model gemma4:e2b is installed." in messages


def test_existing_token_means_one_question(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.secrets_path.write_text("GITHUB_TOKEN=already\n")
    answers, said, numbered = run_wizard(cfg, asks=["3"])
    assert said[0].startswith("DocScout setup: 1 question.")
    assert answers.llm["provider"] == "none" and answers.github_token is None


def test_flags_answer_questions_in_advance(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.secrets_path.write_text("GITHUB_TOKEN=already\n")
    answers, said, numbered = run_wizard(cfg, asks=[], fixed=frozenset({"llm.provider"}))
    assert numbered == [] and said == []


def test_hosted_llm_asks_for_model_and_key_as_follow_ups(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.secrets_path.write_text("GITHUB_TOKEN=already\n")
    answers, said, numbered = run_wizard(cfg, asks=["2", "", "some/model"], secrets=["sk-123"])  # "" = model is required, asked again
    assert len(numbered) == 1
    assert answers.llm == {"provider": "openai_compatible", "model": "some/model", "base_url": "https://openrouter.ai/api/v1"}
    assert answers.llm_api_key == "sk-123"


def test_bad_choice_is_asked_again(tmp_path):
    cfg = make_cfg(tmp_path)
    answers, said, _ = run_wizard(cfg, asks=["7", "none"], secrets=[""])
    assert any("didn't understand '7'" in line for line in said)
    assert answers.llm["provider"] == "none"


def test_rejected_token_is_not_saved(tmp_path):
    cfg = make_cfg(tmp_path)
    answers, _, _ = run_wizard(cfg, asks=["3"], secrets=["bad-token"])
    messages = setup_wizard.save(answers, cfg, tmp_path / "config.toml", verify_token=lambda t: (False, "GitHub rejected this token"))
    assert "GitHub rejected this token" in messages
    assert not cfg.secrets_path.exists()


def test_library_docs_path_asks_for_language_and_stays_within_three(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "library", LibraryDocs)
    cfg = make_cfg(tmp_path)
    answers, said, numbered = run_wizard(cfg, asks=["2", "py, golang", "3"], secrets=[""])
    assert len(numbered) == 3 <= setup_wizard.MAX_QUESTIONS
    assert answers.api_types == ["library"] and answers.languages == ["Python", "Go"]


def test_no_path_asks_more_than_three(tmp_path, monkeypatch):
    monkeypatch.setitem(REGISTRY, "library", LibraryDocs)
    cfg = make_cfg(tmp_path)
    assert setup_wizard.plan_questions(cfg) == ["api_type", "llm", "token"]
    assert len(setup_wizard.plan_questions(cfg)) <= setup_wizard.MAX_QUESTIONS


def test_llm_question_shows_whether_ollama_is_ready(tmp_path):
    cfg = make_cfg(tmp_path)
    _, said, _ = run_wizard(cfg, asks=["1"], secrets=[""], models=None)
    assert any("Status: Ollama isn't installed or running on this machine" in line for line in said)
    _, said, _ = run_wizard(cfg, asks=["1"], secrets=[""], models=["llama3:8b"])
    assert any("Status: Ollama found, but gemma4:e2b isn't downloaded yet" in line for line in said)
    answers, said, _ = run_wizard(cfg, asks=["1"], secrets=[""], models=None)
    assert any("Until then, reports use code-based results only." in note for note in answers.notes)


def test_set_model_warns_when_it_is_not_downloaded(tmp_path, monkeypatch, capsys):
    from docscout import cli

    monkeypatch.setattr(setup_wizard, "list_ollama_models", lambda url: ["gemma4:e2b"])
    path = tmp_path / "config.toml"
    assert cli.main(["--config", str(path), "set", "--model", "tiny:1b"]) == 0
    out = capsys.readouterr().out
    assert "tiny:1b isn't downloaded yet. Run: ollama pull tiny:1b" in out
    assert tomllib.loads(path.read_text())["llm"]["model"] == "tiny:1b"


def test_choosing_local_llm_explains_how_to_change_the_model(tmp_path):
    cfg = make_cfg(tmp_path)
    answers, _, _ = run_wizard(cfg, asks=["1"], secrets=[""])
    hint = next(n for n in answers.notes if n.startswith("Using the local model gemma4:e2b"))
    assert "ollama pull NAME" in hint and "docscout set --model NAME" in hint
    assert hint.endswith("Choose a model that runs smoothly on your system.")
