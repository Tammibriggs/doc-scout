"""Desktop notifications.

The wording is fixed by DocScout. Values (a count, a file path) are passed to the
notification program as separate arguments, never through a shell or a script.
"""

from __future__ import annotations

import html
import logging
import shutil
import subprocess
import sys
from collections.abc import Callable

log = logging.getLogger(__name__)

Notifier = Callable[..., bool]


def send(title: str, body: str, *, urgent: bool = False) -> bool:
    """Show a notification; False if it couldn't be shown (the reason is logged)."""
    if not sys.platform.startswith("linux"):
        log.info("desktop notifications on %s come in stage M5: %s. %s", sys.platform, title, body)
        return False
    exe = shutil.which("notify-send")
    if exe is None:
        log.warning("couldn't show a notification: notify-send isn't installed (package libnotify-bin). %s. %s", title, body)
        return False
    # Notification servers read the body as simple markup, so &, < and > must be escaped.
    args = [exe, "--app-name=DocScout", f"--urgency={'critical' if urgent else 'normal'}", "--", title, html.escape(body, quote=False)]
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("couldn't show a notification (%s): %s. %s", exc, title, body)
        return False
    return True
