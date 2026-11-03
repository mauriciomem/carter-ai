"""Helpers behind the hermetic fixture's host and network guards (plan 003, step 5).

Pure functions, so the guard logic itself can be unit-tested without touching anything real:

- ``digest_host`` / ``changed`` fingerprint the files a bug in slice 1G could rewrite
  (the human's git config, the OpenCode config, Carter's own state). Only hashes are kept,
  never contents.
- ``is_local_host`` / ``is_allowed_connect`` decide what a unit test may open a socket to.
"""

from __future__ import annotations

import hashlib
import ipaddress
import os
import socket
from pathlib import Path

# Relative to the home directory. Keep in sync with what 1G writes (RFC-0007 §4.4, §4.7).
HOST_FILES = (
    ".gitconfig",
    ".config/opencode/opencode.json",
    ".config/opencode/opencode.jsonc",
    ".carter/config.toml",
    ".carter/manifest.json",
    ".carter/guard-state.json",
    ".carter/gitconfig",
    ".config/git/config",
)

# Looked at by ``stat`` only (exists, size, mtime_ns): the content is a credential and is
# never read, not even to hash it.
STAT_ONLY_FILES = (".carter/secrets/gh-read.token",)

ABSENT = "absent"


class NetworkBlockedError(AssertionError):
    """A test tried to reach a non-local network address.

    An ``AssertionError`` (not ``OSError``) so ``except OSError`` in the code under test
    does not silently turn the leak into a "connection failed" path.
    """


def digest_host(home: Path) -> dict[str, str]:
    """Map each guarded relative path to ``sha256`` (plus symlink target), or ``absent``.

    ``STAT_ONLY_FILES`` map to ``stat:<size>:<mtime_ns>`` instead; they are never opened.

    A symlinked file (a dotfiles-managed ``~/.gitconfig``) is hashed through the link and its
    target is recorded too, so re-pointing the link counts as a change.
    """
    result: dict[str, str] = {}
    for rel in HOST_FILES:
        path = home / rel
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except FileNotFoundError:
            digest = ABSENT
        except OSError as exc:
            digest = f"unreadable:{type(exc).__name__}"
        if path.is_symlink():
            digest += f"->{os.readlink(path)}"
        result[rel] = digest
    for rel in STAT_ONLY_FILES:
        try:
            st = (home / rel).lstat()
        except FileNotFoundError:
            result[rel] = ABSENT
        except OSError as exc:
            result[rel] = f"unreadable:{type(exc).__name__}"
        else:
            result[rel] = f"stat:{st.st_size}:{st.st_mtime_ns}"
    return result


def changed(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Relative paths whose digest differs (created, modified, deleted or re-pointed)."""
    return sorted(rel for rel in before.keys() | after.keys() if before.get(rel) != after.get(rel))


def is_local_host(host: object) -> bool:
    """True for loopback addresses and ``localhost`` (and the empty/None wildcard)."""
    if host is None or host in ("", "localhost"):
        return True
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    if not isinstance(host, str):
        return False
    try:
        address = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def is_allowed_connect(address: object, family: int, unix_root: Path) -> bool:
    """May a unit test connect a socket to ``address``?

    Loopback IP sockets are allowed (``http.server`` tests). Unix sockets are allowed only
    under ``unix_root`` (pytest's temp tree), so a real ``SSH_AUTH_SOCK`` or a
    ``/run/user/...`` socket can never be reached.
    """
    if family == socket.AF_UNIX:
        if isinstance(address, bytes):
            address = os.fsdecode(address)
        if not isinstance(address, str) or address.startswith("\0"):
            return False
        return Path(address).resolve().is_relative_to(unix_root.resolve())
    if isinstance(address, tuple) and address:
        return is_local_host(address[0])
    return False
