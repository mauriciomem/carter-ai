"""The on-demand dedicated ssh-agent: unlock and lock (RFC-0007 §4.3 "Key custody", report 22 §4).

A library with no click and no terminal handling: the CLI passes ``run_with_terminal``, a callable
that runs ``ssh-add`` with the user's terminal attached (tests pass a PTY driver). Carter's process
never opens the private key; the passphrase goes from the terminal to ``ssh-add`` and nowhere else.

``unlock`` takes ``~/.carter/run/unlock.lock`` (flock), probes the socket, removes a stale socket
only after an ``lstat`` re-check, stops a verified orphan, starts ``ssh-agent`` when needed and
runs ``ssh-add -t <ttl> <private key>``. ``lock`` removes only the configured key (``ssh-add -d -``
with the public blob on stdin, so no private key and no temp file) and stops the agent when it is
empty and verified. Password-manager setups (``agent_socket`` / ``program``) are not managed here.

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import subprocess
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from carter.identity.agent_paths import (
    SOCKET_LIMITS,
    check_length,
    child_env,
    ensure_private_dir,
    lock_path,
    pidfile_path,
    run_dir,
)
from carter.identity.agent_probe import Probe, probe
from carter.identity.agent_proc import (
    agents_under,
    remove_stale_socket,
    start_agent,
    stop_agent,
    verified_agent,
)
from carter.identity.agent_setup import (
    Setup,
    check_key_file,
    no_passphrase,
    parse_ttl,
    setup_from_config,
)
from carter.identity.errors import E_UNLOCK_PATH, IdentityError

__all__ = [
    "SOCKET_LIMITS",
    "LockResult",
    "Setup",
    "UnlockResult",
    "check_key_file",
    "lock",
    "lock_path",
    "no_passphrase",
    "parse_ttl",
    "pidfile_path",
    "probe",
    "setup_from_config",
    "unlock",
]

Runner = Callable[[list[str], dict[str, str]], int]
LOCK_WAIT = 60.0


@contextlib.contextmanager
def _locked(path: Path) -> Iterator[None]:
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + LOCK_WAIT
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise IdentityError(
                        E_UNLOCK_PATH, detail="another unlock is still running"
                    ) from None
                time.sleep(0.1)
        yield
    finally:
        os.close(fd)  # closing releases the flock


def _prepare(setup: Setup) -> None:
    check_length(setup.sock)  # before anything is created
    ensure_private_dir(run_dir(setup.home))
    ensure_private_dir(setup.sock.parent)


def _probe(setup: Setup) -> Probe:
    return probe(setup.sock, setup.ssh_bin_dir, setup.fingerprint, home=setup.home)


@dataclass(frozen=True)
class UnlockResult:
    status: str  # unlocked | already-unlocked | failed
    returncode: int = 0
    started_agent: bool = False


def unlock(setup: Setup, run_with_terminal: Runner, *, extend: bool = False) -> UnlockResult:
    """Make sure the dedicated agent runs and holds the key (for ``setup.ttl`` when set).

    ``run_with_terminal(argv, env)`` runs ``ssh-add`` attached to the user's terminal and returns
    its exit code. A key that is already loaded is not asked for again unless ``extend`` (one
    prompt, and the lifetime is replaced)."""
    _prepare(setup)
    sock, pidfile = setup.sock, pidfile_path(setup.home)
    with _locked(lock_path(setup.home)):
        state = _probe(setup)
        started = False
        if state.state == "bad":
            detail = f"{sock.name} exists and is not our agent socket; not touching it"
            raise IdentityError(E_UNLOCK_PATH, detail=detail)
        if state.state in ("none", "stale"):
            orphan = verified_agent(pidfile, sock)
            if orphan is not None:
                stop_agent(orphan)
            if state.state == "stale":
                remove_stale_socket(sock)
            start_agent(setup.ssh_bin_dir, sock, pidfile, setup.home)
            started, state = True, _probe(setup)
        if state.state == "ok" and not extend:
            return UnlockResult("already-unlocked")
        lifetime = ["-t", setup.ttl] if setup.ttl else []  # D68 e: no lifetime by default
        argv = [os.path.join(setup.ssh_bin_dir, "ssh-add"), *lifetime, setup.private_key]
        code = run_with_terminal(argv, child_env(setup.home, sock))
        after = _probe(setup)
        if code == 0 and after.state == "ok":
            return UnlockResult("unlocked", 0, started)
        if started and after.state == "empty":  # nothing was loaded: do not leave an idle agent
            _stop_ours(setup)
        return UnlockResult("failed", code, started)


def _stop_ours(setup: Setup) -> bool:
    pid = verified_agent(pidfile_path(setup.home), setup.sock)
    if pid is not None:
        stop_agent(pid)
    remove_stale_socket(setup.sock)
    pidfile_path(setup.home).unlink(missing_ok=True)
    return pid is not None


@dataclass(frozen=True)
class LockResult:
    status: str  # locked | already-locked | failed
    agent_stopped: bool = False
    returncode: int = 0


def lock(setup: Setup, *, stop_all: bool = False) -> LockResult:
    """Remove only the configured key; stop the agent when it is empty (or with ``stop_all``,
    also every verified agent that names the Carter socket directory)."""
    _prepare(setup)
    with _locked(lock_path(setup.home)):
        state = _probe(setup)
        removed = state.state == "ok"
        code = 0
        if state.live and state.state != "empty":
            done = subprocess.run(
                [os.path.join(setup.ssh_bin_dir, "ssh-add"), "-d", "-"],
                input=setup.blob + "\n",
                env=child_env(setup.home, setup.sock),
                capture_output=True,
                text=True,
                start_new_session=True,
                timeout=10,
                check=False,
            )
            code = done.returncode  # 1 = "agent refused operation": already absent, a success
            if code not in (0, 1):
                return LockResult("failed", False, code)
        stopped = False
        if stop_all:
            for pid in agents_under(setup.sock.parent):
                stop_agent(pid)
                stopped = True
            stopped = _stop_ours(setup) or stopped
        elif state.live and _probe(setup).state == "empty":
            stopped = _stop_ours(setup)
        return LockResult("locked" if removed else "already-locked", stopped)
