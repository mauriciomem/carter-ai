"""Helpers for the compatibility contract: the REAL plugin, the REAL Python gate and the real
identity entry, loaded by a real OpenCode in an isolated HOME.

``install_files`` renders what ``carter guard install`` renders (the same functions), so a
contract test does not pay for a full install. ``test_g2_install.py`` runs the install itself.
"""

from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable
from pathlib import Path

from carter.guard import plugin
from carter.identity import isolation
from e2e.harness import Rig

SRC = Path(__file__).resolve().parents[2] / "carter" / "plugin"
PYTHON = sys.executable
CARTER_BIN = str(Path(sys.executable).parent / "carter")
NAMES = (
    "env | cut -d= -f1 | grep -E '^(AGENT|SSH_AUTH_SOCK|GITHUB_TOKEN|GH_TOKEN|CARTER_.*"
    "|GIT_CONFIG_COUNT|GIT_SSH_COMMAND|GH_CONFIG_DIR)$' | sort | tr '\\n' ' '"
)
# The rig's loopback-only network namespace is a user namespace: files owned by the real root show
# up as `nobody` inside it, so the root-ownership check for `false` (unit-tested in
# tests/identity) cannot pass there. This launcher stands in for that one check; everything else
# is the production CLI, unchanged.
LAUNCHER = (
    "import sys;"
    "from carter.identity import isolation as i;"
    "i.resolve_false = lambda *a, **k: '/usr/bin/false';"
    "from carter.cli import main;"
    "sys.argv[0] = 'carter';"
    "main()"
)


CARTER = [PYTHON, "-c", LAUNCHER]  # `carter <args>` for rig.run
SERVER_ENV = {"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"}


PythonPath = str | Callable[[Path], str]


def iso_bytes(home: Path, python_path: PythonPath = PYTHON) -> bytes:
    resolved = python_path(home) if callable(python_path) else python_path
    doc = isolation.render(
        home=str(home),
        python_path=resolved,
        carter_path=CARTER_BIN,
        false_path="/usr/bin/false",
        pat_file=f"{home}/.carter/secrets/gh-read.token",
    )
    return isolation.canonical_bytes(doc)


def install_files(
    *, python_path: PythonPath = PYTHON, tamper: str = ""
) -> dict[str, Callable[[Path], str]]:
    """``extra_files`` for a rig: plugin, core, isolation.json (optionally damaged)."""

    def index_ts(home: Path) -> str:
        sha = isolation.sha256_hex(iso_bytes(home, python_path))
        if tamper == "wrong-hash":
            sha = "0" * 64
        if tamper == "unrendered":
            return (SRC / "index.ts").read_text()
        return plugin.render_index(sha, "0.0-e2e")

    def iso_json(home: Path) -> str:
        return iso_bytes(home, python_path).decode()

    files: dict[str, Callable[[Path], str]] = {
        ".config/opencode/plugins/carter/index.ts": index_ts,
        ".config/opencode/plugins/carter/core.ts": lambda _h: (SRC / "core.ts").read_text(),
        ".config/opencode/plugins/carter/broker.ts": lambda _h: (SRC / "broker.ts").read_text(),
    }
    if tamper != "delete":
        files[".carter/isolation.json"] = iso_json
    return files


def make(rig_factory, opencode_bin, *, files=None, env=None, **kw) -> Rig:
    kw.setdefault("carter_agent", True)
    return rig_factory(
        opencode=opencode_bin,
        extra_files=files if files is not None else install_files(),
        server_env_extra={**SERVER_ENV, **(env or {})},
        **kw,
    )


def status(rig: Rig) -> list[dict]:
    """Status files, newest server first (a hot-loaded server leaves a file behind on restart)."""
    folder = rig.home / ".carter/run/plugin-status"
    rows = [json.loads(f.read_text()) for f in sorted(folder.glob("*.json"))]
    return sorted(rows, key=lambda r: r["boot"], reverse=True)


def wait_status(rig: Rig, state: str, timeout: float = 12.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = status(rig)
        if rows and rows[0]["state"] == state:
            return rows[0]
        time.sleep(0.2)
    raise AssertionError(f"status never became {state}: {status(rig)}")


def run_shell(rig: Rig, command: str, *, timeout: float = 40.0, agent: str | None = None) -> str:
    """An agent shell call through the mock model; returns the raw tool result. The session's
    agent is the rig's Carter agent unless ``agent`` names another one ()."""
    sid = rig.new_session(agent)
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return str(rig.wait_results(seen + 1, timeout=timeout)[-1]["result"])


def error_message(raw: str) -> str:
    try:
        return str(json.loads(raw)["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return ""


def bang(rig: Rig, command: str, timeout: float = 15.0) -> str:
    """The human's ``!`` shell (``/api/shell``)."""
    sid = rig.new_session()
    rig.bang(sid, command)
    deadline = time.time() + timeout
    while time.time() < deadline:
        shells = [
            m for m in rig.api("GET", f"/api/session/{sid}/context")["data"] if m["type"] == "shell"
        ]
        if shells and shells[0].get("status") == "exited":
            return str(shells[0]["output"]["output"])
        time.sleep(0.2)
    raise AssertionError("the ! shell produced no output")
