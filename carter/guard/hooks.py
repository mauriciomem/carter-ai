"""``carter-guard``: the POSIX ``pre-push`` backstop and the self-contained hook command
(RFC-0007 §4.4, C.6.4; plan 004 step 22, freeze G3/G17).

The agent test (AD1) is written **once**, here, from the signal names in ``g2_rules.json``, and
rendered into two mirrors that the vector file (``tests/data/plugin_vectors.json``) keeps equal to
``carter.identity.rules.is_agent``: the script ``~/.carter/hooks/carter-guard`` and the inline
wrapper that is the hook's configured command. The wrapper exists so a missing, unreadable or
broken script can never block the human: it blocks **only** an agent shell, and on the human path
it makes no git call.

Pure functions (``render_*``, ``hook_command``, ``hook_entries``) plus the install of the script
file. Everything here is rendered with ``shlex.quote`` and is byte-deterministic.
"""

from __future__ import annotations

import re
import shlex
from importlib import resources
from pathlib import Path

from carter.guard import gitconfig
from carter.guard.state import GuardState
from carter.identity.errors import E_PUSH_GUARD, registry
from carter.identity.rules import STRONG_AGENT_SIGNAL, load_rules
from carter.install.paths import guard_script_path

GUARD_VERSION = "1.0.0"
EVENT = "pre-push"
HOOK_NAME = "carter-guard-pre-push"
MARKER = "Managed by Carter"
NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")


def _name(value: str) -> str:
    if not NAME.match(value):  # a signal name ends up in shell source: never anything else
        raise ValueError(f"not a safe environment variable name: {value!r}")
    return value


def is_agent_statements() -> list[str]:
    """Statements of the body of ``is_agent`` (mirror of ``rules.is_agent``): the strong marker
    wins, then a human tag, then any weak agent signal. Presence counts, never the value."""
    rules = load_rules()
    strong = _name(STRONG_AGENT_SIGNAL)
    out = [
        "reason=",
        f'[ "${{{strong}-}}" = 1 ] && {{ reason={shlex.quote(strong + "=1")}; return 0; }}',
    ]
    out += [f'[ -n "${{{_name(n)}+x}}" ] && return 1' for n in rules.human_signals]
    for name in rules.agent_signals:
        if name != strong:
            out.append(
                f'[ -n "${{{_name(name)}+x}}" ] && {{ reason={shlex.quote(name + " is set")}; '
                "return 0; }"
            )
    out.append("return 1")
    return out


def block_statement() -> str:
    """``block``: the E-PUSH-GUARD text on stderr (names of signals only, never values)."""
    entry = registry()[E_PUSH_GUARD]
    before, _, after = entry.message.partition("<reason>")
    quoted = [shlex.quote(t) for t in (before, after, entry.remediation)]
    fmt = "'%s%s%s\\n%s\\n'"
    return f'block() {{ printf {fmt} {quoted[0]} "$reason" {quoted[1]} {quoted[2]} >&2; }}'


def _function(name: str, statements: list[str]) -> str:
    body = "\n".join(f"  {s}" for s in statements)
    return f"{name}() {{\n{body}\n}}"


def render_script() -> str:
    """The text of ``~/.carter/hooks/carter-guard`` (identical for every user and run)."""
    template = resources.files("carter.guard").joinpath("templates/carter-guard.sh")
    return (
        template.read_text("utf-8")
        .replace("@@VERSION@@", GUARD_VERSION)
        .replace("@@IS_AGENT@@", _function("is_agent", is_agent_statements()))
        .replace("@@BLOCK@@", block_statement())
    )


def wrapper_statements(script: Path | str, *, call: str = "carter_hook") -> list[str]:
    """The self-contained hook command as complete statements.

    ``carter_hook`` is a function because git appends the hook's arguments to the configured
    command (``sh -c '<command> "$@"'``): the last statement is a call that takes them, and a
    bare ``exit 0`` at the end would die with "too many arguments" on the human path (found by
    the real-git test). Inside, the order is:

    1. the script, when it is executable: exit 0 passes; anything else falls through;
    2. no script, or it failed: block (exit 1) **only** if this is an agent shell, else pass.
    A script that failed with 1 has printed the message; any other failure prints it here."""
    body = (
        'ran=; rc=1; if [ -x "$g" ]; then "$g" '
        f'{EVENT} "$@"; rc=$?; ran=1; [ "$rc" -eq 0 ] && exit 0; fi; '
        'if is_agent; then [ "$ran" = 1 ] && [ "$rc" -eq 1 ] || block; exit 1; fi; exit 0'
    )
    return [
        f"g={shlex.quote(str(script))}",
        "is_agent() { " + "; ".join(is_agent_statements()) + "; }",
        block_statement(),
        "carter_hook() { " + body + "; }",
        call,
    ]


def hook_command(script: Path | str) -> str:
    """The value of ``hook.carter-guard-pre-push.command`` (one line, no external command).

    Git runs it as ``sh -c '<command> "$@"'`` with the hook's arguments."""
    return "; ".join(wrapper_statements(script))


def repo_hook_text(script: Path | str) -> str:
    """The per-repo ``.git/hooks/pre-push`` file (git < 2.54, C.6.5): the same wrapper."""
    head = (
        f"#!/bin/sh\n# {MARKER} (`carter guard`, repo hook). Do not edit: a changed file is kept.\n"
    )
    return head + "\n".join(wrapper_statements(script, call='carter_hook "$@"')) + "\n"


def hook_entries(script: Path | str) -> list[tuple[str, str]]:
    return [
        (f"hook.{HOOK_NAME}.event", EVENT),
        (f"hook.{HOOK_NAME}.command", hook_command(script)),
    ]


def script_path(base_dir: Path | None) -> Path:
    return guard_script_path(base_dir)


def install_script(
    base_dir: Path | None, state: GuardState, *, overwrite_edited: bool = False
) -> str:
    """Write the script (0755, atomically), record its hash and the rendered version."""
    status = gitconfig.install_file(
        script_path(base_dir),
        render_script(),
        state,
        overwrite_edited=overwrite_edited,
        mode=0o755,
    )
    if status != "edited-kept":
        state.set_guard_version(GUARD_VERSION)
    return status
