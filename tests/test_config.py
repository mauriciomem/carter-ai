"""Tests for the risk-based strictness policy model (RFC-0002 / ADR-0005, P1 step 1).

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
    TOOL_RISK_MAP,
    effective_allowlist,
    effective_tool_risk_map,
    generate_default_config,
    load_config,
    most_restrictive_gate,
    resolve_action_gate,
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
        """DEFAULT_CONFIG ships the four policy control keys."""
        policy = DEFAULT_CONFIG["policy"]
        assert policy["level"] == "loose"
        assert policy["unknown_tool"] == "ask"
        assert policy["overrides"] == {}
        assert policy["audit_overrides"] is True

    def test_existing_config_omitting_policy_resolves_loose(self, tmp_path):
        """Q6: an existing config with no policy block defaults to loose (no behaviour change)."""
        cfg_path = tmp_path / "carter.yaml"
        cfg_path.write_text(yaml.dump(_minimal_existing_config()))
        merged = load_config(cfg_path)
        assert merged["policy"]["level"] == "loose"

    def test_new_install_defaults_guarded(self):
        """Q6: a freshly generated config (new install) defaults to guarded."""
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
        import yaml as _yaml

        from carter.config import policy_frontmatter

        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        cfg["policy"]["level"] = "guarded"
        cfg["policy"]["overrides"] = {"R2": "deny"}  # tighten ask -> deny
        block = _yaml.safe_load(policy_frontmatter(cfg, "devops"))
        assert block["policy"]["gates"]["R2"] == "deny"

    def test_override_reflected_in_gate_table(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded", "overrides": {"R3": "ask"}}})
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["R3"] == "ask"  # overridden from the guarded default (gate)

    def test_no_override_uses_taxonomy_default(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded"}})
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["R2"] == "ask"  # unchanged shipped default

    def test_override_only_affects_named_category(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded", "overrides": {"R2": "deny"}}})
        gates = {r["category"]: r["gate"] for r in rows}
        assert gates["R2"] == "deny"
        assert gates["R3"] == "gate"  # untouched


class TestPolicyLevelValidation:
    """`load_config` must reject an unknown policy.level at the boundary rather
    than crashing with a KeyError deep in rendering (audit medium)."""

    def test_invalid_level_raises_config_error(self, tmp_path):
        import yaml as _yaml

        from carter.config import ConfigError, load_config

        cfg = {
            "version": "2",
            "workspace": {"name": "x", "mode": "umbrella"},
            "identity": {"git_account": "y"},
            "agents": ["maestro"],
            "policy": {"level": "strikt"},
        }
        path = tmp_path / "carter.yaml"
        path.write_text(_yaml.dump(cfg))
        with pytest.raises(ConfigError, match="policy.level"):
            load_config(path)

    def test_valid_levels_accepted(self, tmp_path):
        import yaml as _yaml

        from carter.config import load_config

        for level in ("loose", "guarded", "strict"):
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

        path = self._write(tmp_path, {"level": "guarded", "overrides": {"R2": "nuke"}})
        with pytest.raises(ConfigError, match="overrides"):
            load_config(path)

    def test_invalid_override_category_raises(self, tmp_path):
        from carter.config import ConfigError, load_config

        path = self._write(tmp_path, {"level": "guarded", "overrides": {"R9": "deny"}})
        with pytest.raises(ConfigError, match="category"):
            load_config(path)


class TestShippedMapsAreDictShaped:
    def test_taxonomy_is_dict_with_all_levels(self):
        """The R0-R6 taxonomy is a dict; every category maps all three levels."""
        assert isinstance(RISK_TAXONOMY, dict)
        assert set(RISK_TAXONOMY) == {"R0", "R1", "R2", "R3", "R4", "R5", "R6"}
        for gates in RISK_TAXONOMY.values():
            assert {"loose", "guarded", "strict"} <= set(gates)

    def test_tool_risk_map_is_dict(self):
        """The tool->risk map is dict-shaped (tool -> category), never a list."""
        assert isinstance(TOOL_RISK_MAP, dict)
        assert all(isinstance(v, str) for v in TOOL_RISK_MAP.values())

    def test_allowlist_is_dict_of_dicts(self):
        """The per-agent allowlist is agent -> {category: bool}, never a list."""
        assert isinstance(AGENT_ALLOWLIST, dict)
        for cats in AGENT_ALLOWLIST.values():
            assert isinstance(cats, dict)
            assert all(isinstance(v, bool) for v in cats.values())

    def test_devops_is_sole_pusher_narrator_sole_author(self):
        """The shipped allowlist encodes the single-pusher / sole-author invariant."""
        assert AGENT_ALLOWLIST["devops"]["R2"] is True
        assert "R2" not in AGENT_ALLOWLIST["narrator"]
        assert AGENT_ALLOWLIST["narrator"]["R6"] is True


class TestUserOverridesDoNotWipeShippedMaps:
    def test_tool_risk_override_merges_not_replaces(self):
        """A user tool->risk addition deep-merges; shipped entries survive (dict-shaped)."""
        config = {"policy": {"tool_risk": {"my_custom_tool": "R2"}}}
        effective = effective_tool_risk_map(config)
        # user addition is present
        assert effective["my_custom_tool"] == "R2"
        # every shipped entry survives the merge
        for tool, risk in TOOL_RISK_MAP.items():
            assert effective[tool] == risk

    def test_allowlist_override_merges_not_replaces(self):
        """A user allowlist tweak deep-merges without wiping other shipped agents."""
        config = {"policy": {"allowlist": {"engineer": {"R2": True}}}}
        effective = effective_allowlist(config)
        # the shipped sole-pusher agent is untouched
        assert effective["devops"]["R2"] is True
        # the user's extension applied on top of engineer's shipped categories
        assert effective["engineer"]["R0"] is True
        assert effective["engineer"]["R2"] is True

    def test_no_policy_overrides_returns_shipped_defaults(self):
        """With no overrides, the effective maps equal the shipped maps."""
        assert effective_tool_risk_map({}) == TOOL_RISK_MAP
        assert effective_allowlist({}) == AGENT_ALLOWLIST


class TestGatePrecedence:
    def test_most_restrictive_gate_orders_allow_ask_gate_deny(self):
        assert most_restrictive_gate(["allow", "ask"]) == "ask"
        assert most_restrictive_gate(["ask", "deny", "gate"]) == "deny"
        assert most_restrictive_gate(["gate", "ask"]) == "gate"
        assert most_restrictive_gate(["allow"]) == "allow"

    def test_most_restrictive_gate_empty_defaults_allow(self):
        assert most_restrictive_gate([]) == "allow"

    def test_resolve_action_gate_push_force_is_destructive(self):
        """push --force = R2 (remote-write) and R5 (destructive); guarded -> gate (strictest)."""
        assert resolve_action_gate(["R2", "R5"], "guarded") == "gate"

    def test_resolve_action_gate_destroy_denied_at_strict(self):
        """terraform destroy = R3 and R5; strict -> deny."""
        assert resolve_action_gate(["R3", "R5"], "strict") == "deny"

    def test_resolve_action_gate_read_always_allowed(self):
        assert resolve_action_gate(["R0"], "strict") == "allow"
