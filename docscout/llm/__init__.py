"""LLM backends. See :mod:`docscout.llm.base` for the shared schema and rules."""

from __future__ import annotations

from typing import Any

from docscout.errors import ConfigError
from docscout.llm.base import Draft, LLMClient, LLMError, LLMUnavailable, RepoContext, Review, apply_review

__all__ = ["Draft", "LLMClient", "LLMError", "LLMUnavailable", "RepoContext", "Review", "apply_review", "make_client"]

PROVIDERS = ("ollama", "openai_compatible")


def make_client(llm_cfg: dict[str, Any], api_key: str | None = None) -> LLMClient:
    """The configured model. There's no "none": only projects the model has reviewed are reported."""
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
