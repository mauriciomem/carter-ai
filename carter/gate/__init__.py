"""The Carter command gate.

``check(command, cwd, skip_groups)`` decides whether an agent shell may run ``command``;
``python -I -m carter.gate --json`` is the process the plugin calls. Stdlib-only, and it must
not import ``carter.identity``, ``importlib.resources``, ``importlib.metadata`` or ``pathlib``
(they cost 25 ms each and the gate runs on every agent command). ``subprocess`` is
imported lazily, only for git alias lookups.
"""

from __future__ import annotations

import os

MAX_BYTES = 1 << 20


class Decision:
    """The gate's answer: allow or deny; ``rule`` and ``message`` say why."""

    __slots__ = ("decision", "message", "rule")

    def __init__(self, decision: str, rule: str | None = None, message: str | None = None) -> None:
        self.decision, self.rule, self.message = decision, rule, message

    def __repr__(self) -> str:
        return f"Decision({self.decision!r}, {self.rule!r})"


ALLOW = Decision("allow")


def refuse(rule: str, hint: str) -> Decision:
    return Decision("deny", rule, f"Refused by the Carter command gate (rule `{rule}`): {hint}")


def check(
    command: str, cwd: str | None = None, skip_groups: tuple[str, ...] | frozenset[str] = ()
) -> Decision:
    """Allow or deny ``command``. Never raises; an unparseable input is a ``gate-input`` deny."""
    from carter.gate import rules  # noqa: PLC0415 - keeps ``import carter.gate`` itself nearly free
    from carter.gate.words import ParseError  # noqa: PLC0415

    hint = rules.rules_hint("gate-input")
    if len(command.encode("utf-8", "surrogatepass")) > MAX_BYTES or "\0" in command:
        return refuse("gate-input", hint)
    try:
        home = os.path.expanduser("~")
        rules.Engine(home, cwd if cwd else None, frozenset(skip_groups)).run_text(command)
    except rules.Denied as denied:
        return refuse(denied.rule, denied.hint)
    except (ParseError, RecursionError):
        return refuse("gate-input", hint)
    return ALLOW
