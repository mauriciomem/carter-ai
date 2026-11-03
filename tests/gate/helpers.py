"""Small helpers shared by the gate tests."""

from __future__ import annotations

from carter import gate


def rule_of(command: str, cwd: str | None = None, skip: tuple[str, ...] = ()) -> str | None:
    """The rule id that refuses ``command`` (``None`` when it is allowed)."""
    return gate.check(command, cwd, skip).rule
