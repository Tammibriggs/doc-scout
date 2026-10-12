"""Programming-language names: forgiving input, GitHub's names for matching and search.

Users can type "py", "ts", "golang" or "c#"; DocScout stores GitHub's display name
(what ``repo["language"]`` contains, e.g. "C#") and searches with GitHub's qualifier
slug (e.g. ``language:csharp``). Repeating ``language:`` in a search means "any of these".
"""

from __future__ import annotations

from dataclasses import dataclass

# GitHub display name -> search slug
KNOWN: dict[str, str] = {
    "Python": "python", "JavaScript": "javascript", "TypeScript": "typescript", "Go": "go",
    "Rust": "rust", "Java": "java", "Kotlin": "kotlin", "C#": "csharp", "C++": "cpp", "C": "c",
    "PHP": "php", "Ruby": "ruby", "Swift": "swift", "Scala": "scala", "Elixir": "elixir",
    "Erlang": "erlang", "Dart": "dart", "Haskell": "haskell", "Clojure": "clojure", "Lua": "lua",
    "Perl": "perl", "R": "r", "Julia": "julia", "Shell": "shell", "Zig": "zig", "Nim": "nim",
    "OCaml": "ocaml", "F#": "fsharp", "Objective-C": "objective-c", "Vue": "vue",
    "Svelte": "svelte", "Crystal": "crystal", "Groovy": "groovy", "PowerShell": "powershell",
}  # fmt: skip

ALIASES: dict[str, str] = {
    "py": "Python", "python3": "Python",
    "js": "JavaScript", "node": "JavaScript", "nodejs": "JavaScript", "node.js": "JavaScript",
    "ts": "TypeScript",
    "golang": "Go",
    "rs": "Rust",
    "rb": "Ruby",
    "cs": "C#", "csharp": "C#", "c-sharp": "C#", "dotnet": "C#", ".net": "C#",
    "cpp": "C++", "cxx": "C++",
    "kt": "Kotlin",
    "ex": "Elixir", "exs": "Elixir",
    "sh": "Shell", "bash": "Shell",
    "fs": "F#", "fsharp": "F#",
    "objc": "Objective-C",
    "pwsh": "PowerShell",
}  # fmt: skip

_BY_LOWER = {name.lower(): name for name in KNOWN}


@dataclass(frozen=True)
class Language:
    name: str  # GitHub's display name
    slug: str  # value for the ``language:`` search qualifier
    known: bool = True

    def matches(self, repo_language: str | None) -> bool:
        return bool(repo_language) and repo_language.lower() == self.name.lower()


def normalize(text: str) -> Language:
    raw = text.strip()
    key = raw.lower()
    name = _BY_LOWER.get(key) or ALIASES.get(key)
    if name:
        return Language(name, KNOWN[name])
    return Language(raw, key.replace(" ", "-"), known=False)


def parse_list(values: str | list[str]) -> list[Language]:
    """'py, golang' or ['py', 'golang'] -> [Python, Go], without duplicates."""
    items = values.split(",") if isinstance(values, str) else values
    found: dict[str, Language] = {}
    for item in items:
        if item.strip():
            lang = normalize(item)
            found.setdefault(lang.name.lower(), lang)
    return list(found.values())


def search_qualifiers(languages: list[Language]) -> str:
    return " ".join(f"language:{lang.slug}" for lang in languages)
