"""One run at a time: an operating-system file lock.

The OS releases the lock when the process ends, however it ends (a crash, ``kill -9``,
a shutdown), so a stopped run never blocks the next one.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


class Busy(Exception):
    """Another DocScout run holds the lock."""


def _acquire(fh: IO[str]) -> None:
    if os.name == "nt":  # tested in stage M5
        import msvcrt

        fh.seek(0)
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise Busy from exc
    else:
        import fcntl

        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:  # BlockingIOError when someone else holds it
            raise Busy from exc


def _release(fh: IO[str]) -> None:
    if os.name == "nt":
        import msvcrt

        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


@contextmanager
def hold(path: Path) -> Iterator[None]:
    """Hold the lock for the duration of the block; raises :class:`Busy` if it's taken."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+", encoding="utf-8")  # noqa: SIM115 (closed below)
    try:
        _acquire(fh)
    except Busy:
        fh.close()
        raise
    try:
        if os.name != "nt":  # on Windows the locked byte can't be rewritten while locked
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()}\n")
            fh.flush()
        yield
    finally:
        _release(fh)
        fh.close()


def is_held(path: Path) -> bool:
    """True if a run holds the lock right now."""
    if not path.exists():
        return False
    try:
        with hold(path):
            return False
    except Busy:
        return True
