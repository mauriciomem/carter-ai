"""The real plugin (``carter/plugin/{index,core}.ts``) loaded by a real OpenCode (plan 004 step 16).

A smoke test, opt-in (``CARTER_E2E=1``), on the primary binary and ``CARTER_E2E_OPENCODE_ALT``.
The python interpreter in ``isolation.json`` is a shell script that stands in for the gate
(allow, or deny when the command says so) and for the identity entry, because the Python gate
arrives in M3. Step 32 turns this into the full compatibility contract.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from carter.identity import isolation
from e2e.harness import Rig

pytestmark = pytest.mark.e2e

PLUGIN_SRC = Path(__file__).resolve().parents[2] / "carter" / "plugin"
FAKE_PYTHON = """#!/bin/sh
LOG=%(home)s/fakepy.log
case "$*" in
  *carter.identity.env*)
    echo tier >> $LOG
    echo '{"schema_version":1,"tier":"t0","cap":null,"effective":"t0",'\
'"require_tier":null,"reason":null}'
    exit 0 ;;
esac
CMD=$(cat)
printf 'gate args=%%s cmd=%%s\\n' "$*" "$CMD" >> $LOG
case "$CMD" in
  *PLEASE_DENY*)
    echo '{"decision":"deny","rule":"push-verbs","message":'\
'"Refused by the Carter command gate (rule `push-verbs`): test."}'
    exit 1 ;;
esac
echo '{"decision":"allow","rule":null,"message":null}'
exit 0
"""
NAMES = (
    "env | cut -d= -f1 | grep -E '^(AGENT|SSH_AUTH_SOCK|GITHUB_TOKEN|GH_TOKEN|CARTER_.*"
    "|GIT_CONFIG_COUNT|GIT_SSH_COMMAND)$' | sort | tr '\\n' ' '"
)


def iso_bytes(home: Path) -> bytes:
    doc = isolation.render(
        home=str(home),
        python_path=str(home / "fakepy"),
        carter_path=str(home / "carter"),
        false_path="/usr/bin/false",
    )
    return isolation.canonical_bytes(doc)


def make(rig_factory, opencode_bin, *, tamper: bool = False) -> Rig:
    def index_ts(home: Path) -> str:
        sha = isolation.sha256_hex(iso_bytes(home))
        text = (PLUGIN_SRC / "index.ts").read_text()
        return text.replace("__CARTER_ISOLATION_SHA256__", sha).replace(
            "__CARTER_VERSION__", "0.0-e2e"
        )

    def iso_json(home: Path) -> str:
        text = iso_bytes(home).decode()
        return (
            text.replace('"GIT_TERMINAL_PROMPT":"0"', '"GIT_TERMINAL_PROMPT":"1"')
            if tamper
            else text
        )

    return rig_factory(
        opencode=opencode_bin,
        extra_files={
            ".config/opencode/plugins/carter/index.ts": index_ts,
            ".config/opencode/plugins/carter/core.ts": (PLUGIN_SRC / "core.ts").read_text(),
            ".carter/isolation.json": iso_json,
            "fakepy": lambda home: FAKE_PYTHON % {"home": home},
        },
        executable=["fakepy"],
        server_env_extra={"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"},
    )


def status(rig: Rig) -> list[dict]:
    files = sorted((rig.home / ".carter/run/plugin-status").glob("*.json"))
    return [json.loads(f.read_text()) for f in files]


def run_shell(rig: Rig, command: str) -> str:
    sid = rig.new_session()
    seen = len(rig.results())
    rig.prompt(sid, f"RUN {command}")
    return str(rig.wait_results(seen + 1)[-1]["result"])


def wait_status(rig: Rig, state: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        rows = status(rig)
        if rows and rows[0]["state"] == state:
            return rows[0]
        time.sleep(0.2)
    raise AssertionError(f"status never became {state}: {status(rig)}")


def test_loads_isolates_the_agent_shell_and_passes_the_self_test(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    (first,) = status(rig)
    assert first["state"] == "unproven" and first["opencode_version"] == opencode_bin.version
    assert first["plugin_version"] == "0.0-e2e"
    assert first["isolation_sha256"] == isolation.sha256_hex(iso_bytes(rig.home))

    names = set(run_shell(rig, NAMES).split())
    assert "CARTER_AGENT_SHELL" in names and "AGENT" in names  # AD1 sees both
    assert names.isdisjoint({"SSH_AUTH_SOCK", "GITHUB_TOKEN", "CARTER_HUMAN_SHELL"})
    assert {"GH_TOKEN", "GIT_CONFIG_COUNT", "GIT_SSH_COMMAND"} <= names
    assert run_shell(rig, "printenv GIT_CONFIG_COUNT").strip() == "13"
    assert wait_status(rig, "passed")["failed_reason"] is None
    log = (rig.home / "fakepy.log").read_text()
    assert f"--cwd {rig.ws}" in log  # the session directory comes from ctx.session.get (G6)
    assert "-I -m carter.gate --json" in log and "tier" in log


def test_a_bang_shell_is_untouched_and_gets_the_human_tag_only_after_a_pass(
    rig_factory, opencode_bin
) -> None:
    rig = make(rig_factory, opencode_bin)

    def bang() -> set[str]:
        sid = rig.new_session()
        rig.bang(sid, NAMES)
        deadline = time.time() + 10
        while time.time() < deadline:
            shells = [
                m
                for m in rig.api("GET", f"/api/session/{sid}/context")["data"]
                if m["type"] == "shell"
            ]
            if shells and shells[0].get("status") == "exited":
                return set(shells[0]["output"]["output"].split())
            time.sleep(0.2)
        raise AssertionError("no output")

    early = bang()
    assert "SSH_AUTH_SOCK" in early and not early & {
        "CARTER_HUMAN_SHELL",
        "CARTER_AGENT_SHELL",
        "GH_TOKEN",
    }
    run_shell(rig, "true")
    wait_status(rig, "passed")
    late = bang()
    assert "CARTER_HUMAN_SHELL" in late and "SSH_AUTH_SOCK" in late  # tagged, never isolated
    assert not late & {"AGENT", "CARTER_AGENT_SHELL", "GH_TOKEN", "GIT_CONFIG_COUNT"}


def test_a_gate_deny_reaches_the_model_and_the_command_never_runs(
    rig_factory, opencode_bin
) -> None:
    rig = make(rig_factory, opencode_bin)
    witness = rig.ws / "ran"
    result = json.loads(run_shell(rig, f"touch {witness}; echo PLEASE_DENY"))
    assert (
        result["error"]["message"]
        == "Refused by the Carter command gate (rule `push-verbs`): test."
    )
    assert not witness.exists()
    assert status(rig)[0]["state"] == "unproven"  # a rejection does not fail the self-test


def test_a_subagent_shell_is_isolated_too(rig_factory, opencode_bin) -> None:
    rig = make(rig_factory, opencode_bin)
    sid = rig.new_session()
    rig.prompt(sid, f"TASK RUN {NAMES}")
    results = rig.wait_results(2)
    names = set(str(results[0]["result"]).split())
    assert "CARTER_AGENT_SHELL" in names and "SSH_AUTH_SOCK" not in names


def test_a_tampered_isolation_file_refuses_agent_shells_but_not_the_humans(
    rig_factory, opencode_bin
) -> None:
    rig = make(rig_factory, opencode_bin, tamper=True)
    result = json.loads(run_shell(rig, "echo should-not-run"))
    assert result["error"]["message"].startswith(
        "E-ISOLATION-MISSING: Carter isolation file is missing"
    )
    sid = rig.new_session()
    rig.bang(sid, "echo human-ok")
    deadline = time.time() + 10
    while time.time() < deadline:
        shells = [
            m for m in rig.api("GET", f"/api/session/{sid}/context")["data"] if m["type"] == "shell"
        ]
        if shells and shells[0].get("status") == "exited":
            assert shells[0]["output"]["output"].strip() == "human-ok"
            return
        time.sleep(0.2)
    raise AssertionError("the human shell did not run")
