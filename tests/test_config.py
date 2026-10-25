"""Tests for the risk-based strictness policy model (ADR-0005).

The model layer only: the `policy` config block, the shipped R0-R6 taxonomy,
the tool->risk map, and the per-agent allowlist. No emission or enforcement yet.
Everything user-extensible is dict-shaped so `_deep_merge` (which replaces lists
wholesale) merges overrides instead of wiping the shipped defaults.
"""

from __future__ import annotations

import pytest
import yaml

from carter.config import (
    AGENT_ALLOWLIST,
    DEFAULT_CONFIG,
    RISK_TAXONOMY,
    ConfigError,
    effective_allowlist,
    generate_default_config,
    load_config,
)


def _minimal_existing_config() -> dict:
    """A valid carter.yaml with NO policy block (an existing, pre-policy config)."""
    return {
        "version": "2",
        "workspace": {"name": "legacy", "mode": "umbrella"},
        "identity": {"git_account": "someone"},
        "agents": ["maestro", "engineer"],
    }


class TestPolicyBlock:
    def test_default_config_has_policy_control_keys(self):
        """DEFAULT_CONFIG ships the policy control keys; `guarded` is the floor."""
        policy = DEFAULT_CONFIG["policy"]
        assert policy == {"level": "guarded", "overrides": {}}

    def test_existing_config_omitting_policy_resolves_guarded(self, tmp_path):
        """ADR-0010 D3: an existing config with no policy block resolves to `guarded`
        (the floor and default for everything)."""
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(_minimal_existing_config()))
        merged = load_config(cfg_path)
        assert merged["policy"]["level"] == "guarded"

    def test_stale_loose_level_resolves_guarded_silently(self, tmp_path):
        """ADR-0010 D3: a stale `level: loose` from a prior install loads as
        `guarded` — no error, no migration notice, via the normal default path
        (no dedicated `loose` coercion branch). Any unrecognized level does the same.
        """
        cfg = _minimal_existing_config()
        cfg["policy"] = {"level": "loose"}
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        merged = load_config(cfg_path)  # must NOT raise
        assert merged["policy"]["level"] == "guarded"

    def test_new_install_defaults_guarded(self):
        """A freshly generated config (new install) defaults to guarded."""
        cfg = generate_default_config()
        assert cfg["policy"]["level"] == "guarded"

    def test_policy_block_is_independent_per_generation(self):
        """Mutating a generated policy block must not corrupt DEFAULT_CONFIG."""
        cfg = generate_default_config()
        cfg["policy"]["overrides"]["R2"] = "deny"
        assert DEFAULT_CONFIG["policy"]["overrides"] == {}


class TestPolicyOverridesAreHonored:
    """`policy.overrides` (category -> gate) must actually change the emitted
    gate map and the gate table — not silently no-op (audit HIGH-1)."""

    def test_override_tightens_emitted_gate(self):
        from carter.config import permission_rules

        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        cfg["policy"]["level"] = "guarded"
        cfg["policy"]["overrides"] = {"remote-write": "deny"}  # tighten ask -> deny
        rules = permission_rules(cfg, "devops")
        assert {"action": "shell", "resource": "git push *", "effect": "deny"} in rules

    def test_override_reflected_in_gate_table(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table(
            {"policy": {"level": "guarded", "overrides": {"dangerous": "ask"}}}
        )
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["dangerous"] == "ask"  # overridden from the guarded default (gate)

    def test_no_override_uses_taxonomy_default(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded"}})
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["remote-write"] == "ask"  # unchanged shipped default

    def test_override_only_affects_named_category(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table(
            {"policy": {"level": "guarded", "overrides": {"remote-write": "deny"}}}
        )
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["remote-write"] == "deny"
        assert gates["dangerous"] == "gate"  # untouched


class TestPolicyLevelValidation:
    """ADR-0010 D3: `guarded`/`strict` are the only levels; an out-of-vocabulary
    `policy.level` (a stale `loose`, a typo) normalizes to the `guarded` default at
    the boundary rather than raising — no dedicated migration branch. Override
    category/gate typos still fail fast."""

    def test_unknown_level_normalizes_to_guarded(self, tmp_path):
        import yaml as _yaml

        from carter.config import load_config

        cfg = {
            "version": "2",
            "workspace": {"name": "x", "mode": "umbrella"},
            "identity": {"git_account": "y"},
            "agents": ["maestro"],
            "policy": {"level": "strikt"},
        }
        path = tmp_path / "carter.yaml"
        path.write_text(_yaml.dump(cfg))
        # Unknown level resolves to guarded via the default path (no raise).
        assert load_config(path)["policy"]["level"] == "guarded"

    def test_valid_levels_accepted(self, tmp_path):
        import yaml as _yaml

        from carter.config import load_config

        for level in ("guarded", "strict"):
            cfg = {
                "version": "2",
                "workspace": {"name": "x", "mode": "umbrella"},
                "identity": {"git_account": "y"},
                "agents": ["maestro"],
                "policy": {"level": level},
            }
            path = tmp_path / f"carter-{level}.yaml"
            path.write_text(_yaml.dump(cfg))
            assert load_config(path)["policy"]["level"] == level

    def _write(self, tmp_path, policy):
        import yaml as _yaml

        cfg = {
            "version": "2",
            "workspace": {"name": "x", "mode": "umbrella"},
            "identity": {"git_account": "y"},
            "agents": ["maestro"],
            "policy": policy,
        }
        path = tmp_path / "carter.yaml"
        path.write_text(_yaml.dump(cfg))
        return path

    def test_invalid_override_gate_raises(self, tmp_path):
        from carter.config import ConfigError, load_config

        path = self._write(tmp_path, {"level": "guarded", "overrides": {"remote-write": "nuke"}})
        with pytest.raises(ConfigError, match="overrides"):
            load_config(path)

    def test_invalid_override_category_raises(self, tmp_path):
        from carter.config import ConfigError, load_config

        path = self._write(tmp_path, {"level": "guarded", "overrides": {"bogus-cat": "deny"}})
        with pytest.raises(ConfigError, match="category"):
            load_config(path)


class TestProfileValidation:
    """The optional cost `profile:` key is validated at the
    config boundary: unset/None or a known profile name, else a loud ConfigError.
    """

    def _write(self, tmp_path, profile):
        cfg = {
            "version": "2",
            "workspace": {"name": "x", "mode": "umbrella"},
            "identity": {"git_account": "y"},
            "agents": ["maestro"],
            "profile": profile,
        }
        path = tmp_path / "carter.yaml"
        path.write_text(yaml.dump(cfg))
        return path

    def test_valid_profiles_accepted(self, tmp_path):
        from carter.config import load_config

        for profile in ("quality", "budget"):
            path = self._write(tmp_path, profile)
            assert load_config(path)["profile"] == profile

    def test_unknown_profile_raises(self, tmp_path):
        from carter.config import ConfigError, load_config

        path = self._write(tmp_path, "cheapest")
        with pytest.raises(ConfigError, match="profile"):
            load_config(path)

    def test_absent_profile_is_fine(self, tmp_path):
        # No `profile:` key at all → resolves to the shipped default tiers, no error.
        from carter.config import load_config

        cfg = {
            "version": "2",
            "workspace": {"name": "x", "mode": "umbrella"},
            "identity": {"git_account": "y"},
            "agents": ["maestro"],
        }
        path = tmp_path / "carter.yaml"
        path.write_text(yaml.dump(cfg))
        assert load_config(path).get("profile") is None


class TestShippedMapsAreDictShaped:
    def test_taxonomy_is_dict_with_all_levels(self):
        """The 4-category taxonomy (ADR-0010 D4) is a dict; every category maps both
        levels. Secret-access merged into remote-write; the standalone category and
        the R6 overlay are gone."""
        assert isinstance(RISK_TAXONOMY, dict)
        assert set(RISK_TAXONOMY) == {"read", "local-write", "remote-write", "dangerous"}
        for gates in RISK_TAXONOMY.values():
            assert {"guarded", "strict"} <= set(gates)

    def test_remote_write_gates(self):
        """remote-write (incl. secret reads) asks at guarded and gates at strict."""
        assert RISK_TAXONOMY["remote-write"]["guarded"] == "ask"
        assert RISK_TAXONOMY["remote-write"]["strict"] == "gate"

    def test_allowlist_is_dict_of_dicts(self):
        """The per-agent allowlist is agent -> {category: bool}, never a list."""
        assert isinstance(AGENT_ALLOWLIST, dict)
        for cats in AGENT_ALLOWLIST.values():
            assert isinstance(cats, dict)
            assert all(isinstance(v, bool) for v in cats.values())

    def test_devops_is_sole_remote_write_and_dangerous_holder(self):
        """ADR-0010 D4: devops is the sole holder of remote-write AND dangerous (the
        single-pusher invariant); narrator is first-class {read, local-write} and
        does NOT hold remote-write — it reaches it only via the redaction handoff to devops."""
        assert AGENT_ALLOWLIST["devops"]["remote-write"] is True
        assert AGENT_ALLOWLIST["devops"]["dangerous"] is True
        for role, cats in AGENT_ALLOWLIST.items():
            if role != "devops":
                assert "remote-write" not in cats, f"{role} unexpectedly holds remote-write"
                assert "dangerous" not in cats, f"{role} unexpectedly holds dangerous"
        assert AGENT_ALLOWLIST["narrator"] == {"read": True, "local-write": True}


class TestUserOverridesDoNotWipeShippedMaps:
    def test_allowlist_override_merges_not_replaces(self):
        """A user allowlist tweak deep-merges without wiping other shipped agents."""
        config = {"policy": {"allowlist": {"engineer": {"remote-write": True}}}}
        effective = effective_allowlist(config)
        # the shipped sole-pusher agent is untouched
        assert effective["devops"]["remote-write"] is True
        # the user's extension applied on top of engineer's shipped categories
        assert effective["engineer"]["read"] is True
        assert effective["engineer"]["remote-write"] is True

    def test_no_policy_overrides_returns_shipped_defaults(self):
        """With no overrides, the effective allowlist equals the shipped one."""
        assert effective_allowlist({}) == AGENT_ALLOWLIST


class TestLegacyConfigKeysTolerated:
    def test_removed_keys_in_existing_config_still_load(self, tmp_path):
        """Keys Carter no longer reads (dropped as dead config) must not break
        loading an older carter.yaml — they are carried through and ignored."""
        cfg = _minimal_existing_config()
        cfg["workspace"]["description"] = "old"
        cfg["identity"].update({"git_org": "acme", "bot_email": "bot@x"})
        cfg["quality_gate"] = {"enabled": True, "max_iterations": 2, "trigger": "user-initiated"}
        cfg["redaction"] = {"enabled": False, "categories": ["secrets"]}
        cfg["state"] = {"git_tracked": True}
        cfg["plans"] = {"git_regime": "private"}
        cfg["policy"] = {
            "level": "guarded",
            "unknown_tool": "ask",
            "audit_overrides": True,
            "tool_risk": {"my_tool": "remote-write"},
        }
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(cfg))

        loaded = load_config(cfg_path)

        assert loaded["policy"]["level"] == "guarded"
        assert loaded["redaction"]["categories"] == ["secrets"]
        assert loaded["plans"]["step_file_threshold"] == 3

    @staticmethod
    def _inject_legacy_keys(cfg: dict) -> None:
        cfg["workspace"]["description"] = "old"
        cfg["identity"].update({"git_org": "acme", "bot_email": "bot@x"})
        cfg["quality_gate"]["trigger"] = "user-initiated"
        cfg["redaction"]["enabled"] = False
        cfg["state"] = {"git_tracked": True}
        cfg["plans"]["git_regime"] = "private"
        cfg["policy"].update(
            {
                "unknown_tool": "ask",
                "audit_overrides": True,
                "tool_risk": {"my_tool": "remote-write"},
            }
        )

    def test_legacy_keys_survive_update_and_check(self, tmp_path):
        """End to end through the real CLI: an older carter.yaml carrying every
        removed key still updates and passes `carter check` (drift lint included)."""
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        result = runner.invoke(main, ["init", str(tmp_path), "--no-git-state"])
        assert result.exit_code == 0, result.output

        cfg_path = tmp_path / ".carter" / "carter.yaml"
        cfg = yaml.safe_load(cfg_path.read_text())
        self._inject_legacy_keys(cfg)
        cfg_path.write_text(yaml.dump(cfg))

        result = runner.invoke(main, ["update", str(tmp_path)])
        assert result.exit_code == 0, result.output
        agents_dir = tmp_path / ".opencode" / "agents"
        assert len(list(agents_dir.glob("carter-*.md"))) == len(cfg["agents"])
        assert (tmp_path / "AGENTS.md").is_file()
        assert not (tmp_path / ".github").exists()

        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "drift" not in result.output.lower()
        # The legacy keys are still in the file, untouched (carried through, ignored).
        assert yaml.safe_load(cfg_path.read_text())["policy"]["tool_risk"] == {
            "my_tool": "remote-write"
        }


class TestDocsLanguage:
    def test_default_is_english(self):
        assert DEFAULT_CONFIG["docs_language"] == "en"
        assert generate_default_config()["docs_language"] == "en"

    def test_old_config_without_key_resolves_english(self, tmp_path):
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(_minimal_existing_config()))
        assert load_config(cfg_path)["docs_language"] == "en"

    @pytest.mark.parametrize("tag", ["en", "es", "pt-BR", "zh-Hant", "deu"])
    def test_valid_tags_load(self, tmp_path, tag):
        cfg = {**_minimal_existing_config(), "docs_language": tag}
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        assert load_config(cfg_path)["docs_language"] == tag

    @pytest.mark.parametrize("tag", ["", "english!", "e", "pt_BR", 42, None])
    def test_invalid_tags_rejected(self, tmp_path, tag):
        cfg = {**_minimal_existing_config(), "docs_language": tag}
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError, match="docs_language"):
            load_config(cfg_path)

    def test_init_seeds_docs_language(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main, ["init", str(tmp_path), "--no-git-state", "--docs-language", "es"]
        )
        assert result.exit_code == 0, result.output
        cfg = yaml.safe_load((tmp_path / ".carter" / "carter.yaml").read_text())
        assert cfg["docs_language"] == "es"

    def test_init_rejects_bad_docs_language(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main, ["init", str(tmp_path), "--no-git-state", "--docs-language", "pt_BR"]
        )
        assert result.exit_code != 0
        assert "docs_language" in result.output
        assert not (tmp_path / ".carter").exists()


class TestTargetKeyRemoved:
    """ADR-0014 D4: `target:` is gone with no shim; a leftover key is a validation
    error whose message says exactly how to fix it."""

    def test_default_config_has_no_target(self):
        assert "target" not in DEFAULT_CONFIG
        assert "target" not in generate_default_config()

    def test_resolve_targets_is_gone(self):
        import carter.config

        assert not hasattr(carter.config, "resolve_targets")

    @pytest.mark.parametrize("value", ["copilot", "opencode", "all"])
    def test_leftover_target_is_rejected_with_fix(self, tmp_path, value):
        cfg = {**_minimal_existing_config(), "target": value}
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(cfg))
        with pytest.raises(ConfigError) as exc:
            load_config(cfg_path)
        msg = str(exc.value)
        assert "target" in msg
        assert "Delete the `target:` key" in msg
        assert "OpenCode >= 2.1" in msg

    def test_update_surfaces_target_error(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        assert runner.invoke(main, ["init", str(tmp_path), "--no-git-state"]).exit_code == 0
        cfg_path = tmp_path / ".carter" / "carter.yaml"
        cfg_path.write_text(cfg_path.read_text() + "target: copilot\n")
        result = runner.invoke(main, ["update", str(tmp_path)])
        assert result.exit_code != 0
        assert "Delete the `target:` key" in result.output

    def test_init_target_flag_is_gone(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main, ["init", str(tmp_path), "--no-git-state", "--target", "opencode"]
        )
        assert result.exit_code != 0
