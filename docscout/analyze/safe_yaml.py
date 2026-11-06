"""YAML loading for untrusted files.

``yaml.safe_load`` already blocks code execution, but anchors and aliases can still
expand into huge structures when the data is walked ("billion laughs"). Real
OpenAPI specs and the seed dataset don't need aliases, so any alias is rejected.
"""

from __future__ import annotations

import json
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
    """Parse untrusted YAML or JSON, rejecting aliases. JSON (most large specs) goes to the JSON
    parser, and YAML to libyaml when it's installed: the pure-Python parser took 3.5 s for an
    838 KB spec (helix, 6 Nov), a cost paid twice for every PR that changes a spec."""
    if len(text) > max_bytes:
        raise UnsafeYAML(f"document larger than {max_bytes} bytes")
    head = (text[:64].decode("utf-8", "replace") if isinstance(text, bytes) else text[:64]).lstrip("\ufeff \t\r\n")
    if head[:1] in ("{", "["):
        try:
            return json.loads(text)  # JSON has no aliases
        except ValueError:
            pass  # YAML that only starts like JSON
    fast = getattr(yaml, "CSafeLoader", None)
    try:
        if fast is None:
            return yaml.load(text, Loader=_NoAliasLoader)  # noqa: S506 - SafeLoader subclass
        for event in yaml.parse(text, Loader=fast):  # the same rule, checked on libyaml's events
            if isinstance(event, yaml.AliasEvent):
                raise UnsafeYAML(f"YAML aliases are not allowed (line {event.start_mark.line + 1})")
        return yaml.load(text, Loader=fast)  # noqa: S506 - libyaml's SafeLoader
    except yaml.YAMLError as exc:
        raise UnsafeYAML(f"invalid YAML: {exc}") from exc
