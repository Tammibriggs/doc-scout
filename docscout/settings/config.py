"""Configuration and secrets.

Defaults live in ``default_config.toml`` inside the package. A user's ``config.toml``
(in the platform config folder, or passed with ``--config``) is merged over them key by
key, then the ``[profile]`` section is turned into internal settings (:mod:`docscout.settings.profile`).
Secrets come from environment variables first, then ``secrets.env`` in the config folder.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import platformdirs

from docscout.settings import profile as profile_mod
from docscout.errors import ConfigError

APP_NAME = "docscout"
GITHUB_TOKEN_VARS = ("DOCSCOUT_GITHUB_TOKEN", "GITHUB_TOKEN")


def config_dir() -> Path:
    return platformdirs.user_config_path(APP_NAME, appauthor=False)


def data_dir() -> Path:
    return platformdirs.user_data_path(APP_NAME, appauthor=False)


def log_dir() -> Path:
    return platformdirs.user_log_path(APP_NAME, appauthor=False)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_defaults() -> dict[str, Any]:
    text = resources.files("docscout.settings").joinpath("default_config.toml").read_text(encoding="utf-8")
    return tomllib.loads(text)


def parse_env_file(text: str) -> dict[str, str]:
    """Parse simple KEY=VALUE lines; blank lines and # comments are ignored."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass
class Config:
    values: dict[str, Any]
    path: Path | None
    secrets_path: Path

    def __post_init__(self) -> None:
        self.values = copy.deepcopy(self.values)
        profile_mod.apply(self.values)

    def __getitem__(self, section: str) -> dict[str, Any]:
        return self.values[section]

    def secret(self, *names: str) -> str | None:
        for name in names:
            if os.environ.get(name):
                return os.environ[name]
        if self.secrets_path.is_file():
            stored = parse_env_file(self.secrets_path.read_text(encoding="utf-8"))
            for name in names:
                if stored.get(name):
                    return stored[name]
        return None

    @property
    def github_token(self) -> str | None:
        return self.secret(*GITHUB_TOKEN_VARS)

    @property
    def reports_dir(self) -> Path:
        return Path(os.path.expanduser(self["report"]["dir"]))


def user_config_path() -> Path:
    return config_dir() / "config.toml"


def load_user_values(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path} is not valid TOML: {exc}") from exc


def load_config(path: Path | None = None, profile_overrides: dict[str, Any] | None = None) -> Config:
    """Defaults, then the user's config.toml, then one-off ``[profile]`` overrides (e.g. --languages)."""
    values = load_defaults()
    if path is None:
        candidate = user_config_path()
        path = candidate if candidate.is_file() else None
    if path is not None:
        values = _deep_merge(values, load_user_values(path))
    if profile_overrides:
        values = _deep_merge(values, {"profile": profile_overrides})
    return Config(values=values, path=path, secrets_path=config_dir() / "secrets.env")


# ---------------------------------------------------------------------- writing


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # JSON string escapes are valid TOML basic-string escapes
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} to TOML")


def dump_toml(values: dict[str, Any], _prefix: str = "") -> str:
    """Minimal TOML writer for config files: tables, strings, numbers, booleans and lists."""
    scalars = {k: v for k, v in values.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in values.items() if isinstance(v, dict)}
    lines = [f"{k} = {_toml_value(v)}" for k, v in scalars.items() if v is not None]
    for key, table in tables.items():
        name = f"{_prefix}{key}"
        body = dump_toml(table, f"{name}.")
        lines.append("")
        lines.append(f"[{name}]")
        if body.strip():
            lines.append(body.strip("\n"))
    return "\n".join(lines).strip("\n") + "\n"


def save_user_config(path: Path, updates: dict[str, Any], header: str = "") -> Path | None:
    """Merge ``updates`` into the user's config.toml, keeping their other settings.

    An existing file is backed up to ``config.toml.bak`` first (comments are not kept).
    Returns the backup path, if one was made.
    """
    current = load_user_values(path)
    merged = _deep_merge(current, updates)
    backup = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        backup = path.with_name(path.name + ".bak")
        shutil.copy2(path, backup)
    path.write_text(header + dump_toml(merged), encoding="utf-8")
    return backup


def save_secrets(path: Path, updates: dict[str, str]) -> None:
    """Set KEY=VALUE lines in secrets.env, keeping other lines; readable only by the user."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    remaining = dict(updates)
    out = []
    for line in lines:
        key = line.partition("=")[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{key}={value}" for key, value in remaining.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)
