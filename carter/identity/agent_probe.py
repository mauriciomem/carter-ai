"""One probe of the dedicated agent.

``show``, ``unlock``, ``lock``, ``check --host`` and ``carter commit`` all call ``probe``. It reads
exit codes, never ``ssh-add`` prose (the one thing read from ``ssh-add -l`` is the fingerprint
column, compared with the configured key). A hung agent counts as stale (a SIGSTOP'd agent blocks
``ssh-add -l``); the timeout is short on purpose.

====================  ==========================================================
state                 meaning
====================  ==========================================================
``none``              no socket file
``bad``               something is at the path that is not our socket: never touched
``stale``             exit 2 (connection refused), a timeout, or an unusable agent
``empty``             agent up, no keys (locked, or the key expired)  [exit 1]
``wrong-key``         agent up, keys loaded, the configured fingerprint is not one of them
``ok``                the configured key is loaded
====================  ==========================================================

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from carter.identity.agent_paths import child_env

PROBE_TIMEOUT = 2.0


@dataclass(frozen=True)
class Probe:
    state: str
    detail: str = ""  # a short technical hint, never key material

    @property
    def live(self) -> bool:
        """An agent answered (it may be empty or hold another key)."""
        return self.state in ("empty", "wrong-key", "ok")


def classify_path(sock: Path, euid: int | None = None) -> str:
    """``none``, ``bad`` or ``socket`` from one ``lstat``: only our own socket is trusted."""
    uid = os.geteuid() if euid is None else euid
    try:
        info = os.lstat(sock)
    except FileNotFoundError:
        return "none"
    except OSError:
        return "bad"
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISSOCK(info.st_mode) or info.st_uid != uid:
        return "bad"
    return "socket"


def probe(
    sock: Path,
    ssh_bin_dir: str,
    fingerprint: str | None = None,
    *,
    home: Path | None = None,
    timeout: float = PROBE_TIMEOUT,
) -> Probe:
    """The state of the agent at ``sock``. ``fingerprint`` None: any loaded key counts as ``ok``."""
    kind = classify_path(sock)
    if kind != "socket":
        return Probe(kind)
    argv = [os.path.join(ssh_bin_dir, "ssh-add"), "-l"]
    try:
        done = subprocess.run(
            argv,
            env=child_env(home, sock),
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # no controlling terminal: it can never prompt
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Probe("stale", "timeout")
    except OSError as exc:
        return Probe("stale", f"cannot run ssh-add ({type(exc).__name__})")
    if done.returncode == 1:
        return Probe("empty")
    if done.returncode != 0:
        return Probe("stale", f"ssh-add -l exit {done.returncode}")
    if fingerprint is None or any(
        line.split()[1:2] == [fingerprint] for line in done.stdout.splitlines()
    ):
        return Probe("ok")
    return Probe("wrong-key")
