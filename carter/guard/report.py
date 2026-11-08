"""What the guard commands print: problems as warnings, the rest with ``-v`` (D68 a, h)."""

from __future__ import annotations

import re
from pathlib import Path

from carter import ui
from carter.guard import consent
from carter.guard.state import load_or_empty_readonly
from carter.identity.policyset import consent_groups
from carter.install.paths import guard_state_path

PROBLEM = re.compile(
    r"MISSING|CHANGED|INVALID|NOT in|cannot (?:verify|read)|unreadable|still recorded"
)


def say(line: str) -> None:
    """Engine lines: problems surface as warnings, the rest shows with ``-v``."""
    text = line.strip()
    if text.startswith("✓ "):  # a result the user should always see (the D71 notice)
        ui.ok(text.removeprefix("✓ "))
    elif text.startswith(("⚠", "Declined", "Not confirmed", "no terminal", "Opt-outs")) or (
        "need your confirmation" in text or "needs your confirmation" in text
    ):
        ui.warn(text.lstrip("⚠ "))
    else:
        ui.detail(text)


def installed(base_dir: Path | None) -> None:
    """The one line an install ends with: what is accepted now."""

    state = load_or_empty_readonly(guard_state_path(base_dir)).state
    revs = {g.id: g.rev for g in consent_groups()}
    done = [
        f"{g} r{revs[g]}" if revs[g] > 1 else g for g in consent.accepted_groups(state) if g in revs
    ]
    if done:
        ui.ok("guards installed", " · ".join(done))
