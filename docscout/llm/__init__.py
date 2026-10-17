"""LLM backends. See :mod:`docscout.llm.base` for the shared schema and rules."""

from __future__ import annotations

import logging
from typing import Any

from docscout.errors import ConfigError
from docscout.llm.base import ClaimCheck, ClaimContext, Draft, LLMClient, LLMError, LLMUnavailable, RepoContext, Review, apply_review

__all__ = ["Draft", "LLMClient", "LLMError", "LLMUnavailable", "RepoContext", "Review", "apply_review", "make_client"]

PROVIDERS = ("ollama", "openai_compatible")
log = logging.getLogger(__name__)


class FallbackClient:
    """The configured model, and a second one asked when the first can't answer after its own
    retries: busy, down, unknown, or a malformed answer. ``name`` is the model that answered last."""

    def __init__(self, primary: LLMClient, fallback: LLMClient) -> None:
        self.primary, self.fallback = primary, fallback
        self.name = primary.name

    def _ask(self, method: str, *args: Any) -> Any:
        try:
            answer = getattr(self.primary, method)(*args)
            self.name = self.primary.name
            return answer
        except LLMError as exc:
            log.info("%s couldn't answer (%s); asking %s", self.primary.name, exc, self.fallback.name)
        answer = getattr(self.fallback, method)(*args)
        self.name = self.fallback.name
        return answer

    def review(self, ctx: RepoContext, readme_chars: int = 1500, think: bool = False) -> Review:
        return self._ask("review", ctx, readme_chars, think)

    def draft(self, ctx: RepoContext, issue: str | None = None) -> Any:
        return self._ask("draft", ctx, issue)

    def claims(self, ctx: ClaimContext) -> ClaimCheck:
        return self._ask("claims", ctx)

    def unload(self) -> None:
        self.primary.unload()
        self.fallback.unload()

    def close(self) -> None:
        self.primary.close()
        self.fallback.close()


def make_client(llm_cfg: dict[str, Any], api_key: str | None = None) -> LLMClient:
    """The configured model, with ``fallback_model`` behind it when one is set. There's no
    "none": only projects the model has reviewed are reported."""
    client = _one_client(llm_cfg, api_key)
    fallback = str(llm_cfg.get("fallback_model") or "").strip()
    if fallback and fallback != llm_cfg["model"]:
        return FallbackClient(client, _one_client({**llm_cfg, "model": fallback}, api_key))
    return client


def _one_client(llm_cfg: dict[str, Any], api_key: str | None) -> LLMClient:
    provider = llm_cfg["provider"]
    if provider == "none":
        raise ConfigError(
            'DocScout needs a model to review projects ([llm] provider = "none" is no longer supported). '
            "Use a local one (docscout set --llm ollama) or a hosted one (docscout set --llm openai_compatible)."
        )
    if provider == "ollama":
        from docscout.llm.ollama import OllamaClient

        return OllamaClient(
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            num_ctx=int(llm_cfg.get("num_ctx", 4096)),
            timeout=float(llm_cfg.get("timeout_seconds", 300)),
        )
    if provider == "openai_compatible":
        from docscout.llm.openai_compat import OpenAICompatClient

        return OpenAICompatClient(
            base_url=llm_cfg["base_url"],
            model=llm_cfg["model"],
            api_key=api_key,
            timeout=float(llm_cfg.get("timeout_seconds", 300)),
        )
    raise ConfigError(f"unknown LLM provider {provider!r} (use ollama or openai_compatible)")
