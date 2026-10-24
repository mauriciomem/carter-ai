"""Tests for per-agent model emission.

Carter pins a per-target `model:` string on each agent, resolved from a dedicated
`models:` block by `overrides > profile > tier > default`. Thinkers (maestro,
architect, learner, security) = Opus 5.5; implementers (engineer, devops, pm,
narrator) = Sonnet 5.5. Haiku 5.5 is opt-in via `overrides` only. The `profile:` key
(quality|budget) can re-tier at resolve time. The emitted value is a SINGLE string
(an array breaks Copilot CLI): a display name for VS Code/Copilot, a `provider/model`
ID for OpenCode. `carter check` prints a required unverifiable-model advisory. No
effort key; no `temperature`.

Model ids (OpenCode catalog): `anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-5-5`,
`anthropic/claude-haiku-5-5`; Copilot display names "Claude Opus 5.5" etc.
"""

from __future__ import annotations

import yaml

from carter.config import (
    DEFAULT_CONFIG,
    generate_default_config,
    policy_frontmatter,
    policy_native_keys,
    resolve_model,
)

# Default tiers after RFC-0004 lever 1 / plan 007: pm + narrator ship on Sonnet.
THINKERS = ("maestro", "architect", "learner", "security")
IMPLEMENTERS = ("engineer", "devops", "pm", "narrator")


def _config(target: str = "copilot") -> dict:
    cfg = generate_default_config(workspace_name="models", mode="single")
    cfg["agent_suffix"] = ""
    cfg["target"] = target
    return cfg


# ─── The models: block shape ─────────────────────────────────────────────────


class TestModelsBlock:
    def test_default_config_has_models_block(self):
        assert "models" in DEFAULT_CONFIG

    def test_models_block_is_dict_shaped(self):
        # Dict-shaped so `_deep_merge` doesn't wipe it (same footgun as the taxonomy
        # maps). Each tier maps target -> model string.
        models = DEFAULT_CONFIG["models"]
        for key in ("default", "thinkers", "implementers", "overrides"):
            assert key in models, f"models block missing '{key}'"
            assert isinstance(models[key], dict)

    def test_thinkers_tier_is_opus(self):
        models = DEFAULT_CONFIG["models"]
        assert models["thinkers"]["copilot"] == "Claude Opus 5.5"
        assert models["thinkers"]["opencode"] == "anthropic/claude-opus-5-5"

    def test_implementers_tier_is_sonnet(self):
        models = DEFAULT_CONFIG["models"]
        assert models["implementers"]["copilot"] == "Claude Sonnet 5.5"
        assert models["implementers"]["opencode"] == "anthropic/claude-sonnet-5-5"

    def test_default_tier_is_opus_catch_all(self):
        # `default` is the un-tiered catch-all so a future agent never resolves empty.
        models = DEFAULT_CONFIG["models"]
        assert models["default"]["copilot"] == "Claude Opus 5.5"
        assert models["default"]["opencode"] == "anthropic/claude-opus-5-5"

    def test_overrides_default_empty(self):
        assert DEFAULT_CONFIG["models"]["overrides"] == {}

    def test_models_block_survives_deep_merge(self):
        # A partial user config that doesn't mention models must keep the shipped block.
        from carter.config import _merge_with_defaults

        merged = _merge_with_defaults(
            {"version": "2", "workspace": {}, "identity": {}, "agents": ["maestro"]}
        )
        assert merged["models"]["thinkers"]["copilot"] == "Claude Opus 5.5"


# ─── Resolution: overrides > tier > default ──────────────────────────────────


class TestResolveModel:
    def test_thinkers_resolve_to_opus(self):
        cfg = _config(target="copilot")
        for role in THINKERS:
            assert resolve_model(cfg, role) == "Claude Opus 5.5", role

    def test_implementers_resolve_to_sonnet(self):
        cfg = _config(target="copilot")
        for role in IMPLEMENTERS:
            assert resolve_model(cfg, role) == "Claude Sonnet 5.5", role

    def test_narrator_and_pm_default_to_sonnet(self):
        # RFC-0004 lever 1 / plan 007: pm + narrator ship on Sonnet by DEFAULT (both
        # cleared the adherence gate). A regression here re-inflates the Opus bill.
        for target, sonnet in (
            ("copilot", "Claude Sonnet 5.5"),
            ("opencode", "anthropic/claude-sonnet-5-5"),
        ):
            cfg = _config(target=target)
            assert resolve_model(cfg, "narrator") == sonnet, f"narrator/{target}"
            assert resolve_model(cfg, "pm") == sonnet, f"pm/{target}"

    def test_opencode_resolves_provider_id(self):
        cfg = _config(target="opencode")
        assert resolve_model(cfg, "maestro") == "anthropic/claude-opus-5-5"
        assert resolve_model(cfg, "engineer") == "anthropic/claude-sonnet-5-5"

    def test_override_wins_over_tier(self):
        cfg = _config(target="copilot")
        cfg["models"]["overrides"] = {"engineer": {"copilot": "Claude Haiku 5.5"}}
        assert resolve_model(cfg, "engineer") == "Claude Haiku 5.5"
        # The other implementer still resolves to the tier.
        assert resolve_model(cfg, "devops") == "Claude Sonnet 5.5"

    def test_untiered_agent_falls_back_to_default(self):
        cfg = _config(target="copilot")
        # A role in no named tier resolves to `default`, never empty.
        assert resolve_model(cfg, "some-future-agent") == "Claude Opus 5.5"

    def test_resolution_order_is_overrides_then_tier_then_default(self):
        cfg = _config(target="copilot")
        # Tier beats default: engineer is an implementer (Sonnet), not default (Opus).
        assert resolve_model(cfg, "engineer") == "Claude Sonnet 5.5"
        # Override beats tier.
        cfg["models"]["overrides"] = {"engineer": {"copilot": "Claude Haiku 5.5"}}
        assert resolve_model(cfg, "engineer") == "Claude Haiku 5.5"


# ─── Cost profiles: overrides > profile > tier > default (plan 007 / OQ10) ────


class TestProfileResolution:
    OPUS = "Claude Opus 5.5"
    SONNET = "Claude Sonnet 5.5"

    def test_quality_profile_puts_everyone_on_opus(self):
        # `quality` restores the pre-RFC-0004 default: all agents, incl. the now-cheap
        # narrator/pm, resolve to Opus.
        cfg = _config(target="copilot")
        cfg["profile"] = "quality"
        for role in (
            "maestro",
            "architect",
            "engineer",
            "devops",
            "pm",
            "narrator",
            "learner",
            "security",
        ):
            assert resolve_model(cfg, role) == self.OPUS, role

    def test_budget_profile_moves_learner_to_sonnet(self):
        # `budget` = the cheaper default PLUS learner → Sonnet. narrator/pm are already
        # Sonnet by default; maestro/architect/security stay Opus.
        cfg = _config(target="copilot")
        cfg["profile"] = "budget"
        assert resolve_model(cfg, "learner") == self.SONNET
        assert resolve_model(cfg, "narrator") == self.SONNET
        assert resolve_model(cfg, "pm") == self.SONNET
        assert resolve_model(cfg, "maestro") == self.OPUS
        assert resolve_model(cfg, "security") == self.OPUS

    def test_absent_profile_uses_default_tiers(self):
        cfg = _config(target="copilot")  # no profile key
        assert resolve_model(cfg, "narrator") == self.SONNET  # default: implementer
        assert resolve_model(cfg, "maestro") == self.OPUS  # default: thinker

    def test_precedence_overrides_beats_profile_beats_tier(self):
        cfg = _config(target="copilot")
        # profile beats base tier: quality lifts narrator (default Sonnet) to Opus.
        cfg["profile"] = "quality"
        assert resolve_model(cfg, "narrator") == self.OPUS
        # an explicit override beats the profile.
        cfg["models"]["overrides"] = {"narrator": {"copilot": "Claude Haiku 5.5"}}
        assert resolve_model(cfg, "narrator") == "Claude Haiku 5.5"

    def test_profile_resolves_on_opencode_target_too(self):
        cfg = _config(target="opencode")
        cfg["profile"] = "quality"
        assert resolve_model(cfg, "narrator") == "anthropic/claude-opus-5-5"


# ─── The Carter→target model-name table (MODEL LAUNCH sync marker) ────────────


class TestModelStrings:
    def test_model_string_non_empty_for_every_shipped_role(self):
        # A stale/missing string = a silently dead agent. Every shipped role must
        # resolve to a non-empty per-target model string.
        cfg = _config(target="copilot")
        for role in cfg["agents"]:
            assert resolve_model(cfg, role), f"{role}: empty copilot model string"
        cfg = _config(target="opencode")
        for role in cfg["agents"]:
            assert resolve_model(cfg, role), f"{role}: empty opencode model string"


# ─── Emission: a SINGLE per-target model: string (never an array) ────────────


class TestModelEmission:
    def test_copilot_emits_display_name_string(self):
        keys = policy_native_keys(_config(target="copilot"), "maestro")
        assert keys.get("model") == "Claude Opus 5.5"
        assert isinstance(keys["model"], str), "model must be a single string, not an array"

    def test_opencode_emits_provider_id_string(self):
        keys = policy_native_keys(_config(target="opencode"), "engineer")
        assert keys.get("model") == "anthropic/claude-sonnet-5-5"
        assert isinstance(keys["model"], str)

    def test_every_agent_emits_exactly_one_model_string(self):
        for target in ("copilot", "opencode"):
            cfg = _config(target=target)
            for role in cfg["agents"]:
                model = policy_native_keys(cfg, role).get("model")
                assert isinstance(model, str) and model, f"{role}/{target}: missing model string"

    def test_frontmatter_carries_model(self):
        cfg = _config(target="copilot")
        fm = yaml.safe_load(policy_frontmatter(cfg, "devops"))
        assert fm["model"] == "Claude Sonnet 5.5"

    def test_no_temperature_anywhere(self):
        for target in ("copilot", "opencode"):
            cfg = _config(target=target)
            for role in cfg["agents"]:
                fm = yaml.safe_load(policy_frontmatter(cfg, role))
                assert "temperature" not in fm, f"{role}/{target}: emits temperature (D7)"
                assert "effort" not in fm, f"{role}/{target}: emits an effort key (D2.D1)"


# ─── carter check required unverifiable-model advisory ───────────────────────


class TestModelAdvisory:
    def test_advisory_is_always_present(self):
        from carter.scaffold import model_advisory

        cfg = _config(target="copilot")
        advisory = model_advisory(cfg)
        assert advisory, "the unverifiable-model advisory is required, not optional"
        # Names an agent and its pinned model + the can't-verify-subscription caveat.
        assert "maestro" in advisory
        assert "Claude Opus 5.5" in advisory
        assert "subscription" in advisory.lower()

    def test_check_prints_advisory(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        assert runner.invoke(main, ["init", str(tmp_path), "--no-git-state"]).exit_code == 0
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "cannot verify" in result.output.lower()
        assert "subscription" in result.output.lower()
