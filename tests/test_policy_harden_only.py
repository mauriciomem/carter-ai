"""A workspace can only tighten agent permissions, never loosen them.

`.carter/carter.yaml` is writable by agents, so its `policy` block may only move toward
stricter: allowlist removals, overrides to a stricter gate, `level: strict`. Anything
looser than the code baseline is ignored and named in one short line by `update`/`check`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from click.testing import CliRunner

from carter.cli import main
from carter.config import (
    AGENT_ALLOWLIST,
    generate_default_config,
    ignored_policy_keys,
    permission_rules,
    policy_gate_table,
)

ROLES = tuple(AGENT_ALLOWLIST)

LOOSENING = {
    "allowlist": {"engineer": {"dangerous": True}, "pm": {"remote-write": True}},
    "overrides": {"dangerous": "allow", "remote-write": "ask"},
}


def _with_policy(**policy):
    config = generate_default_config()
    config["policy"].update(policy)
    return config


@pytest.mark.parametrize("role", ROLES)
def test_loosening_keys_render_the_same_permissions_as_the_baseline(role):
    config = _with_policy(**LOOSENING)
    assert permission_rules(config, role) == permission_rules(generate_default_config(), role)
    assert policy_gate_table(config) == policy_gate_table(generate_default_config())


def test_loosening_keys_are_named():
    assert ignored_policy_keys(_with_policy(**LOOSENING)) == [
        "policy.allowlist.engineer.dangerous",
        "policy.allowlist.pm.remote-write",
        "policy.overrides.dangerous",
    ]


def test_an_override_looser_than_the_chosen_level_is_ignored():
    config = _with_policy(level="strict", overrides={"remote-write": "ask"})
    assert ignored_policy_keys(config) == ["policy.overrides.remote-write"]
    gates = {row["category"]: row["gate"] for row in policy_gate_table(config)}
    assert gates["remote-write"] == "gate"  # the strict gate, not the override


@pytest.mark.parametrize(
    "policy",
    [
        {"level": "strict"},
        {"overrides": {"remote-write": "deny", "dangerous": "gate"}},
        {"allowlist": {"devops": {"dangerous": False}, "engineer": {"local-write": False}}},
        {"allowlist": {"engineer": {"read": True}}},  # already in the baseline
    ],
)
def test_tightening_keys_still_apply_and_are_not_reported(policy):
    config = _with_policy(**policy)
    assert ignored_policy_keys(config) == []


def test_tightening_changes_the_rendered_permissions():
    base = generate_default_config()
    strict = _with_policy(level="strict")
    assert permission_rules(strict, "devops") != permission_rules(base, "devops")
    no_danger = _with_policy(allowlist={"devops": {"dangerous": False}})
    deny = {"action": "shell", "resource": "terraform apply *", "effect": "deny"}
    assert deny in permission_rules(no_danger, "devops")
    assert deny not in permission_rules(base, "devops")


def test_the_default_config_ignores_nothing():
    assert ignored_policy_keys(generate_default_config()) == []


# ── the commands ─────────────────────────────────────────────────────────────


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    path = tmp_path / "ws"
    path.mkdir()
    assert CliRunner().invoke(main, ["init", str(path), "--no-git-state"]).exit_code == 0
    return path


def _write_policy(ws: Path, **policy) -> None:
    yml = ws / ".carter" / "carter.yaml"
    data = yaml.safe_load(yml.read_text())
    data["policy"].update(policy)
    yml.write_text(yaml.dump(data))


def _agent(ws: Path, role: str) -> str:
    return (ws / ".opencode" / "agents" / f"carter-{role}-local.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("command", ["update", "check"])
def test_the_command_prints_one_short_line_and_succeeds(ws, command):
    before = _agent(ws, "engineer")
    _write_policy(ws, **LOOSENING)
    args = [command, str(ws)] + (["--no-harness"] if command == "check" else [])
    result = CliRunner().invoke(main, args, env={"AGENT": "1"})
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if "loosening" in ln]
    assert len(lines) == 1
    assert "ignored 3 loosening keys" in lines[0]
    assert f"carter {command} --help" in lines[0]
    assert len(lines[0]) <= 80
    assert _agent(ws, "engineer") == before  # the agent file is the baseline's


def test_verbose_names_each_ignored_key(ws):
    _write_policy(ws, **LOOSENING)
    result = CliRunner().invoke(main, ["update", "-v", str(ws)])
    assert "policy.allowlist.engineer.dangerous" in result.output


def test_a_clean_workspace_prints_no_line(ws):
    result = CliRunner().invoke(main, ["update", str(ws)])
    assert result.exit_code == 0
    assert "loosening" not in result.output
