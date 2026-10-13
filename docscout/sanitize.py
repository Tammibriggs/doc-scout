"""Make untrusted text safe to put in a Markdown report.

Repo descriptions, issue titles, file paths and (later) LLM output are written by
strangers. Before they reach the report they lose control, bidirectional-text and ANSI
characters, are collapsed to one line and length-limited, and have Markdown syntax
escaped so they can't add links, images, HTML or headings. Links are only built from
GitHub URLs that DocScout constructs and validates itself.
"""

from __future__ import annotations

import re
from urllib.parse import quote

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-_]")
_INVISIBLE = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f\\u200b-\\u200f\\u202a-\\u202e\\u2060-\\u2069\\ufeff]")
_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!|<>~$])")
_GITHUB_URL = re.compile(
    r"^https://github\.com/[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}"
    r"(/(issues|pull)/\d{1,9}|/blob/([0-9a-f]{7,40}|HEAD)/[A-Za-z0-9._~%/-]{1,300})?$"
)


def clean(value: object, limit: int = 300) -> str:
    """One line of plain text without control characters, at most ``limit`` characters."""
    text = _INVISIBLE.sub("", _ANSI.sub("", str(value or "")))
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def block(value: object, limit: int = 2000) -> str:
    """Multi-line text for the terminal (e.g. a model's draft): line breaks kept, control and
    invisible characters removed, so it can't move the cursor, recolor or hide text."""
    text = _INVISIBLE.sub("", _ANSI.sub("", str(value or "").replace("\r\n", "\n")))
    text = "\n".join(line.rstrip() for line in text.split("\n")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def text(value: object, limit: int = 300) -> str:
    """Untrusted text as inert Markdown."""
    return _MD_SPECIAL.sub(r"\\\1", clean(value, limit))


def code(value: object, limit: int = 120) -> str:
    """Untrusted text as an inline code span (backticks can't break out of it)."""
    return "`" + clean(value, limit).replace("`", "'") + "`"


def is_github_url(url: str) -> bool:
    return bool(_GITHUB_URL.match(url))


def link(label_markdown: str, url: str) -> str:
    """A link only if ``url`` is a GitHub URL DocScout trusts; otherwise just the label."""
    return f"[{label_markdown}]({url})" if is_github_url(url) else label_markdown


def repo_url(full_name: str) -> str:
    return f"https://github.com/{full_name}"


def blob_url(full_name: str, sha: str | None, path: str) -> str:
    return f"https://github.com/{full_name}/blob/{sha or 'HEAD'}/{quote(path, safe='/._-~')}"
