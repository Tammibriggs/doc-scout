"""Local backend: Ollama's native chat API.

The native API (not /v1) is used because it allows a JSON schema in ``format``,
``think``, ``num_ctx`` and ``keep_alive``. Thinking is off unless asked for: on this
laptop it multiplies the time per review. The model stays loaded for 2 minutes
between reviews of a batch and is unloaded once with :meth:`OllamaClient.unload`;
``keep_alive: 0`` on every request would reload the multi-GB model each time.
"""

from __future__ import annotations

import httpx

from typing import Any

from docscout.llm.base import (
    DRAFT_SCHEMA,
    REVIEW_SCHEMA,
    Draft,
    LLMError,
    LLMUnavailable,
    RepoContext,
    Review,
    build_draft_messages,
    build_messages,
    parse_draft,
    parse_review,
)


class OllamaClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        num_ctx: int = 4096,
        timeout: float = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = f"ollama:{model}"
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.num_ctx = num_ctx
        self._send_think = True
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout, transport=transport)

    def _chat(self, payload: dict) -> httpx.Response:
        try:
            return self._client.post("/api/chat", json=payload)
        except httpx.ConnectError as exc:
            raise LLMUnavailable(
                f"Ollama isn't running at {self.base_url}. Start it with `ollama serve`, install it from "
                "https://ollama.com, or use a hosted model: `docscout set --llm openai_compatible`."
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"cannot reach Ollama: {exc}") from exc

    def review(self, ctx: RepoContext, readme_chars: int = 1500, think: bool = False) -> Review:
        return parse_review(self._structured(build_messages(ctx, readme_chars), REVIEW_SCHEMA, think))

    def draft(self, ctx: RepoContext, issue: str | None = None) -> Draft:
        return parse_draft(self._structured(build_draft_messages(ctx, issue), DRAFT_SCHEMA, False))

    def _structured(self, messages: list[dict[str, str]], schema: dict[str, Any], think: bool) -> str:
        """The model's JSON answer, shaped by ``schema``."""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "format": schema,
            "stream": False,
            "keep_alive": "2m",
            "options": {"num_ctx": self.num_ctx, "temperature": 0},
        }
        if self._send_think:
            payload["think"] = think
        resp = self._chat(payload)
        if resp.status_code == 400 and "think" in resp.text.lower() and self._send_think:
            # Models without thinking support may reject the flag entirely.
            self._send_think = False
            payload.pop("think")
            resp = self._chat(payload)
        if resp.status_code == 404 and "not found" in resp.text.lower():
            raise LLMUnavailable(f"The model {self.model} isn't installed. Run: ollama pull {self.model}")
        if resp.status_code >= 400:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:200]}")
        return (resp.json().get("message") or {}).get("content", "")

    def loaded_model_bytes(self) -> int | None:
        """Memory the model currently uses, from /api/ps (None if not loaded)."""
        try:
            models = self._client.get("/api/ps").json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return None
        sizes = [m.get("size", 0) for m in models if m.get("name") == self.model or m.get("model") == self.model]
        return sum(sizes) if sizes else None

    def unload(self) -> None:
        try:
            self._client.post("/api/generate", json={"model": self.model, "keep_alive": 0})
        except httpx.HTTPError:
            pass

    def close(self) -> None:
        self._client.close()
