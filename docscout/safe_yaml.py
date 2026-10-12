"""YAML loading for untrusted files.

``yaml.safe_load`` already blocks code execution, but anchors and aliases can still
expand into huge structures when the data is walked ("billion laughs"). Real
OpenAPI specs and the seed dataset don't need aliases, so any alias is rejected.
"""

from __future__ import annotations

from typing import Any

import yaml


class UnsafeYAML(ValueError):
    pass


class _NoAliasLoader(yaml.SafeLoader):
    def compose_node(self, parent, index):  # type: ignore[no-untyped-def]
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise UnsafeYAML(f"YAML aliases are not allowed (line {event.start_mark.line + 1})")
        return super().compose_node(parent, index)


def load_untrusted(text: str | bytes, *, max_bytes: int = 2 * 1024 * 1024) -> Any:
    if len(text) > max_bytes:
        raise UnsafeYAML(f"document larger than {max_bytes} bytes")
    try:
        return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 - SafeLoader subclass
    except yaml.YAMLError as exc:
        raise UnsafeYAML(f"invalid YAML: {exc}") from exc
