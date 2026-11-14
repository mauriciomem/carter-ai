"""What the guard commands print: problems as warnings, the rest with ``-v`` (h)."""

from __future__ import annotations

import re
from pathlib import Path

from carter import ui
from carter.guard import consent
from carter.guard.state import load_or_empty_readonly
from carter.install.paths import guard_state_path

PROBLEM = re.compile(
    r"MISSING|CHANGED|INVALID|NOT in|cannot (?:verify|read)|unreadable|still recorded"
)


def say(line: str) -> None:
    """Engine lines: problems surface as warnings, the rest shows with ``-v``."""
    text = line.strip()
    if text.startswith("✓ "):  # a result the user should always see (the notice)
        ui.ok(text.removeprefix("✓ "))
    elif text.startswith(("⚠", "Declined", "Not confirmed", "no terminal", "Opt-outs")) or (
        "need your confirmation" in text or "needs your confirmation" in text
    ):
        ui.warn(text.lstrip("⚠ "))
    else:
        ui.detail(text)


def accepted_groups(base_dir: Path | None) -> list[str]:
    """The guard groups the state records as accepted now."""
    return consent.accepted_groups(load_or_empty_readonly(guard_state_path(base_dir)).state)


def installed(base_dir: Path | None) -> None:
    """The one line ``carter guard install`` ends with: what is accepted now."""
    done = accepted_groups(base_dir)
    if done:
        ui.ok("guards installed", " · ".join(done))
