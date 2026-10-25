"""Tests for per-agent model emission.

Carter pins one ``model:`` string per agent in OpenCode V2 syntax
(``provider/model[#variant]``), resolved from the ``models:`` block by
``overrides > profile > tier > default``. Thinkers (maestro, architect, learner,
security) = Opus 5.5; implementers (engineer, devops, pm, narrator) = Sonnet 5.5.
``carter check`` prints a required unverifiable-model advisory. No effort key; no
``temperature``.
"""

from __future__ import annotations

import pytest
import yaml

from carter.config import (
    DEFAULT_CONFIG,
    ConfigError,
    generate_default_config,
    load_config,
    policy_frontmatter,
    policy_native_keys,
    resolve_model,
)

THINKERS = ("maestro", "architect", "learner", "security")
IMPLEMENTERS = ("engineer", "devops", "pm", "narrator")
OPUS = "anthropic/claude-opus-5-5"
SONNET = "anthropic/claude-sonnet-5-5"
HAIKU = "anthropic/claude-haiku-5-5"


def _config() -> dict:
    cfg = generate_default_config(workspace_name="models", mode="single")
    cfg["agent_suffix"] = ""
    return cfg


def _minimal(**extra) -> dict:
    return {"version": "2", "workspace": {}, "identity": {}, "agents": ["maestro"], **extra}


# ─── The models: block shape ─────────────────────────────────────────────────


class TestModelsBlock:
    def test_tiers_are_single_strings(self):
        models = DEFAULT_CONFIG["models"]
        assert models["default"] == OPUS
        assert models["thinkers"] == OPUS
        assert models["implementers"] == SONNET

    def test_overrides_default_empty(self):
        assert DEFAULT_CONFIG["models"]["overrides"] == {}

    def test_models_block_survives_deep_merge(self):
        from carter.config import _merge_with_defaults

        assert _merge_with_defaults(_minimal())["models"]["thinkers"] == OPUS


# ─── Validation of the V2 model string ───────────────────────────────────────


class TestModelValidation:
    @pytest.mark.parametrize(
        "model",
        [
            "anthropic/claude-opus-5-5",
            "anthropic/claude-sonnet-5-5#high",
            "openai/gpt-5.5",
            "openrouter/meta/llama-4#fast",
        ],
    )
    def test_valid_model_strings_load(self, tmp_path, model):
        path = tmp_path / "carter.yaml"
        path.write_text(yaml.dump(_minimal(models={"thinkers": model})))
        assert load_config(path)["models"]["thinkers"] == model

    @pytest.mark.parametrize(
        "model",
        [
            "Claude Opus 5.5",
            "claude-opus-5-5",
            "anthropic/",
            "/claude",
            "anthropic/claude#",
            "anthropic/claude#a#b",
            "",
            42,
        ],
    )
    def test_invalid_model_strings_rejected(self, tmp_path, model):
        path = tmp_path / "carter.yaml"
        path.write_text(yaml.dump(_minimal(models={"thinkers": model})))
        with pytest.raises(ConfigError, match=r"provider/model\[#variant\]"):
            load_config(path)

    def test_invalid_override_rejected(self, tmp_path):
        path = tmp_path / "carter.yaml"
        path.write_text(yaml.dump(_minimal(models={"overrides": {"engineer": "Claude Haiku"}})))
        with pytest.raises(ConfigError, match="models.overrides.engineer"):
            load_config(path)


# ─── Resolution: overrides > profile > tier > default ────────────────────────


class TestResolveModel:
    def test_thinkers_resolve_to_opus(self):
        for role in THINKERS:
            assert resolve_model(_config(), role) == OPUS, role

    def test_implementers_resolve_to_sonnet(self):
        for role in IMPLEMENTERS:
            assert resolve_model(_config(), role) == SONNET, role

    def test_override_wins_over_tier(self):
        cfg = _config()
        cfg["models"]["overrides"] = {"engineer": HAIKU}
        assert resolve_model(cfg, "engineer") == HAIKU
        assert resolve_model(cfg, "devops") == SONNET

    def test_untiered_agent_falls_back_to_default(self):
        assert resolve_model(_config(), "some-future-agent") == OPUS


class TestProfileResolution:
    def test_quality_profile_puts_everyone_on_opus(self):
        cfg = _config()
        cfg["profile"] = "quality"
        for role in (*THINKERS, *IMPLEMENTERS):
            assert resolve_model(cfg, role) == OPUS, role

    def test_budget_profile_moves_learner_to_sonnet(self):
        cfg = _config()
        cfg["profile"] = "budget"
        assert resolve_model(cfg, "learner") == SONNET
        assert resolve_model(cfg, "narrator") == SONNET
        assert resolve_model(cfg, "maestro") == OPUS

    def test_precedence_overrides_beats_profile(self):
        cfg = _config()
        cfg["profile"] = "quality"
        assert resolve_model(cfg, "narrator") == OPUS
        cfg["models"]["overrides"] = {"narrator": HAIKU}
        assert resolve_model(cfg, "narrator") == HAIKU


# ─── Emission ────────────────────────────────────────────────────────────────


class TestModelEmission:
    def test_every_agent_emits_one_model_string(self):
        cfg = _config()
        for role in cfg["agents"]:
            model = policy_native_keys(cfg, role).get("model")
            assert isinstance(model, str) and "/" in model, role

    def test_variant_passes_through(self):
        cfg = _config()
        cfg["models"]["overrides"] = {"devops": "anthropic/claude-sonnet-5-5#high"}
        fm = yaml.safe_load(policy_frontmatter(cfg, "devops"))
        assert fm["model"] == "anthropic/claude-sonnet-5-5#high"

    def test_no_temperature_or_effort(self):
        cfg = _config()
        for role in cfg["agents"]:
            fm = yaml.safe_load(policy_frontmatter(cfg, role))
            assert "temperature" not in fm and "effort" not in fm, role


# ─── carter check required unverifiable-model advisory ───────────────────────


class TestModelAdvisory:
    def test_advisory_is_always_present(self):
        from carter.scaffold import model_advisory

        advisory = model_advisory(_config())
        assert "maestro" in advisory
        assert OPUS in advisory
        assert "subscription" in advisory.lower()

    def test_check_prints_advisory(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        assert runner.invoke(main, ["init", str(tmp_path), "--no-git-state"]).exit_code == 0
        result = runner.invoke(main, ["check", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "cannot verify" in result.output.lower()
