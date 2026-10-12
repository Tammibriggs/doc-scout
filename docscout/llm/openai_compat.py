"""Hosted backend: any OpenAI-compatible chat completions API.

Covers OpenRouter, Groq, Together, OpenAI and similar, using ``base_url`` such as
``https://openrouter.ai/api/v1``. It asks for a JSON schema response; providers that
reject that get JSON mode with the schema written into the prompt instead.
"""

from __future__ import annotations

import json

import httpx

from docscout.llm.base import REVIEW_SCHEMA, LLMError, LLMUnavailable, RepoContext, Review, build_messages, parse_review


class OpenAICompatClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None,
        timeout: float = 300,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.name = f"openai_compatible:{model}"
        self.model = model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=timeout, transport=transport)
        self._schema_mode = True

    def _post(self, payload: dict) -> httpx.Response:
        try:
            return self._client.post("/chat/completions", json=payload)
        except httpx.ConnectError as exc:
            raise LLMUnavailable(f"Can't connect to the LLM provider at {self._client.base_url}. Check the address (--base-url) and your connection.") from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"cannot reach LLM provider: {exc}") from exc

    def review(self, ctx: RepoContext, readme_chars: int = 1500) -> Review:
        messages = build_messages(ctx, readme_chars)
        payload: dict = {"model": self.model, "messages": messages, "temperature": 0}
        if self._schema_mode:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "review", "schema": REVIEW_SCHEMA},
            }
            resp = self._post(payload)
            if resp.status_code == 400:
                self._schema_mode = False
        if not self._schema_mode:
            payload["response_format"] = {"type": "json_object"}
            schema_note = "\n\nReply with a JSON object matching this JSON schema:\n" + json.dumps(REVIEW_SCHEMA)
            payload["messages"] = [
                {**messages[0], "content": messages[0]["content"] + schema_note},
                messages[1],
            ]
            resp = self._post(payload)
        if resp.status_code in (401, 403):
            raise LLMUnavailable(f"The LLM provider rejected the API key ({resp.status_code}). Run `docscout init` again or set DOCSCOUT_LLM_API_KEY.")
        if resp.status_code == 404:
            raise LLMUnavailable(f"The LLM provider doesn't know the model {self.model!r} (404). Check the name with `docscout set --model NAME`.")
        if resp.status_code >= 400:
            raise LLMError(f"LLM provider error {resp.status_code}: {resp.text[:200]}")
        try:
            content = resp.json()["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected response shape: {resp.text[:200]}") from exc
        return parse_review(content)

    def unload(self) -> None:
        pass

    def close(self) -> None:
        self._client.close()
