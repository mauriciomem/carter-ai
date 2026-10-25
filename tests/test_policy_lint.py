"""Tests for the V2 ``permissions:`` emission and the policy lint.

Carter emits each agent's OpenCode V2 ``permissions:`` rule list (last match wins)
from the risk taxonomy x per-agent allowlist. ``carter check`` (``lint_policy``)
compares the emitted ``permissions:``/``model`` with what carter.yaml generates and
rejects any V1 frontmatter key. There is no ``<!-- carter:policy -->`` comment.
"""

from __future__ import annotations

import pytest
import yaml
from click.testing import CliRunner

from carter.config import (
    V1_AGENT_KEYS,
    generate_default_config,
    load_config,
    permission_rules,
    policy_frontmatter,
    write_config,
)
from carter.scaffold import create_env, lint_policy, render_agents

_ALL_ROLES = ["maestro", "architect", "engineer", "devops", "pm", "learner", "narrator", "security"]
_READ_ONLY = ("maestro", "architect", "learner")
_LOCAL_WRITE = ("engineer", "devops", "pm", "narrator", "security")


def _r(action: str, resource: str, effect: str) -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


# Steps 1-4 of the rule order (identical for every agent), in order.
_BASELINE = [
    _r("*", "*", "ask"),
    _r("read", "*", "allow"),
    _r("glob", "*", "allow"),
    _r("grep", "*", "allow"),
    _r("skill", "*", "allow"),
    _r("question", "*", "allow"),
    _r("read", "*.env", "ask"),
    _r("read", "*.env.*", "ask"),
    _r("read", "*.env.example", "allow"),
    _r("external_directory", "~/.carter/*", "allow"),
    _r("read", "~/.carter/*", "allow"),
]
_MEMORIES_EDIT = _r("edit", "~/.carter/memories/*", "allow")
_DANGEROUS = (
    "terraform apply *",
    "terraform destroy *",
    "kubectl apply *",
    "helm upgrade *",
    "rm -rf *",
    "git reset --hard *",
    "git push --force *",
)


_REMOTE_WRITE = (
    "git push *",
    "gh pr create *",
    "gh pr merge *",
    "gh pr comment *",
    "gh pr review *",
    "gh pr edit *",
    "gh issue create *",
    "gh issue comment *",
    "gh issue edit *",
    "gh release *",
    "gh api *",
    "vault read *",
    "vault write *",
)


def _shell(remote_write: str, dangerous: str) -> list[dict[str, str]]:
    return [_r("shell", cmd, remote_write) for cmd in _REMOTE_WRITE] + [
        _r("shell", cmd, dangerous) for cmd in _DANGEROUS
    ]


def _config(level: str = "guarded") -> dict:
    cfg = generate_default_config(workspace_name="lint", mode="single")
    cfg["agent_suffix"] = ""
    cfg["policy"]["level"] = level
    return cfg


def _installed(config: dict) -> dict[str, dict]:
    """{role: parsed frontmatter} as ``carter check`` builds it."""
    return {role: yaml.safe_load(policy_frontmatter(config, role)) for role in config["agents"]}


# ─── Rule order ──────────────────────────────────────────────────────────


class TestRuleOrder:
    def test_architect_read_only_exact_rules(self):
        expected = [
            *_BASELINE,
            _r("subagent", "*", "deny"),
            _r("edit", "*", "ask"),
            _r("shell", "*", "ask"),
            _r("webfetch", "*", "ask"),
            *_shell("deny", "deny"),
        ]
        assert permission_rules(_config(), "architect") == expected

    def test_maestro_exact_rules(self):
        expected = [
            *_BASELINE,
            _r("subagent", "*", "deny"),
            _r("subagent", "carter-*", "allow"),
            _r("edit", "*", "ask"),
            _r("shell", "*", "ask"),
            _r("webfetch", "*", "ask"),
            *_shell("deny", "deny"),
        ]
        assert permission_rules(_config(), "maestro") == expected

    def test_engineer_local_write_exact_rules(self):
        expected = [
            *_BASELINE,
            _MEMORIES_EDIT,
            _r("subagent", "*", "deny"),
            _r("edit", "*", "allow"),
            _r("shell", "*", "allow"),
            _r("webfetch", "*", "allow"),
            *_shell("deny", "deny"),
        ]
        assert permission_rules(_config(), "engineer") == expected

    def test_devops_guarded_gate_emitted_as_ask(self):
        # guarded: remote-write ask, dangerous gate -> ask.
        rules = permission_rules(_config("guarded"), "devops")
        assert rules[-len(_REMOTE_WRITE) - len(_DANGEROUS) :] == _shell("ask", "ask")

    def test_devops_strict(self):
        # strict: remote-write gate -> ask, dangerous deny.
        rules = permission_rules(_config("strict"), "devops")
        assert rules[-len(_REMOTE_WRITE) - len(_DANGEROUS) :] == _shell("ask", "deny")

    def test_overrides_are_honored(self):
        cfg = _config()
        cfg["policy"]["overrides"] = {"remote-write": "deny"}
        rules = permission_rules(cfg, "devops")
        assert _r("shell", "git push *", "deny") in rules
        assert _r("shell", "vault read *", "deny") in rules

    @pytest.mark.parametrize("cmd", ["gh pr create *", "gh api *", "vault read *"])
    def test_engineer_remote_denies_follow_shell_allow(self, cmd):
        # last match wins: the deny must come after the broad shell allow.
        rules = permission_rules(_config(), "engineer")
        allow_idx = rules.index(_r("shell", "*", "allow"))
        assert rules.index(_r("shell", cmd, "deny")) > allow_idx

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_baseline_first(self, role):
        assert permission_rules(_config(), role)[: len(_BASELINE)] == _BASELINE

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_effects_are_v2_vocabulary(self, role):
        for level in ("guarded", "strict"):
            for rule in permission_rules(_config(level), role):
                assert set(rule) == {"action", "resource", "effect"}
                assert rule["effect"] in {"allow", "ask", "deny"}

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_v2_action_names_only(self, role):
        actions = {r["action"] for r in permission_rules(_config(), role)}
        assert not actions & {"bash", "task"}

    @pytest.mark.parametrize("role", _LOCAL_WRITE)
    def test_memories_edit_only_for_local_write(self, role):
        assert _MEMORIES_EDIT in permission_rules(_config(), role)

    @pytest.mark.parametrize("role", _READ_ONLY)
    def test_no_memories_edit_for_read_only(self, role):
        assert _MEMORIES_EDIT not in permission_rules(_config(), role)

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_no_mcp_websearch_or_execute_rules(self, role):
        actions = {r["action"] for r in permission_rules(_config(), role)}
        assert not actions & {"websearch", "execute"}

    @pytest.mark.parametrize("role", [r for r in _ALL_ROLES if r != "maestro"])
    def test_specialists_cannot_launch_subagents(self, role):
        sub = [r for r in permission_rules(_config(), role) if r["action"] == "subagent"]
        assert sub == [_r("subagent", "*", "deny")]

    def test_maestro_glob_survives_agent_suffix(self):
        cfg = _config()
        cfg["agent_suffix"] = "local"
        rendered = render_agents(cfg, create_env())["carter-maestro-local.md"]
        fm = yaml.safe_load(rendered.split("---", 2)[1])
        assert _r("subagent", "carter-*", "allow") in fm["permissions"]


# ─── Emitted frontmatter shape ───────────────────────────────────────────────


class TestEmittedFrontmatter:
    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_no_v1_keys(self, role):
        fm = yaml.safe_load(policy_frontmatter(_config(), role))
        assert not set(fm) & set(V1_AGENT_KEYS)

    def test_v1_key_set(self):
        assert set(V1_AGENT_KEYS) == {"permission", "tools", "bash", "task", "name", "temperature"}


# ─── Lint ────────────────────────────────────────────────────────────────


class TestLint:
    def test_matching_install_is_clean(self):
        for level in ("guarded", "strict"):
            cfg = _config(level)
            assert lint_policy(cfg, _installed(cfg)) == []

    def test_permissions_tamper_is_drift(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["devops"]["permissions"][-1]["effect"] = "allow"
        errors = lint_policy(cfg, installed)
        assert any("devops" in e and "permissions" in e and "drifted" in e for e in errors)

    def test_reordered_rules_are_drift(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["architect"]["permissions"].reverse()
        assert any("architect" in e for e in lint_policy(cfg, installed))

    def test_missing_permissions_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        del installed["engineer"]["permissions"]
        assert any("engineer" in e and "permissions" in e for e in lint_policy(cfg, installed))

    def test_specialist_subagent_allow_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["engineer"]["permissions"].append(_r("subagent", "*", "allow"))
        assert any("engineer" in e for e in lint_policy(cfg, installed))

    def test_model_drift_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["pm"]["model"] = "openai/gpt-x"
        assert any("pm" in e and "model" in e for e in lint_policy(cfg, installed))

    @pytest.mark.parametrize("key", ["permission", "tools", "bash", "task", "name", "temperature"])
    def test_v1_key_is_error(self, key):
        cfg = _config()
        installed = _installed(cfg)
        installed["learner"][key] = "x"
        errors = lint_policy(cfg, installed)
        assert any("learner" in e and key in e and "V1" in e for e in errors)

    def test_absent_role_is_not_an_error(self):
        cfg = _config()
        installed = _installed(cfg)
        del installed["learner"]
        assert not any("learner" in e for e in lint_policy(cfg, installed))


# ─── carter check CLI integration ────────────────────────────────────────────


class TestCheckCliIntegration:
    def _init(self, tmp_path, *args):
        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state", *args])
        assert result.exit_code == 0, result.output
        return runner, main

    def test_fresh_init_checks_ok(self, tmp_path):
        runner, main = self._init(tmp_path)
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Workspace OK" in result.output

    def test_check_fails_on_tampered_permissions(self, tmp_path):
        runner, main = self._init(tmp_path)
        agent = next((tmp_path / ".opencode" / "agents").glob("carter-devops*.md"))
        _, fm_raw, body = agent.read_text().split("---", 2)
        fm = yaml.safe_load(fm_raw)
        fm["permissions"].append(_r("shell", "*", "allow"))
        fm["permissions"].append(_r("shell", "git push *", "allow"))
        agent.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---{body}")
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1, result.output
        assert "devops" in result.output and "drifted" in result.output

    def test_check_fails_on_widened_maestro_dispatch(self, tmp_path):
        runner, main = self._init(tmp_path)
        maestro = next((tmp_path / ".opencode" / "agents").glob("carter-maestro*.md"))
        _, fm_raw, body = maestro.read_text().split("---", 2)
        fm = yaml.safe_load(fm_raw)
        fm["permissions"].append(_r("subagent", "*", "allow"))
        maestro.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---{body}")
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1, result.output
        assert "maestro" in result.output

    def test_accept_degraded_flag_is_gone(self, tmp_path):
        runner, main = self._init(tmp_path)
        result = runner.invoke(main, ["check", str(tmp_path), "--accept-degraded"])
        assert result.exit_code != 0

    def test_strict_checks_ok_after_update(self, tmp_path):
        runner, main = self._init(tmp_path)
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        config = load_config(cfg_path)
        config["policy"]["level"] = "strict"
        write_config(cfg_path, config)
        assert runner.invoke(main, ["update", str(tmp_path)]).exit_code == 0
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output

    def test_init_surfaces_guarded_policy_notice(self, tmp_path):
        runner, main = self._init(tmp_path)
        result = runner.invoke(main, ["update", str(tmp_path)])
        assert "Strictness policy is 'guarded'" in result.output

    def test_stale_loose_resolves_guarded_on_update(self, tmp_path):
        runner, main = self._init(tmp_path)
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        raw = cfg_path.read_text().replace("level: guarded", "level: loose")
        cfg_path.write_text(raw)
        result = runner.invoke(main, ["update", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Strictness policy is 'guarded'" in result.output
        assert load_config(cfg_path)["policy"]["level"] == "guarded"
