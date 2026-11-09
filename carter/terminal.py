"""The human-terminal rule shared by every Carter mutator.

``carter guard install|remove``, ``github-token set|check``, ``push`` and ``pr`` must refuse
in an agent shell (AD1) and, unless told otherwise, without a TTY. The rule is written once
here so it cannot drift between commands.

Stdlib-only (plus ``carter.identity``, itself stdlib-only): the gate wrapper can import
it without pulling in click.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable, Mapping
from typing import IO

from carter.identity.errors import E_HUMAN_TERMINAL, IdentityError
from carter.identity.rules import is_agent, load_rules

DEFAULT_STREAMS = ("stdin", "stdout")


def is_agent_shell(env: Mapping[str, str] | None = None) -> bool:
    """Is this (by default, the current) shell an agent's? See ``rules.is_agent``."""
    return is_agent(os.environ if env is None else env)


def _agent_signals_present(env: Mapping[str, str]) -> list[str]:
    r = load_rules()
    return [n for n in (*r.agent_signals, *r.human_signals) if n in env]


def require_human_terminal(
    command_name: str,
    *,
    need_tty: bool = True,
    streams: Iterable[str] = DEFAULT_STREAMS,
    env: Mapping[str, str] | None = None,
    stdin: IO[str] | None = None,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> None:
    """Raise ``IdentityError(E-HUMAN-TERMINAL)`` unless a human is at a terminal.

    An agent shell is always refused. With ``need_tty`` every stream in ``streams``
    (``stdin``/``stdout``/``stderr``) must be a TTY; pass ``need_tty=False`` for a scripted
    ``--yes`` path. ``env`` and the streams default to the process's. The error's
    ``detail`` names the command and variable or stream *names* only, never values.
    """
    environment = os.environ if env is None else env
    if is_agent(environment):
        names = ", ".join(_agent_signals_present(environment))
        raise IdentityError(E_HUMAN_TERMINAL, detail=f"{command_name}: agent shell ({names})")
    if not need_tty:
        return
    available = {
        "stdin": stdin if stdin is not None else sys.stdin,
        "stdout": stdout if stdout is not None else sys.stdout,
        "stderr": stderr if stderr is not None else sys.stderr,
    }
    missing = [name for name in streams if not _isatty(available[name])]
    if missing:
        raise IdentityError(
            E_HUMAN_TERMINAL, detail=f"{command_name}: no TTY on {', '.join(missing)}"
        )


def stdin_is_tty() -> bool:
    """Is the process's stdin a terminal? (The one place commands ask, so tests can fake it.)"""
    return _isatty(sys.stdin)


def _isatty(stream: IO[str] | None) -> bool:
    try:
        return bool(stream is not None and stream.isatty())
    except (ValueError, OSError):  # closed stream
        return False
