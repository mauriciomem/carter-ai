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

from carter.install.console import _log, log_ok, log_step, log_warn

# Env vars the shipped MCP configs (mcp/*/*.json) read. carter-atlassian is the
# official remote server (OAuth in the client), so it needs none.
REQUIRED_ENV_VARS = (
    "GITHUB_TOKEN",
    "TFE_TOKEN",
)


# Minimum supported OpenCode release (the first with V2 permissions).
MIN_OPENCODE = (2, 1)

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
    log_ok("opencode", ".".join(map(str, version)))
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
        result = subprocess.run([cmd, flag], capture_output=True, text=True, timeout=10)
        return result.stdout.strip().split("\n")[0] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def detect_environment() -> None:
    """Log the OS, Python and uv versions."""
    log_step("Detecting environment...")
    uv_ver = _cmd_version("uv", "--version")
    uv = uv_ver.replace("uv ", "") if uv_ver else "not found"
    _log(f"  OS: {platform.system()} | Python: {platform.python_version()} | uv: {uv}")


def check_credentials() -> None:
    """Warn about unset env vars the shipped MCP configs read. Never fails."""
    log_step("Checking credentials...")
    for var in REQUIRED_ENV_VARS:
        if os.environ.get(var):
            log_ok(var)
        else:
            log_warn(var, f'export {var}="your-value"')
