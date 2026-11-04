"""What the agent code needs from the config, and the checks before ``ssh-add`` (freeze H10).

``Setup`` is plain data built once from ``config.toml``. ``no_passphrase`` is the D54 test (exit
code only); ``check_key_file`` gives a clearer message than ``ssh-add`` for common mistakes.

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from carter.identity.agent_paths import child_env, socket_path
from carter.identity.payload import public_blob
from carter.identity.schema import IdentityConfig

_TTL = re.compile(r"[1-9][0-9]*[smhdwSMHDW]?")


@dataclass(frozen=True)
class Setup:
    """What the agent code needs, as plain data (built once from the config)."""

    home: Path
    ssh_bin_dir: str
    ttl: str
    blob: str  # "type base64"
    fingerprint: str
    private_key: str  # "" for a password-manager setup
    managed_externally: bool
    sock: Path


def setup_from_config(
    cfg: IdentityConfig, home: Path | None = None, env: Mapping[str, str] | None = None
) -> Setup:
    """Raises ``ValueError`` when the config has no usable key material (callers say E-CONFIG)."""
    base = home or Path.home()
    s = cfg.signing
    blob = public_blob(s.public_key)
    if not blob or not s.fingerprint:
        raise ValueError("no public key or fingerprint configured")
    external = bool(s.agent_socket or s.program)
    if not external and not s.private_key_path:
        raise ValueError("no private_key_path configured")
    return Setup(
        base, s.ssh_bin_dir, parse_ttl(s.ttl), blob, s.fingerprint, s.private_key_path, external,
        socket_path(base, env),
    )  # fmt: skip


def parse_ttl(text: str) -> str:
    """A lifetime ``ssh-add -t`` accepts: seconds or ``<n>[smhdw]``. ``ValueError`` otherwise."""
    if not _TTL.fullmatch(text.strip()):
        raise ValueError("a lifetime like 8h, 30m or 3600")
    return text.strip()


def check_key_file(path: str) -> str | None:
    """Why ``path`` cannot be the private key (``missing``, ``not-a-file``, ``too-open``), checked
    with ``stat`` only, before ``ssh-add`` gives a worse message. ``None`` when it looks usable."""
    try:
        info = os.stat(path)
    except OSError:
        return "missing"
    if not stat.S_ISREG(info.st_mode):
        return "not-a-file"
    if info.st_mode & 0o077:
        return "too-open"
    return None


def no_passphrase(setup: Setup) -> bool:
    """D54: ``ssh-keygen -y -P '' -f <key>`` with all stdio on ``/dev/null``; **exit code only**.
    Exit 0 means the key opens without a passphrase. Every other result (a passphrase, a missing or
    unreadable file, an unsupported format) is "not proven", and ``ssh-add`` reports the rest."""
    done = subprocess.run(
        [os.path.join(setup.ssh_bin_dir, "ssh-keygen"), "-y", "-P", "", "-f", setup.private_key],
        env=child_env(setup.home),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        timeout=15,
        check=False,
    )
    return done.returncode == 0
