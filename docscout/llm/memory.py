"""Free memory, checked before loading a local model.

On a small laptop a model that doesn't fit makes the whole computer swap. So the
reviews wait until enough memory is free, and the projects found meanwhile are held.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def available_bytes() -> int | None:
    """Memory available to new programs (Linux ``MemAvailable``); None where unknown (macOS and Windows until M5)."""
    meminfo = Path("/proc/meminfo")
    if not meminfo.is_file():
        return None
    for line in meminfo.read_text().splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) * 1024
    return None


def shortage(llm_cfg: dict[str, Any], free: int | None = None) -> str | None:
    """Why the local model shouldn't be loaded now, or None. A hosted model uses no local memory."""
    if llm_cfg.get("provider") != "ollama":
        return None
    free = available_bytes() if free is None else free
    need = float(llm_cfg.get("min_free_memory_gb", 2.5))
    if free is None or free >= need * 1e9:
        return None
    return f"only {free / 1e9:.1f} GB of memory is free and {llm_cfg.get('model', 'the model')} needs about {need:g} GB"
