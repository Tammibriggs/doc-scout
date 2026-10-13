"""Starting DocScout automatically.

Every 15 minutes the operating system's scheduler runs ``docscout run --if-due``, which
exits within a second unless today's run is due and the computer is online. There's
one small module per operating system: Linux (systemd) now; macOS (launchd) and
Windows (Task Scheduler) in stage M5.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class SchedulerError(Exception):
    """The schedule couldn't be changed; the message says what to do instead."""


class Unsupported(SchedulerError):
    pass


@dataclass
class ScheduleStatus:
    installed: bool
    running: bool = False  # the timer is enabled and active
    next_check: str | None = None
    problems: list[str] = field(default_factory=list)


class Scheduler(Protocol):
    name: str

    def install(self, cmd: list[str], *, dry_run: bool = False) -> list[str]: ...
    def uninstall(self, *, dry_run: bool = False) -> list[str]: ...
    def status(self, cmd: list[str]) -> ScheduleStatus: ...
    def log_hint(self) -> str: ...


def command(config_path: Path | None = None) -> list[str]:
    """What the schedule runs: this Python installation, so a virtualenv or pipx install works."""
    cmd = [sys.executable, "-m", "docscout"]
    if config_path is not None:
        cmd += ["--config", str(Path(config_path).expanduser().resolve())]
    return cmd + ["run", "--if-due"]


def for_this_os() -> Scheduler:
    if sys.platform.startswith("linux"):
        from docscout.scheduler.linux import Systemd

        return Systemd()
    name = {"darwin": "macOS", "win32": "Windows"}.get(sys.platform, sys.platform)
    raise Unsupported(
        f"Automatic daily runs on {name} come in a later version (stage M5 of the plan). "
        "Until then, run `docscout run` yourself, or have your system's scheduler run "
        "`docscout run --if-due` every 15 minutes."
    )
