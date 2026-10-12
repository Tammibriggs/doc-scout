"""LLM backends. See :mod:`docscout.llm.base` for the shared schema and rules."""

from __future__ import annotations

from typing import Any

from docscout.llm.base import LLMClient, LLMError, RepoContext, Review, apply_review

__all__ = ["LLMClient", "LLMError", "RepoContext", "Review", "apply_review", "make_client"]


def make_client(llm_cfg: dict[str, Any], api_key: str | None = None) -> LLMClient | None:
    provider = llm_cfg["provider"]
    if provider == "none":
        return None
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
    raise ValueError(f"unknown LLM provider {provider!r} (use ollama, openai_compatible or none)")
