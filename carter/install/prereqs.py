"""Environment detection and prerequisite/credential checks.

OpenCode is the only supported harness: ``require_opencode`` fails the install
hard when ``opencode`` is missing or older than ``MIN_OPENCODE``.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from carter.home import tilde
from carter.identity.errors import E_OPENCODE_VERSION
from carter.install.console import _log, log_ok, log_step, log_warn
from carter.install.paths import token_path

# Env vars the shipped MCP configs (mcp/*/*.json) read. carter-atlassian is the
# official remote server (OAuth in the client), so it needs none. carter-github reads
# a file, not the environment (see `check_credentials`).
REQUIRED_ENV_VARS = ("TFE_TOKEN",)


# Minimum supported OpenCode release (the first with V2 permissions).
MIN_OPENCODE = (2, 1)
# The newest OpenCode the Carter plugin was proven against. Older 2.1.x
# and newer releases still install, with a warning: G2 relies on the plugin's self-test there.
TESTED_OPENCODE = (2, 1, 4)
FIRST_PLUGIN_BAND = (2, 1, 4)

_VERSION_RE = re.compile(r"\bv?(\d+)\.(\d+)(?:\.(\d+))?")


class PrerequisiteError(RuntimeError):
    """A hard install prerequisite is missing; nothing has been written."""


def parse_opencode_version(output: str) -> tuple[int, int, int] | None:
    """Parse ``opencode --version`` output (e.g. ``opencode v2.1.4``).

    Tolerates a leading ``v`` and a pre-release/build suffix (``2.1.0-beta.1``).
    Returns ``None`` when no ``MAJOR.MINOR`` version is present.
    """
    match = _VERSION_RE.search(output)
    if not match:
        return None
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch or 0)


def version_band(version: tuple[int, int, int]) -> str:
    """``too-old`` (< 2.1), ``untested-low`` (2.1.0 to 2.1.3), ``tested``, ``above`` (newer)."""
    if version[:2] < MIN_OPENCODE:
        return "too-old"
    if version < FIRST_PLUGIN_BAND:
        return "untested-low"
    return "above" if version > TESTED_OPENCODE else "tested"


def require_opencode() -> tuple[int, int, int]:
    """Fail hard unless ``opencode`` is on PATH and at least ``MIN_OPENCODE``.

    Raises:
        PrerequisiteError: ``opencode`` is missing, its version is unreadable, or
            it is older than ``MIN_OPENCODE``.
    """
    minimum = ".".join(map(str, MIN_OPENCODE))
    hint = f"Install or upgrade OpenCode (>= {minimum}): https://opencode.ai/v2/docs/"
    if not _which("opencode"):
        raise PrerequisiteError(f"opencode not found on PATH. {hint}")
    output = _cmd_version("opencode", "--version")
    version = parse_opencode_version(output or "")
    if version is None:
        raise PrerequisiteError(
            f"Could not read the OpenCode version from `opencode --version` "
            f"(got {output!r}). {hint}"
        )
    if version[:2] < MIN_OPENCODE:
        shown = ".".join(map(str, version))
        raise PrerequisiteError(f"OpenCode {shown} is too old. {hint}")
    shown = ".".join(map(str, version))
    if version_band(version) in ("untested-low", "above"):
        log_warn(
            "opencode",
            f"the guards are untested on {shown}; relying on the plugin's own check "
            f"({E_OPENCODE_VERSION})",
        )
    else:
        log_ok("opencode", shown)
    return version


def check_optional_tools() -> None:
    """Report optional tools (``gh`` for carter-ops). Never fails the install."""
    if _which("gh"):
        log_ok("gh CLI", (_cmd_version("gh") or "")[:30])
    else:
        log_warn("gh CLI not found (optional)")


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _cmd_version(cmd: str, flag: str = "--version") -> str | None:
    try:
        result = subprocess.run(
            [cmd, flag],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # no controlling terminal: nothing can print behind our back
        )
        return result.stdout.strip().split("\n")[0] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def detect_environment() -> None:
    """Log the OS, Python and uv versions."""
    log_step("Detecting environment...")
    uv_ver = _cmd_version("uv", "--version")
    uv = uv_ver.replace("uv ", "") if uv_ver else "not found"
    _log(f"OS: {platform.system()} | Python: {platform.python_version()} | uv: {uv}", level=2)


def check_credentials(base_dir: Path | None = None) -> None:
    """Warn about credentials the shipped MCP configs read. Never fails.

    ``carter-github`` reads the read-only token from ``~/.carter/secrets/gh-read.token``
    (set with `carter github-token set`), never from an exported variable."""
    log_step("Checking credentials...")
    token = token_path(base_dir)
    if token.is_file() and not token.is_symlink():
        log_ok("GitHub read-only token", tilde(token))
    else:
        log_warn(
            "GitHub read-only token not found",
            "Run `carter github-token set` in your own terminal (a read-only fine-grained token).",
        )
    for var in REQUIRED_ENV_VARS:
        if os.environ.get(var):
            log_ok(var)
        else:
            log_warn(var, f'export {var}="your-value"')
