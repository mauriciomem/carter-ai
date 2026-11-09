"""Find the OpenCode server process(es) and read their environment **by name**.

``carter check --host`` asks whether the server was started from a polluted environment (an
agent signal, a human tag, Carter's own isolation markers): then the plugin cannot tell shells
apart. Linux reads ``/proc/<pid>/environ``; macOS has no such file, so ``ps eww`` is parsed (the
permission model of macOS 26 is a step-38 item). The values stay in memory for the exact-value
marker comparison and are never printed, logged or put in an exception.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

NAME_VALUE = re.compile(r"(?:^|\s)([A-Za-z_][A-Za-z0-9_]*)=")
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


def server_pids() -> list[int]:
    """Pids of the running OpenCode servers (``ps``)."""
    return pids_from_ps()


def pids_from_ps(*, runner: Runner = subprocess.run) -> list[int]:
    """Pids whose command is ``opencode`` running ``serve`` (the service and ``serve --port``)."""
    try:
        done = runner(
            ["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    pids: list[int] = []
    for line in done.stdout.splitlines():
        parts = line.split()
        is_server = len(parts) >= 3 and os.path.basename(parts[1]) == "opencode"
        if is_server and parts[0].isdigit() and "serve" in parts[2:4]:
            pids.append(int(parts[0]))
    return pids


def auto_pids(*, runner: Runner = subprocess.run) -> list[int]:
    """Pids of OpenCode processes started with ``--auto`` (every permission is accepted at once)."""
    try:
        done = runner(
            ["ps", "-axo", "pid=,args="], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found: list[int] = []
    for line in done.stdout.splitlines():
        parts = line.split()
        is_auto = (
            len(parts) >= 2 and os.path.basename(parts[1]) == "opencode" and "--auto" in parts[2:]
        )
        if is_auto and parts[0].isdigit():
            found.append(int(parts[0]))
    return found


def read_environ(
    pid: int, *, proc: Path = Path("/proc"), runner: Runner = subprocess.run
) -> dict[str, str] | None:
    """The environment of ``pid`` (``None`` when it cannot be read)."""
    try:
        raw = (proc / str(pid) / "environ").read_bytes()
    except OSError:
        raw = b""
    if raw:
        pairs = (item.partition(b"=") for item in raw.split(b"\0") if b"=" in item)
        return {k.decode("utf-8", "replace"): v.decode("utf-8", "replace") for k, _, v in pairs}
    try:  # macOS: `ps eww` prints the environment after the command
        done = runner(
            ["ps", "eww", "-o", "command=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0 or not done.stdout.strip():
        return None
    env: dict[str, str] = {}
    text = done.stdout.strip()
    matches = list(NAME_VALUE.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        env[m.group(1)] = text[m.end() : end].strip()
    return env or None


def names(env: Mapping[str, str]) -> list[str]:
    return sorted(env)
