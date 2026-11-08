"""The full ``carter guard install`` with ``g2`` revision 2, into an isolated HOME and an
isolated server (plan 004 step 32). This is the stand-in for the user's live install (step 40).
D71: the deny set lives in the Carter agents, so the shells below run as the rig's Carter agent;
the global OpenCode config gets no ``policies``, only the per-agent ``carter_push`` denies.

Nothing here touches the real ``~/.config/opencode`` or ``~/.carter``: Carter runs with the rig's
HOME and service port, against the rig's server, mock model only. Steps: install, restart,
the plugin loads, an agent shell is isolated, the real gate rejects ``git -C . push``, the human's
``!`` shell is untouched, ``guard remove --only plugin`` restores, the per-agent denies stay.
"""

from __future__ import annotations

import json
import time

import pytest

from carter import harness
from carter.install.paths import isolation_path, plugin_dir
from e2e.g2 import CARTER, NAMES, bang, error_message, run_shell, status, wait_status

pytestmark = pytest.mark.e2e

REFUSED = "Refused by the Carter command gate (rule `push-verbs`)"


def carter(rig, *args: str, timeout: float = 240.0):
    return rig.run([*CARTER, *args], timeout=timeout)


def state(rig) -> dict:
    return json.loads((rig.home / ".carter/guard-state.json").read_text())


def policies(rig) -> set[str]:
    merged = harness._resolve(json.loads(rig.debug("config")))
    return {
        f"{p['action']} {p['resource']}"
        for p in harness.policy_statements(merged)
        if p.get("effect") == "deny" and p.get("action") == "tool.use"
    }


def test_install_isolate_gate_and_restore(rig_factory, opencode_bin) -> None:
    rig = rig_factory(
        opencode=opencode_bin,
        carter_agent=True,
        server_env_extra={"SSH_AUTH_SOCK": "/tmp/fake-agent.sock", "GITHUB_TOKEN": "not-a-token"},
    )
    home = rig.home
    assert not (home / ".carter/isolation.json").exists()

    # 1. install (a bare --yes on a fresh machine follows C.6.2: g2 at revision 2 is asked and yes)
    dry = carter(rig, "guard", "install", "--dry-run")
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "would write" in dry.stdout and not (home / ".carter/isolation.json").exists()
    res = carter(rig, "guard", "install", "-v", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    assert "plugin installed:" in res.stdout and "restart the OpenCode server" in res.stdout
    assert state(rig)["consents"]["g2"]["rev"] == 3  # slice B: revision 3 carries the B tools
    assert isolation_path(None).name == "isolation.json"
    for path in (
        home / ".carter/isolation.json",
        home / ".config/opencode/plugins/carter/index.ts",
    ):
        assert path.exists(), path
    assert "pre-push" in (home / ".carter/gitconfig").read_text()
    assert not policies(rig) and "policies" not in json.loads(rig.config_file.read_text())
    assert state(rig)["opencode_policies"] == []  # D71: nothing global but the per-agent denies
    assert state(rig)["agent_permissions"]

    # 2. restart: the plugin loads
    rig.restart()
    first = status(rig)[0]  # the plugin was hot-loaded at install too: the old pid's file stays
    assert first["state"] == "unproven" and first["opencode_version"] == opencode_bin.version

    # 3. the agent shell is isolated: no SSH agent, a dummy GH_TOKEN, AD1 signals, the rest
    names = set(run_shell(rig, NAMES).split())
    assert {
        "CARTER_AGENT_SHELL",
        "AGENT",
        "GH_TOKEN",
        "GIT_CONFIG_COUNT",
        "GIT_SSH_COMMAND",
    } <= names
    assert names.isdisjoint({"SSH_AUTH_SOCK", "GITHUB_TOKEN", "CARTER_HUMAN_SHELL"})
    doc = json.loads((home / ".carter/isolation.json").read_text())
    assert run_shell(rig, "printenv GH_TOKEN").strip() == doc["plugin"]["gh_token_dummy"]
    wait_status(rig, "passed")

    # 4. the real gate rejects the push the literal policy cannot see
    witness = rig.ws / "ran"
    refused = error_message(run_shell(rig, f"git -C . push; touch {witness}"))
    assert refused.startswith(REFUSED) and not witness.exists()
    assert run_shell(rig, "echo allowed-ok").strip() == "allowed-ok"

    # 5. the human's ! shell is untouched (and tagged as human now that the self-test passed)
    human = set(bang(rig, NAMES).split())
    assert "SSH_AUTH_SOCK" in human and "CARTER_HUMAN_SHELL" in human
    assert not human & {"CARTER_AGENT_SHELL", "GH_TOKEN", "GIT_CONFIG_COUNT", "AGENT"}

    # 6. check --host sees a loaded, passing plugin (run from the rig, which has the server)
    check = carter(rig, "check", "--host", "-v")
    assert "plugin and isolation.json match (hash)" in check.stdout, check.stdout
    assert "self-test passed" in check.stdout, check.stdout
    # the rig's `carter-engineer` is a stand-in (no `carter install` ran), so the two rows about
    # its permissions are expected to be RED; anything else with a cross is a failure
    crosses = [ln for ln in (check.stdout + check.stderr).splitlines() if "\u2717" in ln]
    assert all("carter-engineer" in ln or ln.startswith("\u2717 host:") for ln in crosses), crosses

    # 7. remove --only plugin: the plugin side goes, the 1G denies, hooks and token stay
    res = carter(rig, "guard", "remove", "--yes", "--only", "plugin")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (home / ".carter/isolation.json").exists() and not plugin_dir(home).exists()
    assert not (home / ".carter/run").exists() or not (home / ".carter/run/gh-empty").exists()
    assert state(rig)["consents"]["g2"]["rev"] == 1 and state(rig)["agent_permissions"]
    assert (home / ".carter/hooks/carter-guard").exists() and (home / ".carter/gitconfig").exists()

    # 8. OpenCode unloads the deleted plugin (spike B 6d): the agent shell is no longer isolated
    deadline = time.time() + 30
    names = set()
    while time.time() < deadline:
        names = set(run_shell(rig, NAMES).split())
        if "SSH_AUTH_SOCK" in names:
            break
        time.sleep(1)
    assert "SSH_AUTH_SOCK" in names and "CARTER_AGENT_SHELL" not in names, names
    again = error_message(run_shell(rig, "git -C . log -1 --format=%s"))
    assert not again.startswith("Refused by the Carter command gate")

    # 9. a bare --yes does not bring the plugin back; --yes --only g2 does
    res = carter(rig, "guard", "install", "--yes")
    assert (
        "need your confirmation" in res.stdout + res.stderr
        and not (home / ".carter/isolation.json").exists()
    )
    res = carter(rig, "guard", "install", "--yes", "--only", "g2")
    assert res.returncode == 0 and (home / ".carter/isolation.json").exists(), res.stdout
    assert state(rig)["consents"]["g2"]["rev"] == 3  # slice B: revision 3 carries the B tools

    # 10. a full remove leaves nothing of Carter's but the documented keepers
    res = carter(rig, "guard", "remove", "--yes")
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (home / ".carter/guard-state.json").exists()
    assert not (home / ".carter/hooks/carter-guard").exists()
    assert "include" not in (home / ".gitconfig").read_text()
