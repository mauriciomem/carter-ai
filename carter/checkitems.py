"""The result lines shared by ``carter check --host`` and ``carter github-token check``.

An ``Item`` has a level (``ok``, ``info``, ``warn``, ``red``), an area, text and an optional fix.
Exit code 1 only if something is ``red``. Items carry names and counts, never values.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

Level = Literal["ok", "info", "warn", "red"]


@dataclass(frozen=True)
class Item:
    level: Level
    area: str
    text: str
    fix: str = ""
    raw: str = ""  # a complete line to print as is (the unknown-key line)

    def render(self) -> str:
        fix = f"\n      → {self.fix}" if self.fix else ""
        return f"  {self.level.upper():<5} {self.area}: {self.text}{fix}"


def config_items(notes: Iterable[str]) -> list[Item]:
    """One line per note of the config reader (the managed file was ignored, or lost a table)."""
    from carter.identity.managed import IGNORED  # noqa: PLC0415 - keep the import light

    return [Item("warn", "config", n, IGNORED.get(n, "")) for n in notes]


def exit_code(items: list[Item]) -> int:
    return 1 if any(i.level == "red" for i in items) else 0


def summary(items: list[Item], noun: str) -> str:
    red = sum(1 for i in items if i.level == "red")
    warn = sum(1 for i in items if i.level == "warn")
    if red:
        return f"{noun}: {red} RED, {warn} WARN."
    return f"{noun} OK ({warn} WARN)." if warn else f"{noun} OK."


def render(items: list[Item], head: str, noun: str) -> list[str]:
    return [head, *(i.render() for i in items), summary(items, noun)]
