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
from collections.abc import Sequence
from importlib import resources
from pathlib import Path

from carter.guard import gitconfig
from carter.guard.state import GuardState
from carter.identity.errors import (
    E_GUARD_COMMITTER,
    E_GUARD_NOIDENT,
    E_GUARD_SIGNCFG,
    E_GUARD_T01SIGN,
    E_GUARD_TRAILER,
    E_GUARD_UNSIGNED,
    E_PUSH_GUARD,
    registry,
)
from carter.identity.rules import STRONG_AGENT_SIGNAL, load_rules
from carter.install.paths import guard_script_path

GUARD_VERSION = "2.0.0"
EVENT = "pre-push"
HOOK_NAME = "carter-guard-pre-push"
COMMIT_EVENTS = ("prepare-commit-msg", "commit-msg", "post-commit")
EVENTS = (EVENT, *COMMIT_EVENTS)  # revision 2 of the `hooks` group wires all four
# Hints that follow a reject; not registry entries (the registry holds the message and fix).
STALE_HINT = "If you just changed `max_tier`, run `carter update`."
RESTART_HINT = "If this persists, restart the agent from a clean terminal."
COMMIT_BLOCK = (
    "carter-guard: agent commit blocked (the guard script is missing or failed)",
    "Run `carter guard status`, or ask the user to run `carter guard install`.",
)
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


def events_for_rev(rev: int) -> tuple[str, ...]:
    """Revision 1 of ``hooks`` / ``repo_hooks`` wired ``pre-push`` only; revision 2 all four."""
    return EVENTS if rev >= 2 else (EVENT,)


def hook_name(event: str) -> str:
    return f"carter-guard-{event}"


def _parts(code: str, marker: str | None = None) -> list[str]:
    """The registry message split on its ``<placeholder>`` (or on ``marker``)."""
    message = registry()[code].message
    if marker:
        return list(message.partition(marker)[::2])
    return re.split(r"<[a-z]+>", message)


def message_assignments() -> str:
    """The reject texts as shell variables, from the registry (single source, shlex-quoted)."""
    reg = registry()
    values: dict[str, str] = {}
    for i, part in enumerate(_parts(E_GUARD_COMMITTER)):
        values[f"M_COMMITTER_{i}"] = part
    for i, part in enumerate(_parts(E_GUARD_TRAILER, "Co-authored-by")):
        values[f"M_TRAILER_{i}"] = part
    for i, part in enumerate(_parts(E_GUARD_UNSIGNED)):
        values[f"M_UNSIGNED_{i}"] = part
    values["M_NOIDENT_0"] = reg[E_GUARD_NOIDENT].message
    values["M_T01SIGN_0"] = reg[E_GUARD_T01SIGN].message
    values["R_NOIDENT"] = reg[E_GUARD_NOIDENT].remediation
    values["R_COMMITTER"] = reg[E_GUARD_COMMITTER].remediation
    values["R_SIGNCFG"] = reg[E_GUARD_SIGNCFG].remediation
    values["R_TRAILER"] = reg[E_GUARD_TRAILER].remediation
    values["R_UNSIGNED"] = reg[E_GUARD_UNSIGNED].remediation
    values["STALE_HINT"] = STALE_HINT
    values["RESTART_HINT"] = RESTART_HINT
    return "\n".join(f"{k}={shlex.quote(v)}" for k, v in values.items())


def render_script() -> str:
    """The text of ``~/.carter/hooks/carter-guard`` (identical for every user and run)."""
    template = resources.files("carter.guard").joinpath("templates/carter-guard.sh")
    return (
        template.read_text("utf-8")
        .replace("@@VERSION@@", GUARD_VERSION)
        .replace("@@IS_AGENT@@", _function("is_agent", is_agent_statements()))
        .replace("@@BLOCK@@", block_statement())
        .replace("@@MESSAGES@@", message_assignments())
        .replace("@@SIGNCFG_CODE@@", E_GUARD_SIGNCFG)
        .replace("@@UNSIGNED_CODE@@", E_GUARD_UNSIGNED)
    )


def _commit_block() -> str:
    """The text a commit hook prints when the script is missing or broke (agent shells only)."""
    return (
        "block() { printf '%s\\n%s\\n' "
        + " ".join(shlex.quote(t) for t in COMMIT_BLOCK)
        + " >&2; }"
    )


def wrapper_statements(
    script: Path | str, *, call: str = "carter_hook", event: str = EVENT
) -> list[str]:
    """The self-contained hook command as complete statements.

    ``carter_hook`` is a function because git appends the hook's arguments to the configured
    command (``sh -c '<command> "$@"'``): the last statement is a call that takes them, and a
    bare ``exit 0`` at the end would die with "too many arguments" on the human path (found by
    the real-git test). Inside, the order is:

    1. the script, when it is executable: exit 0 passes; anything else falls through;
    2. no script, or it failed: block (exit 1) **only** if this is an agent shell, else pass.
    A script that failed with 1 has printed the message; any other failure prints it here.

    ``post-commit`` never blocks (it warns in the script, git ignores its status anyway). The
    commit events pass ``CARTER_GUARD_CONFIG`` (Carter's own git file, next to the hooks
    directory) so the script reads the tier mirror from there and nowhere else."""
    env = ""
    if event != EVENT:
        env = (
            "CARTER_GUARD_CONFIG="
            + shlex.quote(str(Path(script).parent.parent / "gitconfig"))
            + " "
        )
    tail = (
        "exit 0"
        if event == "post-commit"
        else 'if is_agent; then [ "$ran" = 1 ] && [ "$rc" -eq 1 ] || block; exit 1; fi; exit 0'
    )
    body = (
        'ran=; rc=1; if [ -x "$g" ]; then '
        f'{env}"$g" {event} "$@"; rc=$?; ran=1; [ "$rc" -eq 0 ] && exit 0; fi; {tail}'
    )
    return [
        f"g={shlex.quote(str(script))}",
        "is_agent() { " + "; ".join(is_agent_statements()) + "; }",
        block_statement() if event == EVENT else _commit_block(),
        "carter_hook() { " + body + "; }",
        call,
    ]


def hook_command(script: Path | str, event: str = EVENT) -> str:
    """The value of ``hook.carter-guard-<event>.command`` (one line, no external command).

    Git runs it as ``sh -c '<command> "$@"'`` with the hook's arguments."""
    return "; ".join(wrapper_statements(script, event=event))


def repo_hook_text(script: Path | str, event: str = EVENT) -> str:
    """The per-repo ``.git/hooks/<event>`` file (git < 2.54, C.6.5): the same wrapper."""
    head = (
        f"#!/bin/sh\n# {MARKER} (`carter guard`, repo hook). Do not edit: a changed file is kept.\n"
    )
    return head + "\n".join(wrapper_statements(script, call='carter_hook "$@"', event=event)) + "\n"


def hook_entries(script: Path | str, events: Sequence[str] = (EVENT,)) -> list[tuple[str, str]]:
    """``hook.carter-guard-<event>.event`` and ``.command`` per event (default: ``pre-push``,
    which is what revision 1 of the ``hooks`` group wrote)."""
    out: list[tuple[str, str]] = []
    for event in events:
        out += [
            (f"hook.{hook_name(event)}.event", event),
            (f"hook.{hook_name(event)}.command", hook_command(script, event)),
        ]
    return out


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
