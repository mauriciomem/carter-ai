"""Processes of the dedicated agent: start it, recognise it, stop it (freeze H11, report 22 §4).

A pid is only ever killed after ``verified_agent`` has seen ``ssh-agent`` and the socket path in its
command line. Stopping is TERM, a wait of about three seconds, then KILL (a SIGSTOP'd agent only
acts on TERM once continued; SIGKILL leaves the socket file behind, which is removed afterwards and
only if it is our own socket). ``ssh-agent -k`` is never used: it kills whatever ``SSH_AGENT_PID``
names.

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import contextlib
import os
import re
import signal
import subprocess
import time
from pathlib import Path

from carter.identity.agent_paths import child_env
from carter.identity.agent_probe import classify_path
from carter.identity.errors import E_UNLOCK_PATH, IdentityError

STOP_WAIT = 3.0


def _ps(*args: str) -> str:
    done = subprocess.run(
        ["ps", "-ww", *args], capture_output=True, text=True, stdin=subprocess.DEVNULL, check=False
    )
    return done.stdout


def alive(pid: int) -> bool:
    """Is ``pid`` a running process (a zombie awaiting its parent does not count)?"""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return not _ps("-p", str(pid), "-o", "stat=").strip().startswith("Z")


def is_ssh_agent(command: str) -> bool:
    """Is the program of this command line ``ssh-agent``? (Not a text that merely mentions it.)"""
    program = (
        command.strip().split(" -", 1)[0].strip()
    )  # up to the first option; spaces in a path ok
    return os.path.basename(program) == "ssh-agent"


def verified_agent(pidfile: Path, sock: Path) -> int | None:
    """The pid in ``pidfile`` if (and only if) it is an ``ssh-agent`` serving ``sock``."""
    try:
        text = pidfile.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text.isdigit():
        return None
    command = _ps("-p", text, "-o", "command=")
    return int(text) if is_ssh_agent(command) and str(sock) in command else None


def agents_under(directory: Path) -> list[int]:
    """Pids of ``ssh-agent`` processes of this user whose command line names ``directory``."""
    found = []
    for line in _ps("-u", str(os.getuid()), "-o", "pid=,command=").splitlines():
        pid, _, command = line.strip().partition(" ")
        if pid.isdigit() and is_ssh_agent(command) and f"{directory}{os.sep}" in command:
            found.append(int(pid))
    return found


def stop_agent(pid: int, wait: float = STOP_WAIT) -> str:
    """TERM, wait, KILL. Returns ``gone``, ``term`` or ``kill``."""
    if not alive(pid):
        return "gone"
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGCONT)
        os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not alive(pid):
            return "term"
        time.sleep(0.05)
    with contextlib.suppress(ProcessLookupError):
        os.kill(pid, signal.SIGKILL)
    time.sleep(0.1)
    return "kill"


def remove_stale_socket(sock: Path) -> bool:
    """Unlink ``sock`` only if a fresh ``lstat`` says it is our own socket. Call under the lock."""
    if classify_path(sock) != "socket":
        return False
    sock.unlink(missing_ok=True)
    return True


def start_agent(ssh_bin_dir: str, sock: Path, pidfile: Path, home: Path | None = None) -> int:
    """``ssh-agent -a <sock> -s`` (the agent has bound the socket when it returns), then the
    pidfile (0600). Raises ``E-UNLOCK-PATH`` when the agent cannot bind."""
    env = child_env(home)
    done = subprocess.run(
        [os.path.join(ssh_bin_dir, "ssh-agent"), "-a", str(sock), "-s"],
        env=env,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        timeout=10,
        check=False,
    )
    match = re.search(r"SSH_AGENT_PID=(\d+);", done.stdout)
    if done.returncode != 0 or not match:
        raise IdentityError(E_UNLOCK_PATH, detail="ssh-agent could not bind the dedicated socket")
    pid = int(match.group(1))
    fd = os.open(pidfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, f"{pid}\n".encode())
    finally:
        os.close(fd)
    return pid
