"""Notification bridge: TUI toasts and system notify-send."""

from __future__ import annotations

import asyncio
import logging
import subprocess
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

logger = logging.getLogger(__name__)

# Urgency levels for notify-send
URGENCY_LOW = "low"
URGENCY_NORMAL = "normal"
URGENCY_CRITICAL = "critical"


def _notify_send(title: str, message: str, urgency: str = URGENCY_NORMAL) -> None:
    """Fire a system notification via notify-send.

    Silently ignores failures — notify-send may not be installed.
    """
    try:
        subprocess.run(
            ["notify-send", "--urgency", urgency, "--app-name", "ghastly", title, message],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except FileNotFoundError:
        logger.debug("notify-send not found — skipping system notification")
    except subprocess.TimeoutExpired:
        logger.debug("notify-send timed out")
    except OSError as exc:
        logger.warning("notify-send failed: %s", exc)


async def notify(
    app: "App[object]",
    title: str,
    message: str,
    urgency: str = URGENCY_NORMAL,
    system: bool = True,
) -> None:
    """Send a TUI toast notification and optionally a system notification.

    Args:
        app: The running Textual app instance.
        title: Notification title.
        message: Notification body.
        urgency: One of URGENCY_LOW, URGENCY_NORMAL, URGENCY_CRITICAL.
        system: Whether to also send a system (notify-send) notification.
    """
    # Map urgency to Textual severity level
    if urgency == URGENCY_CRITICAL:
        severity = "error"
    elif urgency == URGENCY_LOW:
        severity = "information"
    else:
        severity = "information"

    app.notify(f"{title}: {message}", severity=severity, timeout=8)  # type: ignore[arg-type]

    if system:
        # Run in executor to avoid blocking the event loop
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _notify_send, title, message, urgency)


def urgency_for_status(status: str) -> str:
    """Return an appropriate notify-send urgency for a given display status."""
    if status == "failure":
        return URGENCY_CRITICAL
    if status == "success":
        return URGENCY_NORMAL
    return URGENCY_LOW
