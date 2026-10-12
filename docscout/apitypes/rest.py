"""REST/HTTP APIs, usually described by OpenAPI (Swagger) specs.

Endpoint detection is language- and framework-agnostic: it only looks for HTTP
methods followed by paths, ``curl`` commands, and Markdown tables with method/endpoint
columns.
"""

from __future__ import annotations

import re

from docscout.apitypes.base import ApiType
from docscout.evidence import Evidence, Signals

_METHODS = "GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS"
_METHOD_PATH = re.compile(rf"(?<![\w/])({_METHODS})\s+`?(/[\w{{}}:./\-*]*)", re.MULTILINE)
_CURL_LINE = re.compile(r"\bcurl\b[^\n]*")
_CURL_METHOD = re.compile(rf"(?:-X|--request)\s*['\"]?({_METHODS})\b")
_CURL_URL_PATH = re.compile(r"https?://[^\s/'\"]+(/[\w{}:./\-*]*)")
_TABLE_ROW = re.compile(rf"^\|\s*`?({_METHODS})`?\s*\|\s*`?(/[^|`\s]*)`?", re.MULTILINE | re.IGNORECASE)
_REST_MENTION = re.compile(r"\b(rest(ful)?\s+api|api\s+(reference|endpoints?|docs|documentation)|http\s+api)\b", re.IGNORECASE)
_REST_DESCRIPTION = re.compile(r"\b(rest(ful)?\s+api|http\s+api|rest\s+server)\b", re.IGNORECASE)
_REST_ISSUE = re.compile(r"\b(openapi|swagger|endpoints?|rest(ful)?)\b", re.IGNORECASE)


def find_endpoints(text: str) -> set[tuple[str, str]]:
    """Distinct (METHOD, /path) pairs documented in the text."""
    found: set[tuple[str, str]] = set()
    for method, path in _METHOD_PATH.findall(text):
        found.add((method.upper(), path.rstrip(".`")))
    for method, path in _TABLE_ROW.findall(text):
        found.add((method.upper(), path.rstrip(".`")))
    for line in _CURL_LINE.findall(text):
        url = _CURL_URL_PATH.search(line)
        if url:
            method = _CURL_METHOD.search(line)
            found.add((method.group(1) if method else "GET", url.group(1).rstrip(".`'\"")))
    return {(m, p) for m, p in found if len(p) > 1}


def mentions_rest_api(text: str) -> bool:
    return bool(_REST_MENTION.search(text))


class RestApi(ApiType):
    key = "rest"
    label = "REST"
    llm_style = "rest"
    definition_pattern = re.compile(r"(openapi|swagger)[\w.-]*\.(ya?ml|json)$", re.IGNORECASE)

    def evidence(self, signals: Signals) -> Evidence:
        ev = Evidence()
        if _REST_DESCRIPTION.search(signals.text):
            ev.add(0.1, "describes a REST/HTTP API")
        if signals.tree is not None and self.find_definitions(signals.tree):
            ev.add(0.1, "owns an OpenAPI/Swagger spec")
        if signals.readme:
            endpoints = find_endpoints(signals.readme)
            if len(endpoints) >= 3:
                ev.add(0.15, f"README documents {len(endpoints)} endpoints")
            elif endpoints:
                ev.add(0.08, f"README mentions {len(endpoints)} endpoint(s)")
            if mentions_rest_api(signals.readme):
                ev.add(0.05, "README mentions a REST/HTTP API")
        if any(_REST_ISSUE.search(title) for title in signals.issue_titles):
            ev.add(0.1, "maintainers asked for REST API docs help")
        return ev
