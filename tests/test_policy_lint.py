"""Tests for the risk-based strictness policy lint (P3, RFC-0002 / ADR-0005).

Covers ``carter.scaffold.lint_policy`` — the deterministic, offline lint that
verifies the emitted agent frontmatter still matches the declared policy model —
and the ``carter check --accept-degraded`` CLI integration.
"""

from __future__ import annotations

import yaml
from click.testing import CliRunner

from carter.config import (
    generate_default_config,
    load_config,
    parse_policy_comment,
    policy_comment,
    policy_frontmatter,
    write_config,
)
from carter.scaffold import lint_policy


def _config(level: str = "guarded", target: str = "copilot", redaction: bool = True) -> dict:
    """Default config pinned to a policy level + target, canonical agent names."""
    cfg = generate_default_config(workspace_name="lint", mode="single")
    cfg["agent_suffix"] = ""
    cfg["policy"]["level"] = level
    cfg["target"] = target
    cfg["redaction"]["enabled"] = redaction
    return cfg


def _installed(config: dict) -> dict[str, dict]:
    """Build the {role: parsed frontmatter} map the way ``carter check`` does:
    parse each role's native frontmatter and re-inject the ``policy`` block from
    its ``carter:policy`` comment (which is where the block now lives, off the wire).
    """
    installed = {}
    for role in config["agents"]:
        fm = yaml.safe_load(policy_frontmatter(config, role)) or {}
        fm["policy"] = parse_policy_comment(policy_comment(config, role))
        installed[role] = fm
    return installed


# ─── Drift detection (emitted frontmatter ↔ declared model) ──────────────────


class TestLintClean:
    """A matching install — emitted frontmatter == declared model — lints clean."""

    def test_matching_install_has_no_errors(self):
        cfg = _config(level="guarded", target="copilot")
        errors, _ = lint_policy(cfg, _installed(cfg))
        assert errors == []

    def test_matching_install_has_no_warnings(self):
        cfg = _config(level="guarded", target="copilot")  # not strict, redaction on
        _, warnings = lint_policy(cfg, _installed(cfg))
        assert warnings == []

    def test_guarded_opencode_install_is_clean(self):
        # guarded on an enforcing target (opencode) with redaction on: no hard-ack,
        # no redaction contradiction → clean.
        cfg = _config(level="guarded", target="opencode")
        errors, warnings = lint_policy(cfg, _installed(cfg))
        assert errors == []
        assert warnings == []


class TestLintDrift:
    """Tampering with emitted frontmatter is flagged as drift (an error)."""

    def test_allowlist_mismatch_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["devops"]["policy"]["allow"] = ["R0"]  # tampered
        errors, _ = lint_policy(cfg, installed)
        assert any("devops" in e and "allow" in e.lower() for e in errors)
        assert any("drifted from declared allowlist" in e for e in errors)

    def test_gate_mismatch_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        installed["devops"]["policy"]["gates"]["R2"] = "allow"  # guarded R2 is ask
        errors, _ = lint_policy(cfg, installed)
        assert any("devops" in e and "gate" in e.lower() for e in errors)

    def test_missing_policy_block_is_error(self):
        cfg = _config()
        installed = _installed(cfg)
        del installed["maestro"]["policy"]
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "policy" in e.lower() for e in errors)

    def test_absent_role_is_not_an_error(self):
        # A role in the model but not in `installed` is not lint's concern —
        # missing-file is handled by the existing `carter check` logic.
        cfg = _config()
        installed = _installed(cfg)
        del installed["learner"]
        errors, _ = lint_policy(cfg, installed)
        assert not any("learner" in e for e in errors)


class TestLintNativeKeyDrift:
    """The lint must also guard the ENFORCED native keys — OpenCode ``permission``
    and copilot ``tools`` — not only the advisory ``policy`` block (audit HIGH-2).
    """

    def test_permission_tamper_is_error(self):
        cfg = _config(level="strict", target="opencode")
        installed = _installed(cfg)
        # devops bash is `deny` at strict; tamper it to a permissive value.
        installed["devops"]["permission"]["bash"] = "allow"
        errors, _ = lint_policy(cfg, installed, accept_degraded=True)
        assert any("devops" in e and "permission" in e.lower() for e in errors)

    def test_tools_tamper_is_error(self):
        cfg = _config(level="guarded", target="copilot")
        installed = _installed(cfg)
        installed["devops"]["tools"] = ["carter-github/*", "carter-evil/*"]  # widened
        errors, _ = lint_policy(cfg, installed)
        assert any("devops" in e and "tools" in e.lower() for e in errors)

    def test_missing_permission_on_opencode_is_error(self):
        cfg = _config(level="guarded", target="opencode")
        installed = _installed(cfg)
        del installed["devops"]["permission"]
        errors, _ = lint_policy(cfg, installed)
        assert any("devops" in e and "permission" in e.lower() for e in errors)

    def test_matching_native_keys_are_clean(self):
        cfg = _config(level="strict", target="all")
        errors, _ = lint_policy(cfg, _installed(cfg), accept_degraded=True)
        assert not [e for e in errors if "permission" in e.lower() or "tools" in e.lower()]

    def test_overridden_install_has_no_false_drift(self):
        # A legitimately-overridden install emits gates the lint must accept.
        cfg = _config(level="guarded", target="opencode")
        cfg["policy"]["overrides"] = {"R2": "deny", "R3": "ask"}
        errors, _ = lint_policy(cfg, _installed(cfg))
        assert errors == []


# ─── HARD ACK (Q15): strict on a non-enforcing target fails closed ───────────


class TestHardAck:
    """``strict`` on a target that cannot enforce gates requires an explicit ack."""

    def test_strict_on_copilot_fails_closed(self):
        cfg = _config(level="strict", target="copilot")
        errors, _ = lint_policy(cfg, _installed(cfg), accept_degraded=False)
        assert any("accept-degraded" in e for e in errors)

    def test_strict_on_copilot_acknowledged(self):
        cfg = _config(level="strict", target="copilot")
        errors, warnings = lint_policy(cfg, _installed(cfg), accept_degraded=True)
        assert errors == []
        assert any("degrades to advisory" in w and "acknowledged" in w for w in warnings)

    def test_strict_on_opencode_no_degraded(self):
        cfg = _config(level="strict", target="opencode")  # opencode enforces
        errors, warnings = lint_policy(cfg, _installed(cfg), accept_degraded=False)
        assert not any("accept-degraded" in e for e in errors)
        assert not any("degrades to advisory" in w for w in warnings)

    def test_strict_on_all_degrades_only_on_copilot(self):
        cfg = _config(level="strict", target="all")
        errors, _ = lint_policy(cfg, _installed(cfg), accept_degraded=False)
        ack_errors = [e for e in errors if "accept-degraded" in e]
        assert len(ack_errors) == 1
        assert "copilot" in ack_errors[0]
        assert "opencode" not in ack_errors[0]  # opencode enforces, not degraded


# ─── Redaction WARN (Q16): guarded|strict + redaction off is a contradiction ──


class TestRedactionWarn:
    def test_guarded_redaction_off_warns(self):
        cfg = _config(level="guarded", redaction=False)
        _, warnings = lint_policy(cfg, _installed(cfg))
        assert any("redaction.enabled is false" in w for w in warnings)

    def test_strict_redaction_off_warns(self):
        cfg = _config(level="strict", target="opencode", redaction=False)
        _, warnings = lint_policy(cfg, _installed(cfg))
        assert any("redaction.enabled is false" in w and w.startswith("strict") for w in warnings)


# ─── Fail-closed dispatch lint (P3, RFC-0005 §1 D1.2 / ADR-0010 D1) ──────────


class TestDispatchLint:
    """The primary's dispatch allowlist is a security boundary: a ``'*'``, a glob,
    or an absent ``agents:``/``permission.task`` on the maestro is a fail-closed
    ERROR (exit non-zero), never a warning. An explicit per-specialist list passes.
    """

    def test_explicit_copilot_dispatch_is_clean(self):
        cfg = _config(level="guarded", target="copilot")
        errors, _ = lint_policy(cfg, _installed(cfg))
        assert not any("dispatch" in e.lower() for e in errors)

    def test_explicit_opencode_dispatch_is_clean(self):
        cfg = _config(level="guarded", target="opencode")
        errors, _ = lint_policy(cfg, _installed(cfg))
        assert not any("dispatch" in e.lower() for e in errors)

    def test_star_agents_is_error(self):
        cfg = _config(level="guarded", target="copilot")
        installed = _installed(cfg)
        installed["maestro"]["agents"] = ["*"]  # failure-open glob
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "agents" in e for e in errors)

    def test_glob_agents_is_error(self):
        cfg = _config(level="guarded", target="copilot")
        installed = _installed(cfg)
        installed["maestro"]["agents"] = ["carter-*"]  # auto-trusts future agents
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "agents" in e for e in errors)

    def test_absent_agents_is_error(self):
        cfg = _config(level="guarded", target="copilot")
        installed = _installed(cfg)
        del installed["maestro"]["agents"]
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "agents" in e for e in errors)

    def test_star_permission_task_is_error(self):
        cfg = _config(level="guarded", target="opencode")
        installed = _installed(cfg)
        installed["maestro"]["permission"]["task"] = {"*": "allow"}  # failure-open
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "task" in e for e in errors)

    def test_glob_permission_task_is_error(self):
        cfg = _config(level="guarded", target="opencode")
        installed = _installed(cfg)
        installed["maestro"]["permission"]["task"] = {"*": "deny", "carter-*": "allow"}
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "task" in e for e in errors)

    def test_absent_permission_task_is_error(self):
        cfg = _config(level="guarded", target="opencode")
        installed = _installed(cfg)
        installed["maestro"]["permission"].pop("task", None)
        errors, _ = lint_policy(cfg, installed)
        assert any("maestro" in e and "task" in e for e in errors)

    def test_dispatch_violation_is_error_not_warning(self):
        cfg = _config(level="guarded", target="copilot")
        installed = _installed(cfg)
        installed["maestro"]["agents"] = ["*"]
        errors, warnings = lint_policy(cfg, installed)
        assert any("dispatch" in e.lower() or "agents" in e for e in errors)
        assert not any("*" in w for w in warnings), "must be an error, never a warning"

    def test_check_fails_on_star_dispatch(self, tmp_path):
        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state"])
        assert result.exit_code == 0, result.output
        maestro = next((tmp_path / ".github" / "agents").glob("carter-maestro*.md"))
        # Rewrite the maestro frontmatter so its dispatch allowlist is the
        # failure-open glob `'*'` — parse, tamper, re-emit (robust to flow-style).
        text = maestro.read_text()
        _, fm_raw, body = text.split("---", 2)
        fm = yaml.safe_load(fm_raw)
        fm["agents"] = ["*"]
        maestro.write_text(f"---\n{yaml.safe_dump(fm, sort_keys=False)}---{body}")
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1, result.output
        assert "maestro" in result.output


# ─── N2: no false "server not wired" warning ─────────────────────────────────


class TestNoFalseMcpWarning:
    """The lint reads per-agent frontmatter scope only; global MCP wiring is out
    of scope, so it must never warn that a server is "not wired"."""

    def test_valid_config_emits_no_server_wiring_warning(self):
        cfg = _config()  # agents carry valid frontmatter
        _, warnings = lint_policy(cfg, _installed(cfg))
        assert not any("wired" in w.lower() or "mcp server" in w.lower() for w in warnings)


# ─── carter check --accept-degraded CLI integration ──────────────────────────


class TestCheckCliIntegration:
    def _init(self, tmp_path, *args):
        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state", *args])
        assert result.exit_code == 0, result.output
        return runner, main

    def test_check_fails_on_drifted_agent_frontmatter(self, tmp_path):
        runner, main = self._init(tmp_path)  # default: copilot, guarded
        agent = next((tmp_path / ".github" / "agents").glob("carter-devops*.md"))
        # The policy block now lives in the carter:policy comment (compact JSON),
        # off the wire; tamper it there to simulate drift.
        tampered = agent.read_text().replace('"remote-write":"ask"', '"remote-write":"allow"', 1)
        agent.write_text(tampered)
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 1, result.output
        assert "devops" in result.output
        assert "drifted" in result.output

    def test_accept_degraded_flag_is_accepted(self, tmp_path):
        runner, main = self._init(tmp_path)
        result = runner.invoke(main, ["check", str(tmp_path), "--accept-degraded"])
        assert result.exit_code == 0, result.output
        assert "Workspace OK" in result.output

    def test_strict_on_copilot_fails_closed_without_ack(self, tmp_path):
        runner, main = self._init(tmp_path)  # copilot, guarded
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        config = load_config(cfg_path)
        config["policy"]["level"] = "strict"
        write_config(cfg_path, config)
        # Re-emit agents at the new level so there is no drift — isolating the
        # hard-ack check (changing policy.level requires `carter update`).
        assert runner.invoke(main, ["update", str(tmp_path)]).exit_code == 0

        failed = runner.invoke(main, ["check", str(tmp_path)])
        assert failed.exit_code == 1, failed.output
        assert "accept-degraded" in failed.output

        ok = runner.invoke(main, ["check", str(tmp_path), "--accept-degraded"])
        assert ok.exit_code == 0, ok.output

    def test_check_warns_on_redaction_contradiction(self, tmp_path):
        runner, main = self._init(tmp_path)  # guarded, redaction on
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        config = load_config(cfg_path)
        config["redaction"]["enabled"] = False
        write_config(cfg_path, config)
        assert runner.invoke(main, ["update", str(tmp_path)]).exit_code == 0

        result = runner.invoke(main, ["check", str(tmp_path)])
        # guarded + redaction off is a contradiction → WARN, but not an error.
        assert result.exit_code == 0, result.output
        assert "redaction.enabled is false" in result.output

    def test_init_surfaces_guarded_policy_notice(self, tmp_path):
        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state"])
        assert result.exit_code == 0, result.output
        # New installs default to guarded → the policy notice surfaces.
        assert "Strictness policy is 'guarded'" in result.output

    def test_stale_loose_resolves_guarded_on_update(self, tmp_path):
        # ADR-0010 D3: a stale `level: loose` in carter.yaml resolves to guarded
        # silently (no error, no migration message). On update the guarded notice
        # then fires like any guarded workspace.
        runner, main = self._init(tmp_path)
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        # Write a stale loose level directly (bypassing validation) as a prior
        # install would have left it.
        raw = cfg_path.read_text().replace("level: guarded", "level: loose")
        cfg_path.write_text(raw)
        result = runner.invoke(main, ["update", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Strictness policy is 'guarded'" in result.output
        assert load_config(cfg_path)["policy"]["level"] == "guarded"
