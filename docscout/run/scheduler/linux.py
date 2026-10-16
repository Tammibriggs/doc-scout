"""Linux: a systemd user timer that runs ``docscout run --if-due`` every 15 minutes.

User timers run while you're logged in, which is also when notifications can be shown.
``OnStartupSec`` checks two minutes after you log in, and ``Persistent=true`` catches up
on a check missed while the computer was off.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Callable
from pathlib import Path

from docscout.run.scheduler import SchedulerError, ScheduleStatus

SERVICE = "docscout.service"
TIMER = "docscout.timer"
Runner = Callable[[list[str]], subprocess.CompletedProcess]

TIMER_TEXT = """\
[Unit]
Description=Check every 15 minutes whether DocScout's daily run is due

[Timer]
OnStartupSec=2min
OnCalendar=*:0/15
Persistent=true
AccuracySec=1min

[Install]
WantedBy=timers.target
"""


def unit_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "systemd" / "user"


def quote(arg: str) -> str:
    """One ExecStart argument, escaped for systemd: % and $ are special, spaces need quotes."""
    arg = arg.replace("%", "%%").replace("$", "$$")
    if not arg or re.search(r"[\s\"'\\;]", arg):
        arg = '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return arg


def service_text(cmd: list[str]) -> str:
    return f"""\
[Unit]
Description=DocScout: look for API docs you can contribute to, if today's run is due

[Service]
Type=oneshot
ExecStart={" ".join(quote(a) for a in cmd)}
Environment=PYTHONUNBUFFERED=1 PYTHONUTF8=1
# Low priority, so the computer stays responsive during a run.
Nice=10
IOSchedulingClass=idle
TimeoutStartSec=2h
"""


def _exec_start(text: str) -> list[str] | None:
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            try:
                return [a.replace("%%", "%").replace("$$", "$") for a in shlex.split(line.removeprefix("ExecStart="))]
            except ValueError:
                return None
    return None


def _same_installation(a: list[str], b: list[str]) -> bool:
    """Same folder of executables and same arguments (``python`` and ``python3`` are the same install)."""
    return Path(a[0]).parent == Path(b[0]).parent and a[1:] == b[1:]


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=30)


class Systemd:
    name = "systemd user timer"

    def __init__(self, runner: Runner = _run, directory: Path | None = None) -> None:
        self._runner = runner
        self.dir = directory or unit_dir()

    def _files(self, cmd: list[str]) -> dict[Path, str]:
        return {self.dir / SERVICE: service_text(cmd), self.dir / TIMER: TIMER_TEXT}

    def _call(self, cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = self._runner(cmd)
        except (OSError, subprocess.SubprocessError) as exc:
            raise SchedulerError(f"Couldn't run {' '.join(cmd)}: {exc}. {self._fallback()}") from exc
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise SchedulerError(f"`{' '.join(cmd)}` failed: {detail}. {self._fallback()}")
        return result

    def _out(self, cmd: list[str]) -> str:
        try:
            return (self._runner(cmd).stdout or "").strip()
        except (OSError, subprocess.SubprocessError):
            return ""

    @staticmethod
    def _fallback() -> str:
        return (
            "Daily runs need a systemd user session. Without one, run `docscout run --if-due` "
            "every 15 minutes another way, e.g. a cron entry: */15 * * * * docscout run --if-due"
        )

    def install(self, cmd: list[str], *, dry_run: bool = False) -> list[str]:
        files = self._files(cmd)
        commands = [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", TIMER]]
        if dry_run:
            lines = []
            for path, text in files.items():
                lines += [f"Would write {path}:", *("    " + line for line in text.splitlines()), ""]
            return lines + [f"Would run: {' '.join(c)}" for c in commands]
        self.dir.mkdir(parents=True, exist_ok=True)
        for path, text in files.items():
            path.write_text(text, encoding="utf-8")
        for c in commands:
            self._call(c)
        return [f"Installed {TIMER} and {SERVICE} in {self.dir}."]

    def uninstall(self, *, dry_run: bool = False) -> list[str]:
        files = [p for p in (self.dir / TIMER, self.dir / SERVICE) if p.exists()]
        if dry_run:
            return ["Would run: systemctl --user disable --now docscout.timer", *(f"Would delete {p}" for p in files)]
        if not files:
            return ["The daily schedule isn't installed; nothing to remove."]
        self._call(["systemctl", "--user", "disable", "--now", TIMER], check=False)
        for path in files:
            path.unlink()
        self._call(["systemctl", "--user", "daemon-reload"], check=False)
        return [f"Removed {TIMER} and {SERVICE}."]

    def status(self, cmd: list[str]) -> ScheduleStatus:
        service = self.dir / SERVICE
        if not (self.dir / TIMER).exists() or not service.exists():
            return ScheduleStatus(installed=False)
        enabled = self._out(["systemctl", "--user", "is-enabled", TIMER]) == "enabled"
        active = self._out(["systemctl", "--user", "is-active", TIMER]) == "active"
        status = ScheduleStatus(installed=True, running=enabled and active)
        if not status.running:
            status.problems.append("The timer is installed but not running. Turn it back on with: docscout schedule install")
        else:
            status.next_check = self._out(["systemctl", "--user", "show", TIMER, "-p", "NextElapseUSecRealtime", "--value"]) or None
        installed_cmd = _exec_start(service.read_text(encoding="utf-8"))
        if not installed_cmd or not Path(installed_cmd[0]).exists():
            status.problems.append(
                "The schedule starts a program that no longer exists (the virtualenv may have moved). "
                "Run docscout schedule install again from this installation."
            )
        elif not _same_installation(installed_cmd, cmd):
            status.problems.append(f"The schedule starts a different DocScout installation ({installed_cmd[0]}). To use this one: docscout schedule install")
        if self._out(["systemctl", "--user", "show", SERVICE, "-p", "Result", "--value"]) not in ("", "success"):
            status.problems.append(f"The last scheduled check ended with an error. Details: {self.log_hint()}")
        return status

    def log_hint(self) -> str:
        return "journalctl --user -u docscout.service -n 50"
