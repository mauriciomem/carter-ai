"""The signing shim ``~/.carter/bin/carter-ssh-sign`` (RFC-0007 App C.3, freeze H8/H9).

git calls it as ``gpg.ssh.program``. The generated POSIX script signs only the configured LLM key,
through the configured agent, and never prompts; it refuses everything else with ``E-SHIM-REFUSED``.
This module renders it from a template (every value goes through ``shlex.quote``, every path is
absolute, the bytes are deterministic) and holds the preflight for the minimum tool versions.
Recording the file's hash in ``guard-state.json`` is the caller's job (``identity add``).

Stdlib-only (see ``test_stdlib_only``).
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from carter.identity.errors import E_GIT_OLD, E_SHIM_REFUSED, E_SSH_OLD, IdentityError, registry
from carter.identity.isolation import resolve_false
from carter.identity.payload import shim_path
from carter.identity.rules import shim_data

__all__ = [
    "MIN_GIT_SIGNING",
    "MIN_OPENSSH",
    "ShimParams",
    "allowed_signers_path",
    "check_git",
    "check_openssh",
    "parse_version",
    "render",
    "resolve_false",
    "sha256_of",
    "shim_path",
    "write",
]

MIN_GIT_SIGNING = tuple(shim_data()["min_git"])  # -U for key:: literals arrived in git 2.40
MIN_OPENSSH = tuple(shim_data()["min_openssh"])  # SSH_ASKPASS_REQUIRE arrived in OpenSSH 8.4
_TEMPLATE = "carter-ssh-sign.sh"
_BANNER = "Managed by Carter"


def allowed_signers_path(home: Path | None = None) -> Path:
    """``~/.carter/hooks/allowed_signers`` (H2): the LLM key, one ``namespaces="git"`` line."""
    return (home or Path.home()) / ".carter" / "hooks" / "allowed_signers"


@dataclass(frozen=True)
class ShimParams:
    """Everything the generated script needs, as absolute paths and the configured key.

    ``sock`` is the dedicated agent's socket or the password manager's ``agent_socket``;
    empty for a ``program`` setup, which brings its own agent. ``signer`` is ``<ssh_bin_dir>/
    ssh-keygen`` unless ``program`` is set: only the *sign* operation goes to the program."""

    key: str  # "type base64", no comment
    sock: str
    false_path: str
    keygen: str
    run_dir: str
    signer: str = ""
    file_key: str = (
        ""  # D68 d: a passphrase-less private key; the shim signs from exactly this path
    )

    def checked(self) -> ShimParams:
        for name in ("sock", "false_path", "keygen", "run_dir", "signer", "file_key"):
            value = getattr(self, name)
            if value and not os.path.isabs(value):
                raise ValueError(f"{name} must be an absolute path")
        if len(self.key.split()) != 2 or "\n" in self.key:
            raise ValueError("key must be a single 'type blob' line")
        return self


def render(params: ShimParams) -> bytes:
    """The shim script for ``params``: deterministic, mode 0755 when written."""
    p = params.checked()
    template = resources.files("carter.identity").joinpath("templates", _TEMPLATE)
    text = template.read_text("utf-8")
    refusal = f"{E_SHIM_REFUSED}: {registry()[E_SHIM_REFUSED].message}"
    values = {
        "KEY": p.key,
        "SOCK": p.sock,
        "FALSE": p.false_path,
        "KEYGEN": p.keygen,
        "SIGNER": p.signer or p.keygen,
        "RUN_DIR": p.run_dir,
        "FILE_KEY": p.file_key,
        "REFUSAL": refusal,
    }
    for name, value in values.items():
        text = text.replace(f"@@{name}@@", shlex.quote(value))
    text = text.replace("@@ALLOWED@@", "|".join(shim_data()["y_ops"]))
    assert "@@" not in text and _BANNER in text
    return text.encode("utf-8")


def sha256_of(data: bytes) -> str:
    """The ``sha256:<hex>`` form ``guard-state.json`` records."""
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write(path: Path, data: bytes) -> bool:
    """Write the shim atomically (mode 0755, tmp in the same directory, fsync, rename).

    Returns False when the file already holds exactly ``data``."""
    with contextlib.suppress(OSError):
        if path.read_bytes() == data and os.access(path, os.X_OK):
            return False
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        os.fchmod(fd, 0o755)
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return True


def parse_version(output: str, pattern: str) -> tuple[int, ...] | None:
    """The first ``pattern`` match as a tuple of ints, e.g. ``OpenSSH_(\\d+)\\.(\\d+)``."""
    match = re.search(pattern, output)
    return tuple(int(g) for g in match.groups()) if match else None


Runner = Callable[[list[str]], str]


def _run(argv: list[str]) -> str:
    try:
        done = subprocess.run(
            argv, capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return done.stdout + done.stderr


def check_openssh(bin_dir: str, run: Runner = _run) -> tuple[int, ...]:
    """Raise ``E-SSH-OLD`` unless OpenSSH under ``bin_dir`` is at least ``MIN_OPENSSH``."""
    found = parse_version(run([os.path.join(bin_dir, "ssh"), "-V"]), r"OpenSSH_(\d+)\.(\d+)")
    if found is None or found < MIN_OPENSSH:
        raise IdentityError(E_SSH_OLD, detail=f"found {found or 'unknown'}, need {MIN_OPENSSH}")
    return found


def check_git(run: Runner = _run) -> tuple[int, ...]:
    """Raise ``E-GIT-OLD`` unless git is at least ``MIN_GIT_SIGNING`` (``-U`` for ``key::``)."""
    found = parse_version(run(["git", "--version"]), r"git version (\d+)\.(\d+)")
    if found is None or found < MIN_GIT_SIGNING:
        raise IdentityError(E_GIT_OLD, detail=f"found {found or 'unknown'}, need {MIN_GIT_SIGNING}")
    return found
