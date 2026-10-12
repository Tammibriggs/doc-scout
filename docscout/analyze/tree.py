"""Generic helpers for a repo's file tree (as returned by GitHub's git trees API)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MAX_DEFINITION_BYTES = 2 * 1024 * 1024

# Files under these folders usually describe someone else's API or exist only for tests.
_NOT_OWNED_DIRS = re.compile(
    r"(^|/)(node_modules|vendor|vendors|third[_-]?party|external|examples?|samples?|fixtures?|"
    r"testdata|test|tests|__tests__|spec/fixtures|mocks?|\.github)(/|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OwnedFile:
    path: str
    size: int


def find_owned_files(tree: list[dict[str, Any]], name_pattern: re.Pattern[str], max_bytes: int = MAX_DEFINITION_BYTES) -> list[OwnedFile]:
    """Files whose name matches ``name_pattern`` and that the repo plausibly owns.

    Shallow paths come first: a root-level file is the most likely to describe the project itself.
    """
    found = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        directory, _, name = path.rpartition("/")
        if not name_pattern.search(name) or _NOT_OWNED_DIRS.search(directory):
            continue
        size = int(entry.get("size") or 0)
        if size == 0 or size > max_bytes:
            continue
        found.append(OwnedFile(path=path, size=size))
    return sorted(found, key=lambda f: (f.path.count("/"), f.path))


def has_path(tree: list[dict[str, Any]], pattern: str) -> bool:
    regex = re.compile(pattern, re.IGNORECASE)
    return any(regex.search(entry.get("path", "")) for entry in tree)


def has_contributing(tree: list[dict[str, Any]]) -> bool:
    return has_path(tree, r"^(\.github/|docs/)?contributing(\.\w+)?$")


def has_container_setup(tree: list[dict[str, Any]]) -> bool:
    return has_path(tree, r"^(docker-compose[\w.-]*\.ya?ml|compose\.ya?ml|dockerfile|\.devcontainer/.*)$")
