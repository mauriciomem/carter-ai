"""Where the dedicated ssh-agent lives, and the checks on those paths.

Socket: ``$XDG_RUNTIME_DIR/carter/agent.sock`` when that directory is set, absolute and owned by
the user; on macOS ``$TMPDIR/carter-<uid>/agent.sock``; otherwise ``~/.carter/run/agent.sock``.
The pidfile and the lock always live in ``~/.carter/run/`` (a ``$TMPDIR`` purge must not orphan an
agent that can no longer be verified). Directories are 0700, owned by the user, never symlinks; the
socket path stays below the AF_UNIX limit (104 bytes on macOS, 108 on Linux). Violations raise
``E-UNLOCK-PATH``; nothing here deletes a path that is not a socket.

Stdlib-only (see ``test_stdlib_only``). ``home`` is the user's home directory throughout.
"""

from __future__ import annotations

import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path

from carter.identity.errors import E_UNLOCK_PATH, IdentityError

SOCKET_LIMITS = {"darwin": 104, "linux": 108}
SOCKET_NAME = "agent.sock"


def run_dir(home: Path | None = None) -> Path:
    return (home or Path.home()) / ".carter" / "run"


def pidfile_path(home: Path | None = None) -> Path:
    return run_dir(home) / "agent.pid"


def lock_path(home: Path | None = None) -> Path:
    return run_dir(home) / "unlock.lock"


def socket_limit(platform: str | None = None) -> int:
    return SOCKET_LIMITS["darwin" if (platform or sys.platform) == "darwin" else "linux"]


def _usable_runtime_root(value: str | None, euid: int) -> Path | None:
    """A runtime base directory from the environment: absolute, a real directory, ours."""
    if not value or not os.path.isabs(value):
        return None
    try:
        info = os.lstat(value)
    except OSError:
        return None
    if stat.S_ISDIR(info.st_mode) and info.st_uid == euid:
        return Path(value)
    return None


def socket_path(
    home: Path | None = None,
    env: Mapping[str, str] | None = None,
    *,
    platform: str | None = None,
    euid: int | None = None,
) -> Path:
    """The dedicated agent's socket path (the one place that decides it; the shim bakes it in)."""
    env = os.environ if env is None else env
    uid = os.geteuid() if euid is None else euid
    if (platform or sys.platform) == "darwin":
        base = _usable_runtime_root(env.get("TMPDIR"), uid)
        if base is not None:
            return base / f"carter-{uid}" / SOCKET_NAME
    else:
        base = _usable_runtime_root(env.get("XDG_RUNTIME_DIR"), uid)
        if base is not None:
            return base / "carter" / SOCKET_NAME
    return run_dir(home) / SOCKET_NAME


def check_length(sock: Path, platform: str | None = None) -> None:
    """``E-UNLOCK-PATH`` when the path cannot be bound; the detail carries the hint."""
    limit = socket_limit(platform)
    size = len(os.fsencode(sock))
    if size >= limit:
        raise IdentityError(
            E_UNLOCK_PATH,
            detail=f"the socket path is {size} bytes; AF_UNIX allows fewer than {limit}. "
            "Shorten HOME or TMPDIR (or set XDG_RUNTIME_DIR to a short directory).",
        )


def ensure_private_dir(path: Path, euid: int | None = None) -> None:
    """Create ``path`` (0700) or verify it: not a symlink, a directory, owned by us. A loose mode
    is repaired; a foreign owner or a symlink is refused (``E-UNLOCK-PATH``)."""
    uid = os.geteuid() if euid is None else euid
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        old = os.umask(0o077)
        try:
            path.mkdir(parents=True, mode=0o700, exist_ok=True)
        finally:
            os.umask(old)
        info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise IdentityError(E_UNLOCK_PATH, detail=f"{path.name} is a symlink; refusing to use it")
    if not stat.S_ISDIR(info.st_mode):
        raise IdentityError(E_UNLOCK_PATH, detail=f"{path.name} is not a directory")
    if info.st_uid != uid:
        raise IdentityError(E_UNLOCK_PATH, detail=f"{path.name} is owned by another user")
    if stat.S_IMODE(info.st_mode) != 0o700:
        os.chmod(path, 0o700)


def child_env(home: Path | None = None, sock: Path | None = None, **extra: str) -> dict[str, str]:
    """The environment of every OpenSSH child: built from scratch, never the caller's. Only
    ``sock`` names an agent, there is no ``DISPLAY`` and askpass is not consulted."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home or Path.home()),
        "LANG": "C",
        "LC_ALL": "C",
        "SSH_ASKPASS_REQUIRE": "never",
    }
    if sock is not None:
        env["SSH_AUTH_SOCK"] = str(sock)
    env.update(extra)
    return env
