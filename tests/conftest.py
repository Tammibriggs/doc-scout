from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from docscout.settings.config import Config, load_defaults

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


class AgreeingModel:
    """Stands in for the local model in tests: confirms every project as a REST API."""

    name = "ollama:gemma4:e2b"

    def __init__(self):
        self.reviewed: list[str] = []

    def review(self, ctx, readme_chars=1500, think=False):
        from docscout.llm.base import Review

        self.reviewed.append(ctx.full_name)
        return Review(project_type="serves_api", api_style="rest", confidence=0.9, evidence="GET /api/checks",
                      why="Its users integrate through the API.", first_steps=["Describe POST /checks", "Add examples"])  # fmt: skip

    def unload(self):
        pass

    def close(self):
        pass


@pytest.fixture(autouse=True)
def no_real_model(monkeypatch):
    """Tests never load a real model: reviews agree unless a test says otherwise, and memory looks plentiful."""
    from docscout.llm import review
    from docscout.llm import memory

    from docscout.llm.ollama import OllamaClient
    from docscout.llm.openai_compat import OpenAICompatClient

    model = AgreeingModel()
    monkeypatch.setattr(review, "open_reviewer", lambda cfg: model)
    monkeypatch.setattr(memory, "available_bytes", lambda: 16 * 10**9)

    # A safety net: loading a real model during tests would swap a small laptop. Mocked
    # connections (httpx.MockTransport) are fine.
    def mocked_only(send):
        def guarded(self, payload):
            if not isinstance(self._client._transport, httpx.MockTransport):
                raise AssertionError("a test tried to call a real model")
            return send(self, payload)

        return guarded

    monkeypatch.setattr(OllamaClient, "_chat", mocked_only(OllamaClient._chat))
    monkeypatch.setattr(OpenAICompatClient, "_post", mocked_only(OpenAICompatClient._post))
    return model
