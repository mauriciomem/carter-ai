"""Environment detection and prerequisite/credential checks.

``check_prerequisites`` itself lives in ``carter.installer`` (it resolves ``_which``
through that module's namespace so tests can monkeypatch it); the leaf probes and the
non-coupled checks live here.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess

from carter.install.console import _log, log_ok, log_step, log_warn

# Env vars the shipped MCP configs (mcp/*/*.json) read. carter-atlassian is the
# official remote server (OAuth in the client), so it needs none.
REQUIRED_ENV_VARS = (
    "GITHUB_TOKEN",
    "TFE_TOKEN",
)


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _cmd_version(cmd: str, flag: str = "--version") -> str | None:
    try:
        result = subprocess.run([cmd, flag], capture_output=True, text=True, timeout=10)
        return result.stdout.strip().split("\n")[0] if result.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def detect_environment() -> dict:
    log_step("Detecting environment...")
    info = {
        "os": platform.system(),
        "os_version": platform.version().split()[0] if platform.version() else "unknown",
        "python": platform.python_version(),
    }
    uv_ver = _cmd_version("uv", "--version")
    info["uv"] = uv_ver.replace("uv ", "") if uv_ver else "not found"
    _log(f"  OS: {info['os']} | Python: {info['python']} | uv: {info['uv']}")
    return info


def check_credentials() -> dict[str, bool]:
    log_step("Checking credentials...")
    results: dict[str, bool] = {}

    for var in REQUIRED_ENV_VARS:
        val = os.environ.get(var)
        if val:
            log_ok(var)
            results[var] = True
        else:
            log_warn(var, f'export {var}="your-value"')
            results[var] = False

    return results
