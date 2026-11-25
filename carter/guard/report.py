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
    if isinstance(line, ui.Raw):  # a command or snippet: shown whole with -v
        ui.detail(ui.Raw("  " + text))
    elif text.startswith("✓ "):  # a result the user should always see (the notice)
        ui.ok(text.removeprefix("✓ "))
    elif text.startswith("→ "):  # the line under a warning: where to read more, or what to run
        ui.fix(text.removeprefix("→ "))
    elif text.startswith(("⚠", "Declined", "Not confirmed", "no terminal", "Opt-outs")) or (
        "need your confirmation" in text or "needs your confirmation" in text
    ):
        ui.warn(text.lstrip("⚠ "))
    else:
        ui.detail(text)


def accepted_groups(base_dir: Path | None) -> list[str]:
    """The guard groups the state records as accepted now."""
    return consent.accepted_groups(load_or_empty_readonly(guard_state_path(base_dir)).state)


def removed_groups(base_dir: Path | None, only: list[str]) -> None:
    """The line under ``guard remove --only``: a removed group is recorded as declined."""
    state = load_or_empty_readonly(guard_state_path(base_dir)).state
    if any(state.consents.get(name, {}).get("decision") == "declined" for name in only):
        ui.info("· declined; the other guards stay (see: carter guard --help)")


def installed(base_dir: Path | None) -> None:
    """The one line ``carter guard install`` ends with: what is accepted now."""
    done = accepted_groups(base_dir)
    if done:
        ui.ok("guards installed", f"{len(done)} groups (see: carter guard status)")
