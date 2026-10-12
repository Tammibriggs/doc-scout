from __future__ import annotations

from datetime import datetime, timezone

import pytest

from docscout.config import Config, load_defaults

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def cfg(tmp_path) -> Config:
    return Config(values=load_defaults(), path=None, secrets_path=tmp_path / "secrets.env")


def iso(days_ago: float) -> str:
    from datetime import timedelta

    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
