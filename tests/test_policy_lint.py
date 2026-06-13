"""Tests for the risk-based strictness policy lint (P3, RFC-0002 / ADR-0005).

Covers ``carter.scaffold.lint_policy`` — the deterministic, offline lint that
verifies the emitted agent frontmatter still matches the declared policy model —
and the ``carter check --accept-degraded`` CLI integration.
"""
from __future__ import annotations

import yaml
from click.testing import CliRunner

from carter.config import generate_default_config, load_config, policy_frontmatter, write_config
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
    parse each role's emitted policy frontmatter into a dict.
    """
    return {
        role: yaml.safe_load(policy_frontmatter(config, role))
        for role in config["agents"]
    }


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

    def test_loose_install_is_clean(self):
        cfg = _config(level="loose", target="opencode")
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

    def test_loose_redaction_off_does_not_warn(self):
        cfg = _config(level="loose", redaction=False)
        _, warnings = lint_policy(cfg, _installed(cfg))
        assert not any("redaction" in w for w in warnings)


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
        tampered = agent.read_text().replace("R2: ask", "R2: allow", 1)
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

        failed = runner.invoke(main, ["check", str(tmp_path)])
        assert failed.exit_code == 1, failed.output
        assert "accept-degraded" in failed.output

        ok = runner.invoke(main, ["check", str(tmp_path), "--accept-degraded"])
        assert ok.exit_code == 0, ok.output
