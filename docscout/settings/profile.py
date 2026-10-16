"""The user's profile: what they want DocScout to find, in plain terms.

The ``[profile]`` section is the only part of the config most people touch (``docscout
init`` writes it). :func:`apply` turns it into the internal settings the rest of the
code reads, such as enabled API types, search star bands and the star ranges the
health gate accepts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from docscout.errors import ConfigError
from docscout.settings.languages import Language, parse_list, search_qualifiers

if TYPE_CHECKING:
    from docscout.analyze.apitypes import ApiType

# (min stars, max stars or None for no upper limit)
SIZE_RANGES: dict[str, tuple[int, int | None]] = {
    "small": (20, 200),
    "medium": (200, 1000),
    "large": (1000, 5000),
    "huge": (5000, None),
}
# Search bands per size, narrow enough to stay under GitHub's 1000-results-per-query cap.
SIZE_BANDS: dict[str, list[tuple[int, int | None]]] = {
    "small": [(20, 50), (50, 200)],
    "medium": [(200, 1000)],
    "large": [(1000, 5000)],
    "huge": [(5000, None)],
}
SIZE_LABELS = {"small": "20–200★", "medium": "200–1,000★", "large": "1,000–5,000★", "huge": "5,000★ and up"}
DEFAULT_SIZES = ["small", "medium", "large"]
LANGUAGE_FILTERS = ("auto", "require", "prefer")


def apply(values: dict[str, Any]) -> None:
    """Validate ``values["profile"]`` and write the settings derived from it, in place."""
    profile = values.setdefault("profile", {})

    types = list(profile.get("api_types") or [])
    if not types:
        raise ConfigError('[profile] api_types must list at least one API type, e.g. api_types = ["rest"]')
    values.setdefault("api_types", {})["enabled"] = types

    sizes = list(profile.get("project_sizes") or DEFAULT_SIZES)
    unknown = [s for s in sizes if s not in SIZE_RANGES]
    if unknown:
        raise ConfigError(f"unknown project size(s) {', '.join(unknown)}; choose from {', '.join(SIZE_RANGES)}")
    ordered = [s for s in SIZE_RANGES if s in sizes]
    profile["project_sizes"] = ordered
    values.setdefault("discovery", {})["star_bands"] = [band for s in ordered for band in SIZE_BANDS[s]]
    values.setdefault("health", {})["star_ranges"] = [SIZE_RANGES[s] for s in ordered]

    profile["languages"] = [lang.name for lang in parse_list(profile.get("languages") or [])]
    mode = profile.get("language_filter", "auto")
    if mode not in LANGUAGE_FILTERS:
        raise ConfigError(f"[profile] language_filter must be one of {', '.join(LANGUAGE_FILTERS)}, not {mode!r}")
    profile["language_filter"] = mode


@dataclass(frozen=True)
class LanguagePolicy:
    languages: list[Language]
    required: bool  # True: other languages are excluded; False: they're kept, yours rank higher

    def search_qualifiers(self) -> str:
        return search_qualifiers(self.languages) if self.required else ""


def language_policy(profile: dict[str, Any], api_types: list[ApiType]) -> LanguagePolicy:
    languages = parse_list(profile.get("languages") or [])
    if not languages:
        return LanguagePolicy([], False)
    mode = profile.get("language_filter", "auto")
    if mode == "auto":
        # Each API type decides: library/SDK docs need your language, spec-based APIs mostly don't.
        required = all(t.language_mode == "require" for t in api_types)
    else:
        required = mode == "require"
    return LanguagePolicy(languages, required)


def one_line(values: dict[str, Any], api_types: list[ApiType]) -> str:
    """e.g. "REST API docs · any language, Python ranked higher · small, medium, large projects"."""
    policy = language_policy(values["profile"], api_types)
    names = ", ".join(lang.name for lang in policy.languages)
    if not names:
        languages = "any language"
    elif policy.required:
        languages = f"only {names}"
    else:
        languages = f"any language, {names} ranked higher"
    sizes = ", ".join(values["profile"]["project_sizes"])
    return f"{', '.join(t.label for t in api_types)} API docs · {languages} · {sizes} projects"


def describe(values: dict[str, Any], api_types: list[ApiType], *, has_token: bool, config_path: str | None) -> str:
    """The profile in plain sentences, for ``docscout profile`` and the end of ``init``."""
    profile = values["profile"]
    policy = language_policy(profile, api_types)
    names = ", ".join(lang.name for lang in policy.languages)
    if not policy.languages:
        languages = "any"
    elif policy.required:
        languages = f"only {names}"
    else:
        languages = f"any, with {names} ranked higher"
    sizes = ", ".join(f"{s} ({SIZE_LABELS[s]})" for s in profile["project_sizes"])
    llm = values["llm"]
    if llm["provider"] == "ollama":
        llm_text = f"local Ollama ({llm['model']})"
    elif llm["provider"] == "openai_compatible":
        llm_text = f"hosted ({llm['model']} at {llm['base_url']})"
    else:
        llm_text = f"{llm['provider']} (not supported: use ollama or openai_compatible)"
    lines = [
        "DocScout is looking for:",
        f"  API docs:       {', '.join(t.label for t in api_types)}",
        f"  Languages:      {languages}",
        f"  Project sizes:  {sizes}",
        f"  Repos per day:  {values['discovery']['daily_repo_budget']}",
        f"  LLM:            {llm_text}",
        f"  GitHub token:   {'set' if has_token else 'not set (run docscout init)'}",
        f"Settings file:    {config_path or 'none yet, using defaults (run docscout init)'}",
    ]
    return "\n".join(lines)
