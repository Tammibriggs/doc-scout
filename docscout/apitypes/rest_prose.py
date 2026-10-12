"""REST endpoints documented in prose (README or Markdown docs), and how complete each is.

Language- and framework-agnostic: endpoints are found from HTTP methods followed by
paths, ``curl`` commands, and Markdown tables with method/endpoint columns. Each
endpoint's section (up to the next endpoint or heading) is checked for a description
(25), a request example (20), a response example (25), status or error codes (15) and
auth (15, or once for the whole document under an "Authentication" heading).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from docscout.analyze.gaps import Finding, counted

_METHODS = "GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS"
_METHOD_PATH = re.compile(rf"(?<![\w/])({_METHODS})\s+`?(/[\w{{}}:./\-*]*)", re.MULTILINE)
_CURL_LINE = re.compile(r"\bcurl\b[^\n]*")
_CURL_METHOD = re.compile(rf"(?:-X|--request)\s*['\"]?({_METHODS})\b")
_CURL_URL_PATH = re.compile(r"https?://[^\s/'\"]+(/[\w{}:./\-*]*)")
_TABLE_ROW = re.compile(rf"^\|\s*`?({_METHODS})`?\s*\|\s*`?(/[^|`\s]*)`?[^\n]*", re.MULTILINE | re.IGNORECASE)
_REST_MENTION = re.compile(r"\b(rest(ful)?\s+api|api\s+(reference|endpoints?|docs|documentation)|http\s+api)\b", re.IGNORECASE)

_CODE_BLOCK = re.compile(r"^(```|~~~)[^\n]*\n(.*?)^\1", re.DOTALL | re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}[ \t]+(.+)$", re.MULTILINE)
_REQUEST_CODE = re.compile(rf"\bcurl\b|\bwget\b|\bhttpie\b|\bfetch\(|\brequests\.|\baxios\b|^\s*({_METHODS})\s+/", re.IGNORECASE | re.MULTILINE)
_RESPONSE_WORDS = re.compile(r"\b(response|returns?|output|result)\b", re.IGNORECASE)
_STATUS = re.compile(
    r"\b(200|201|202|204|301|302|304|400|401|403|404|405|409|410|422|429|500|502|503)\b|status code|error code|\berrors?\b",
    re.IGNORECASE,
)
_AUTH = re.compile(r"\b(auth\w*|tokens?|api[ _-]?keys?|bearer|credentials?|sign[ -]?in|log[ -]?in|session)\b", re.IGNORECASE)
_WORD = re.compile(r"[A-Za-z]{2,}")

WEIGHTS = {"description": 25, "request example": 20, "response example": 25, "status or error codes": 15, "auth": 15}
MISSING_TEXT = {
    "description": "have no description",
    "request example": "have no request example",
    "response example": "have no response example",
    "status or error codes": "list no status or error codes",
    "auth": "don't say how to authenticate",
}
COMPLETE = 0.8


def find_endpoints(text: str) -> set[tuple[str, str]]:
    """Distinct (METHOD, /path) pairs documented in the text."""
    return {(a.method, a.path) for a in _anchors(text, _code_spans(text))}


def mentions_rest_api(text: str) -> bool:
    return bool(_REST_MENTION.search(text))


@dataclass
class _Anchor:
    method: str
    path: str
    start: int
    line_end: int
    table_row: str | None = None


def _code_spans(text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in _CODE_BLOCK.finditer(text)]


def _inside(pos: int, spans: list[tuple[int, int]]) -> tuple[int, int] | None:
    return next((s for s in spans if s[0] <= pos < s[1]), None)


def _anchors(text: str, spans: list[tuple[int, int]]) -> list[_Anchor]:
    """One anchor per endpoint, preferring a mention outside code blocks."""
    found: dict[tuple[str, str], _Anchor] = {}

    def add(method: str, path: str, pos: int, table_row: str | None = None) -> None:
        path = path.rstrip(".`'\"")
        if len(path) <= 1:
            return
        key = (method.upper(), path)
        span = _inside(pos, spans)
        start = span[0] if span else pos
        line_end = text.find("\n", pos)
        anchor = _Anchor(key[0], path, start, len(text) if line_end < 0 else line_end, table_row)
        current = found.get(key)
        if current is None or (_inside(current.start + 1, spans) and not span):
            found[key] = anchor

    for m in _TABLE_ROW.finditer(text):
        add(m.group(1), m.group(2), m.start(), table_row=m.group(0))
    for m in _METHOD_PATH.finditer(text):
        add(m.group(1), m.group(2), m.start())
    for m in _CURL_LINE.finditer(text):
        url = _CURL_URL_PATH.search(m.group(0))
        if url:
            method = _CURL_METHOD.search(m.group(0))
            add(method.group(1) if method else "GET", url.group(1), m.start())
    return sorted(found.values(), key=lambda a: a.start)


@dataclass
class ProseEndpoint:
    label: str
    missing: list[str]

    @property
    def completeness(self) -> float:
        return round(sum(w for k, w in WEIGHTS.items() if k not in self.missing) / 100, 2)


@dataclass
class ProseResult:
    endpoints: list[ProseEndpoint] = field(default_factory=list)
    source: str | None = None  # the file most endpoints were found in

    @property
    def completeness(self) -> float:
        if not self.endpoints:
            return 0.0
        return round(sum(e.completeness for e in self.endpoints) / len(self.endpoints), 2)

    def findings(self) -> list[Finding]:
        total = len(self.endpoints)
        result = []
        for key in WEIGHTS:
            failing = [e.label for e in self.endpoints if key in e.missing]
            if failing:
                result.append(counted(MISSING_TEXT[key], failing, total, noun="endpoints"))
        return result


def _section(text: str, anchor: _Anchor, anchors: list[_Anchor]) -> str:
    if anchor.table_row is not None:
        return anchor.table_row
    ends = [len(text), anchor.start + 2500]
    ends += [a.start for a in anchors if a.start > anchor.line_end and a.table_row is None]
    heading = _HEADING.search(text, anchor.line_end)
    if heading:
        ends.append(heading.start())
    return text[anchor.start : min(ends)]


def _preceding_heading(text: str, anchor: _Anchor) -> str:
    before = text[max(0, anchor.start - 200) : anchor.start]
    headings = _HEADING.findall(before)
    return headings[-1] if headings else ""


def _check(text: str, anchor: _Anchor, anchors: list[_Anchor], global_auth: bool) -> list[str]:
    section = _section(text, anchor, anchors)
    blocks = [m.group(2) for m in _CODE_BLOCK.finditer(section)]
    if section.lstrip().startswith(("```", "~~~")) and not blocks:
        blocks = [section]  # the anchor sits inside a code block that runs past the section
    prose = _CODE_BLOCK.sub(" ", section)
    missing = []

    if anchor.table_row is not None:
        cells = [c.strip() for c in anchor.table_row.strip().strip("|").split("|")[2:]]
        has_description = any(len(_WORD.findall(c)) >= 2 for c in cells)
    else:
        own = _HEADING.sub(" ", _METHOD_PATH.sub(" ", prose))
        has_description = len(_WORD.findall(own)) >= 4 or len(_WORD.findall(_preceding_heading(text, anchor))) >= 3
    if not has_description:
        missing.append("description")

    request = any(_REQUEST_CODE.search(b) for b in blocks)
    response = any(b.strip().startswith(("{", "[")) or "HTTP/1" in b or "HTTP/2" in b for b in blocks)
    if not response and len(blocks) >= 2 and _RESPONSE_WORDS.search(prose):
        response = True
    if not request:
        missing.append("request example")
    if not response:
        missing.append("response example")
    if not _STATUS.search(section):
        missing.append("status or error codes")
    if not (global_auth or _AUTH.search(section)):
        missing.append("auth")
    return missing


def analyze_text(text: str) -> list[ProseEndpoint]:
    spans = _code_spans(text)
    anchors = _anchors(text, spans)
    global_auth = any(_AUTH.search(h) for h in _HEADING.findall(text))
    return [ProseEndpoint(f"{a.method} {a.path}", _check(text, a, anchors, global_auth)) for a in anchors]


def analyze_docs(files: list[tuple[str, str]]) -> ProseResult:
    """Endpoints across several (path, text) docs files; the first mention of an endpoint wins."""
    result = ProseResult()
    seen: set[str] = set()
    best_count = 0
    for path, text in files:
        endpoints = [e for e in analyze_text(text) if e.label not in seen]
        seen.update(e.label for e in endpoints)
        result.endpoints.extend(endpoints)
        if len(endpoints) > best_count:
            best_count, result.source = len(endpoints), path
    return result
