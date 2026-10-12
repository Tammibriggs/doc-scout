"""API types DocScout can look for. Enable them in config with ``[api_types] enabled``.

To add one: subclass :class:`~docscout.apitypes.base.ApiType` in a new module, add it to
``REGISTRY``, and give it an ``[api_types.<key>]`` section in ``default_config.toml``.
Then measure it on its own labeled sample (``discover`` + ``eval``) before enabling it
by default.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from docscout.apitypes.base import ApiType
from docscout.apitypes.rest import RestApi
from docscout.errors import ConfigError

REGISTRY: dict[str, type[ApiType]] = {RestApi.key: RestApi}


def enabled_types(api_types_cfg: dict[str, Any]) -> list[ApiType]:
    keys = list(api_types_cfg.get("enabled", []))
    if not keys:
        raise ConfigError('[profile] api_types must list at least one API type, e.g. api_types = ["rest"]')
    unknown = [k for k in keys if k not in REGISTRY]
    if unknown:
        raise ConfigError(f"unknown API type(s) {', '.join(unknown)} in [profile] api_types; available: {', '.join(REGISTRY)}")
    return [REGISTRY[k](api_types_cfg.get(k, {})) for k in keys]


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def repo_queries(types: list[ApiType]) -> list[str]:
    return _unique(q for t in types for q in t.repo_queries)


def definition_filenames(types: list[ApiType]) -> list[str]:
    return _unique(f for t in types for f in t.definition_filenames)


def issue_keywords(types: list[ApiType], generic: list[str]) -> list[str]:
    return _unique([*generic, *(k for t in types for k in t.issue_keywords)])


__all__ = ["REGISTRY", "ApiType", "ConfigError", "enabled_types", "repo_queries", "definition_filenames", "issue_keywords"]
