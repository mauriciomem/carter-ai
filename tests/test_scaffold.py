"""Tests for Carter scaffold — template rendering and workspace initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from carter.config import (
    AGENT_MCP_SCOPE,
    RISK_TAXONOMY,
    ConfigError,
    effective_allowlist,
    generate_default_config,
    load_config,
    policy_frontmatter,
    write_config,
)
from carter.scaffold import create_env, render_agents, render_instructions, write_rendered_files
from carter.state import KNOWLEDGE_FILES, add_to_gitignore, init_workspace

# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def default_config() -> dict:
    """A complete default configuration for content/structure tests.

    ``agent_suffix`` is pinned to "" so rendered files use canonical
    ``carter-<role>.md`` names these tests reference directly. The suffix
    feature (real default "local") is covered by ``TestAgentSuffix``.
    """
    config = generate_default_config(workspace_name="test-workspace", mode="umbrella")
    config["agent_suffix"] = ""
    return config


@pytest.fixture
def templates_dir() -> Path:
    """Path to the templates directory in the repo."""
    return Path(__file__).resolve().parent.parent / "templates"


@pytest.fixture
def env(templates_dir):
    """Jinja2 environment pointed at real templates."""
    return create_env(templates_dir)


# ─── Config Tests ────────────────────────────────────────────────────────────


class TestConfig:
    def test_generate_default_has_required_keys(self, default_config):
        """Default config contains all required keys."""
        assert "version" in default_config
        assert "workspace" in default_config
        assert "identity" in default_config
        assert "agents" in default_config

    def test_generate_default_mode(self):
        """Mode parameter is respected."""
        config = generate_default_config(mode="single")
        assert config["workspace"]["mode"] == "single"

    def test_write_and_load_roundtrip(self, tmp_path, default_config):
        """Config can be written and loaded back identically."""
        config_path = tmp_path / "carter.yaml"
        write_config(config_path, default_config)
        loaded = load_config(config_path)
        assert loaded == default_config

    def test_load_missing_file_raises(self, tmp_path):
        """Loading a non-existent config raises ConfigError."""
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "missing.yaml")

    def test_load_invalid_format_raises(self, tmp_path):
        """Loading a non-dict YAML raises ConfigError."""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("just a string\n")
        with pytest.raises(ConfigError, match="Invalid config"):
            load_config(config_path)

    def test_load_missing_keys_raises(self, tmp_path):
        """Loading config without required keys raises ConfigError."""
        config_path = tmp_path / "partial.yaml"
        config_path.write_text(yaml.dump({"version": "2"}))
        with pytest.raises(ConfigError, match="Missing required"):
            load_config(config_path)


# ─── Bug Fix Tests ───────────────────────────────────────────────────────────


class TestConfigIsolation:
    """Bug #1: generate_default_config must return fully independent copies."""

    def test_mutating_agents_list_does_not_corrupt_defaults(self):
        """Appending to agents list doesn't affect subsequent calls."""
        from carter.config import DEFAULT_CONFIG

        original_agents = list(DEFAULT_CONFIG["agents"])
        config = generate_default_config()
        config["agents"].append("debugger")

        # DEFAULT_CONFIG must be unchanged
        assert DEFAULT_CONFIG["agents"] == original_agents

    def test_mutating_nested_dict_does_not_corrupt_defaults(self):
        """Mutating quality_gate dict doesn't affect subsequent calls."""
        from carter.config import DEFAULT_CONFIG

        config = generate_default_config()
        config["quality_gate"]["max_iterations"] = 99

        assert DEFAULT_CONFIG["quality_gate"]["max_iterations"] == 2

    def test_mutating_redaction_categories_does_not_corrupt_defaults(self):
        """Mutating categories list doesn't affect subsequent calls."""
        from carter.config import DEFAULT_CONFIG

        config = generate_default_config()
        config["redaction"]["categories"] = ["secrets"]

        assert len(DEFAULT_CONFIG["redaction"]["categories"]) == 7

    def test_two_generated_configs_are_independent(self):
        """Two generated configs don't share any mutable state."""
        c1 = generate_default_config()
        c2 = generate_default_config()

        c1["agents"].append("debugger")
        c1["personality"]["skepticism"] = "always"
        c1["tdd"]["strict"] = True

        assert "debugger" not in c2["agents"]
        assert c2["personality"]["skepticism"] == "scaled"
        assert c2["tdd"]["strict"] is False


class TestConfigMerge:
    """Bug #2: load_config must merge with defaults for missing optional keys."""

    def test_partial_config_gets_defaults_for_missing_sections(self, tmp_path):
        """Config missing optional sections gets defaults filled in."""
        config_path = tmp_path / "carter.yaml"
        minimal = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user"},
            "agents": ["maestro"],
        }
        config_path.write_text(yaml.dump(minimal))
        loaded = load_config(config_path)

        # Optional sections should be present from defaults
        assert "personality" in loaded
        assert "quality_gate" in loaded
        assert "tdd" in loaded
        assert "redaction" in loaded
        assert "state" in loaded

    def test_partial_nested_dict_gets_missing_keys(self, tmp_path):
        """Partial quality_gate gets missing keys from defaults."""
        config_path = tmp_path / "carter.yaml"
        config = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user"},
            "agents": ["maestro"],
            "quality_gate": {"enabled": False},
        }
        config_path.write_text(yaml.dump(config))
        loaded = load_config(config_path)

        # User's value preserved
        assert loaded["quality_gate"]["enabled"] is False
        # Defaults filled in for missing keys
        assert loaded["quality_gate"]["max_iterations"] == 2
        assert loaded["quality_gate"]["trigger"] == "user-initiated"

    def test_user_list_values_not_merged_with_defaults(self, tmp_path):
        """User's agents list replaces default, not merges with it."""
        config_path = tmp_path / "carter.yaml"
        config = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user"},
            "agents": ["maestro", "engineer"],
        }
        config_path.write_text(yaml.dump(config))
        loaded = load_config(config_path)

        assert loaded["agents"] == ["maestro", "engineer"]

    def test_user_explicit_none_preserved(self, tmp_path):
        """Explicit null/None values are preserved, not filled from defaults."""
        config_path = tmp_path / "carter.yaml"
        config = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user", "git_org": None},
            "agents": ["maestro"],
        }
        config_path.write_text(yaml.dump(config))
        loaded = load_config(config_path)

        assert loaded["identity"]["git_org"] is None

    def test_extra_user_keys_preserved(self, tmp_path):
        """Keys not in defaults are preserved (forward-compatible)."""
        config_path = tmp_path / "carter.yaml"
        config = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user"},
            "agents": ["maestro"],
            "custom_extension": {"foo": "bar"},
        }
        config_path.write_text(yaml.dump(config))
        loaded = load_config(config_path)

        assert loaded["custom_extension"] == {"foo": "bar"}

    def test_full_config_roundtrip_unchanged(self, tmp_path):
        """A full config with all keys loads without modification."""
        config_path = tmp_path / "carter.yaml"
        full = generate_default_config()
        write_config(config_path, full)
        loaded = load_config(config_path)

        assert loaded == full

    def test_merged_config_renders_templates_successfully(self, tmp_path, env):
        """A partial config, after merge, renders all templates without error."""
        config_path = tmp_path / "carter.yaml"
        config = {
            "version": "2",
            "workspace": {"name": "test", "mode": "umbrella"},
            "identity": {"git_account": "user"},
            "agents": ["maestro"],
        }
        config_path.write_text(yaml.dump(config))
        loaded = load_config(config_path)

        # Should not raise UndefinedError. Merge supplies the default
        # agent_suffix ("local"), so the rendered file is suffixed.
        results = render_agents(loaded, env)
        assert "carter-maestro-local.md" in results


class TestAgentValidation:
    """Bug #3: render_agents must validate agent names before rendering."""

    def test_unknown_agent_raises_config_error(self, default_config, env):
        """Typo in agent name raises ConfigError, not TemplateNotFound."""
        default_config["agents"] = ["maetsro"]
        with pytest.raises(ConfigError):
            render_agents(default_config, env)

    def test_error_message_lists_valid_agents(self, default_config, env):
        """Error message for unknown agent includes available options."""
        default_config["agents"] = ["nonexistent"]
        with pytest.raises(ConfigError, match="maestro"):
            render_agents(default_config, env)

    def test_path_traversal_rejected(self, default_config, env):
        """Path traversal attempt in agent name is rejected."""
        default_config["agents"] = ["../../etc/passwd"]
        with pytest.raises(ConfigError):
            render_agents(default_config, env)

    def test_empty_string_rejected(self, default_config, env):
        """Empty agent name is rejected."""
        default_config["agents"] = [""]
        with pytest.raises(ConfigError):
            render_agents(default_config, env)

    def test_special_characters_rejected(self, default_config, env):
        """Agent names with spaces or special chars are rejected."""
        default_config["agents"] = ["foo bar"]
        with pytest.raises(ConfigError):
            render_agents(default_config, env)

    def test_valid_agents_pass_validation(self, default_config, env):
        """All standard agents pass validation without error."""
        default_config["agents"] = [
            "maestro",
            "architect",
            "engineer",
            "devops",
            "pm",
            "learner",
            "narrator",
        ]
        # Should not raise
        results = render_agents(default_config, env)
        assert len(results) == 7


# ─── Scaffold Tests ──────────────────────────────────────────────────────────


class TestScaffold:
    def test_render_agents_produces_all_configured(self, default_config, env):
        """Every agent in config produces a rendered file."""
        results = render_agents(default_config, env)
        for agent_name in default_config["agents"]:
            assert f"carter-{agent_name}.md" in results

    def test_rendered_agent_has_identity_block(self, default_config, env):
        """Every rendered agent contains an <identity> block."""
        results = render_agents(default_config, env)
        for filename, content in results.items():
            assert "<identity>" in content, f"{filename} missing <identity>"

    def test_rendered_agent_has_role_block(self, default_config, env):
        """Every rendered agent contains a <role> block."""
        results = render_agents(default_config, env)
        for filename, content in results.items():
            assert "<role>" in content, f"{filename} missing <role>"

    def test_rendered_agent_has_boundaries_block(self, default_config, env):
        """Every rendered agent contains a <boundaries> block."""
        results = render_agents(default_config, env)
        for filename, content in results.items():
            assert "<boundaries>" in content, f"{filename} missing <boundaries>"

    def test_rendered_agent_has_generated_header(self, default_config, env):
        """Every rendered agent starts with the generated header."""
        results = render_agents(default_config, env)
        for filename, content in results.items():
            assert "Generated by Carter v2" in content, f"{filename} missing header"

    def test_render_instructions(self, default_config, env):
        """Instructions template renders with workspace name."""
        results = render_instructions(default_config, env)
        assert "copilot-instructions.md" in results
        content = results["copilot-instructions.md"]
        assert "test-workspace" in content

    def test_write_rendered_files(self, tmp_path, default_config, env):
        """Rendered files are written to disk."""
        agents = render_agents(default_config, env)
        written = write_rendered_files(agents, tmp_path / "agents")
        assert len(written) == len(default_config["agents"])
        for path in written:
            assert path.exists()
            assert path.stat().st_size > 0

    def test_quality_gate_renders_when_enabled(self, default_config, env):
        """Maestro includes quality gate when enabled."""
        default_config["quality_gate"]["enabled"] = True
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "<quality_gate>" in maestro

    def test_quality_gate_absent_when_disabled(self, default_config, env):
        """Maestro excludes quality gate when disabled."""
        default_config["quality_gate"]["enabled"] = False
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "<quality_gate>" not in maestro

    def test_skepticism_scaled_renders_interaction_rules(self, default_config, env):
        """Scaled skepticism produces interaction_rules block."""
        default_config["personality"]["skepticism"] = "scaled"
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "<interaction_rules>" in maestro

    def test_skepticism_off_keeps_policy_drops_calibration(self, default_config, env):
        """Off skepticism keeps the always-on policy gate table (in
        interaction_rules) but drops only the Skepticism Calibration sub-section
        (RFC-0002 P2 step 5 — the policy gate is independent of skepticism)."""
        default_config["personality"]["skepticism"] = "off"
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "<interaction_rules>" in maestro
        assert "Strictness Policy" in maestro
        assert "Skepticism Calibration" not in maestro


# ─── Quality Gate Tests ──────────────────────────────────────────────────────


class TestQualityGate:
    def test_must_haves_renders_with_spec_handoff(self, default_config, env):
        """must_haves integration renders when spec_handoff is true."""
        default_config["quality_gate"]["enabled"] = True
        default_config["tdd"]["spec_handoff"] = True
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "must_haves" in maestro

    def test_must_haves_absent_without_spec_handoff(self, default_config, env):
        """must_haves not mentioned when spec_handoff is false."""
        default_config["quality_gate"]["enabled"] = True
        default_config["tdd"]["spec_handoff"] = False
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "must_haves" not in maestro

    def test_iteration_count_in_quality_gate(self, default_config, env):
        """Iteration count from config appears in rendered quality gate."""
        default_config["quality_gate"]["enabled"] = True
        default_config["quality_gate"]["max_iterations"] = 3
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        # max_iterations - 1 = 2 remaining shown in text
        assert "2 iterations remaining" in maestro
        assert "3 rounds max" in maestro

    def test_review_output_format_present(self, default_config, env):
        """Quality gate includes structured review output format."""
        default_config["quality_gate"]["enabled"] = True
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "Review Output Format" in maestro
        assert "Verdict" in maestro

    def test_engineer_review_checklist(self, default_config, env):
        """Engineer gets security-aware review checklist when gate enabled."""
        default_config["quality_gate"]["enabled"] = True
        results = render_agents(default_config, env)
        engineer = results["carter-engineer.md"]
        assert "security issues" in engineer
        assert "dead code" in engineer

    def test_engineer_review_absent_when_disabled(self, default_config, env):
        """Engineer review checklist absent when gate disabled."""
        default_config["quality_gate"]["enabled"] = False
        results = render_agents(default_config, env)
        engineer = results["carter-engineer.md"]
        assert "quality gate mode" not in engineer

    def test_architect_review_checklist(self, default_config, env):
        """Architect gets design-focused review checklist when gate enabled."""
        default_config["quality_gate"]["enabled"] = True
        results = render_agents(default_config, env)
        architect = results["carter-architect.md"]
        assert "abstraction leaks" in architect
        assert "coupling violations" in architect

    def test_reviewers_validate_must_haves(self, default_config, env):
        """Both reviewers mention must_haves when spec_handoff enabled."""
        default_config["quality_gate"]["enabled"] = True
        default_config["tdd"]["spec_handoff"] = True
        results = render_agents(default_config, env)
        engineer = results["carter-engineer.md"]
        architect = results["carter-architect.md"]
        assert "must_haves" in engineer
        assert "must_haves" in architect

    def test_maestro_checkpoint_protocol(self, default_config, env):
        """Maestro carries the checkpoint write protocol referencing `carter save`.

        Anti-drift: the prompt instructs the agent to run `carter save`, which
        must exist as a real CLI command (it does — see carter.cli.save).
        """
        maestro = render_agents(default_config, env)["carter-maestro.md"]
        assert "Saving a Checkpoint" in maestro
        assert "carter save" in maestro
        assert "suggest-and-confirm" in maestro
        # the checkpoint is a thin cursor, not a content duplicate
        assert "source of truth" in maestro


# ─── State Tests ─────────────────────────────────────────────────────────────


class TestState:
    def test_init_workspace_creates_structure(self, tmp_path, default_config):
        """init_workspace creates the full .carter/ tree."""
        carter_dir = init_workspace(tmp_path, default_config, git_state=False)
        assert carter_dir.exists()
        assert (carter_dir / "carter.yaml").exists()
        assert (carter_dir / "state" / "plans" / "active").is_dir()
        assert (carter_dir / "state" / "plans" / "completed").is_dir()
        assert (carter_dir / "state" / "sessions").is_dir()
        assert (carter_dir / "knowledge").is_dir()

    def test_init_workspace_creates_knowledge_files(self, tmp_path, default_config):
        """All knowledge files are created with content."""
        init_workspace(tmp_path, default_config, git_state=False)
        knowledge_dir = tmp_path / ".carter" / "knowledge"
        for filename in KNOWLEDGE_FILES:
            path = knowledge_dir / filename
            assert path.exists(), f"Missing: {filename}"
            assert path.stat().st_size > 0

    def test_init_workspace_does_not_overwrite_config(self, tmp_path, default_config):
        """Calling init twice doesn't overwrite existing config."""
        init_workspace(tmp_path, default_config, git_state=False)
        config_path = tmp_path / ".carter" / "carter.yaml"
        original_content = config_path.read_text()

        # Modify and re-init
        modified_config = dict(default_config)
        modified_config["workspace"]["name"] = "changed"
        init_workspace(tmp_path, modified_config, git_state=False)

        assert config_path.read_text() == original_content

    def test_init_workspace_does_not_overwrite_knowledge(self, tmp_path, default_config):
        """Re-init doesn't overwrite existing knowledge files."""
        init_workspace(tmp_path, default_config, git_state=False)
        gotchas = tmp_path / ".carter" / "knowledge" / "gotchas.md"
        gotchas.write_text("# Custom content\n")

        init_workspace(tmp_path, default_config, git_state=False)
        assert gotchas.read_text() == "# Custom content\n"

    def test_init_workspace_with_git(self, tmp_path, default_config):
        """Git state creates .git directory inside .carter/."""
        carter_dir = init_workspace(tmp_path, default_config, git_state=True)
        assert (carter_dir / ".git").is_dir()

    def test_add_to_gitignore_creates_file(self, tmp_path):
        """Creates .gitignore if it doesn't exist."""
        add_to_gitignore(tmp_path, ".carter/")
        gitignore = tmp_path / ".gitignore"
        assert gitignore.exists()
        assert ".carter/" in gitignore.read_text()

    def test_add_to_gitignore_appends(self, tmp_path):
        """Appends to existing .gitignore."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text("node_modules/\n")
        add_to_gitignore(tmp_path, ".carter/")
        content = gitignore.read_text()
        assert "node_modules/" in content
        assert ".carter/" in content

    def test_add_to_gitignore_no_duplicate(self, tmp_path):
        """Doesn't duplicate entry if already present."""
        gitignore = tmp_path / ".gitignore"
        gitignore.write_text(".carter/\n")
        add_to_gitignore(tmp_path, ".carter/")
        assert gitignore.read_text().count(".carter/") == 1


# ─── Narrator / Redaction Tests ──────────────────────────────────────────────


class TestNarrator:
    """Tests for carter-narrator template and redaction system."""

    def test_narrator_renders(self, default_config, env):
        """Narrator template renders without error when in agents list."""
        results = render_agents(default_config, env)
        assert "carter-narrator.md" in results

    def test_narrator_has_identity(self, default_config, env):
        """Narrator has identity block."""
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<identity>" in content
        assert "Carter Narrator" in content

    def test_narrator_has_role(self, default_config, env):
        """Narrator has role block with content production focus."""
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<role>" in content
        assert "external-facing content" in content

    def test_narrator_has_boundaries(self, default_config, env):
        """Narrator has boundaries block."""
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<boundaries>" in content

    def test_redaction_rules_present_when_enabled(self, default_config, env):
        """Redaction rules render when redaction is enabled."""
        default_config["redaction"]["enabled"] = True
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<redaction_rules>" in content

    def test_redaction_rules_absent_when_disabled_and_loose(self, default_config, env):
        """At `loose`, redaction rules are absent when redaction is disabled."""
        default_config["redaction"]["enabled"] = False
        default_config["policy"]["level"] = "loose"
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<redaction_rules>" not in content

    def test_redaction_forced_at_guarded_despite_disabled(self, default_config, env):
        """must_have #5: `guarded` forces a redaction pass even with redaction off."""
        default_config["redaction"]["enabled"] = False
        default_config["policy"]["level"] = "guarded"
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<redaction_rules>" in content

    def test_redaction_forced_at_strict_despite_disabled(self, default_config, env):
        """must_have #5: `strict` forces a redaction pass even with redaction off."""
        default_config["redaction"]["enabled"] = False
        default_config["policy"]["level"] = "strict"
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "<redaction_rules>" in content

    def test_all_categories_render(self, default_config, env):
        """All configured redaction categories appear in output."""
        default_config["redaction"]["enabled"] = True
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "Secrets" in content
        assert "Internal URLs" in content
        assert "Security Incidents" in content
        assert "PII" in content
        assert "Financial Figures" in content
        assert "Employee Data" in content
        assert "Infrastructure IDs" in content

    def test_subset_categories_render(self, default_config, env):
        """Only configured categories render (subset selection)."""
        default_config["redaction"]["enabled"] = True
        default_config["redaction"]["categories"] = ["secrets", "pii"]
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "Secrets" in content
        assert "PII" in content
        assert "Financial Figures" not in content
        assert "Infrastructure IDs" not in content

    def test_anti_bypass_clause_present(self, default_config, env):
        """Anti-bypass clause is always present when redaction is enabled."""
        default_config["redaction"]["enabled"] = True
        results = render_agents(default_config, env)
        content = results["carter-narrator.md"]
        assert "Anti-Bypass Clause" in content
        assert "Roleplay" in content
        assert "Hypothetical" in content
        assert "Mode override" in content

    def test_narrator_absent_when_not_in_agents(self, default_config, env):
        """Narrator is not rendered when removed from agents list."""
        config = dict(default_config)
        config["agents"] = [a for a in default_config["agents"] if a != "narrator"]
        results = render_agents(config, env)
        assert "carter-narrator.md" not in results

    def test_maestro_routes_to_narrator(self, default_config, env):
        """Maestro routing table includes narrator when configured."""
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        assert "carter-narrator" in maestro


# ─── Discovery paths (carter init/update output locations) ───────────────────


class TestRenderDiscovery:
    """`carter init`/`update` must write agents and instructions to the paths the
    tools actually discover (ADR-0002): copilot → .github/, opencode → .opencode/
    + AGENTS.md. Carter-owned agents are (re)written; instruction files are
    skip-if-exists.
    """

    def _agent_names(self, config: dict) -> list[str]:
        return [f"carter-{a}.md" for a in config["agents"]]

    def test_copilot_target_writes_github_paths(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        default_config["target"] = "copilot"
        _render_and_write(tmp_path, default_config, env)

        agents_dir = tmp_path / ".github" / "agents"
        for name in self._agent_names(default_config):
            assert (agents_dir / name).exists()
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()
        # Nothing written to the legacy non-discoverable path
        assert not (tmp_path / "agents").exists()

    def test_opencode_target_writes_opencode_paths(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        default_config["target"] = "opencode"
        _render_and_write(tmp_path, default_config, env)

        agents_dir = tmp_path / ".opencode" / "agents"
        for name in self._agent_names(default_config):
            assert (agents_dir / name).exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".github").exists()

    def test_all_target_writes_both(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        default_config["target"] = "all"
        _render_and_write(tmp_path, default_config, env)

        assert (tmp_path / ".github" / "agents" / "carter-maestro.md").exists()
        assert (tmp_path / ".github" / "copilot-instructions.md").exists()
        assert (tmp_path / ".opencode" / "agents" / "carter-maestro.md").exists()
        assert (tmp_path / "AGENTS.md").exists()

    def test_instructions_skip_if_exists(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        default_config["target"] = "copilot"
        instr = tmp_path / ".github" / "copilot-instructions.md"
        instr.parent.mkdir(parents=True)
        instr.write_text("USER CONTENT")

        _render_and_write(tmp_path, default_config, env)

        # User instruction file preserved, agents still written
        assert instr.read_text() == "USER CONTENT"
        assert (tmp_path / ".github" / "agents" / "carter-maestro.md").exists()

    def test_agents_rewritten_on_update(self, tmp_path, default_config, env):
        """Carter-owned agents are overwritten so `carter update` refreshes them."""
        from carter.cli import _render_and_write

        default_config["target"] = "copilot"
        agent = tmp_path / ".github" / "agents" / "carter-maestro.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("STALE")

        _render_and_write(tmp_path, default_config, env)

        assert agent.read_text() != "STALE"
        assert "Carter Maestro" in agent.read_text()

    def test_resolve_targets(self):
        from carter.cli import _resolve_targets

        assert _resolve_targets("copilot") == ["copilot"]
        assert _resolve_targets("opencode") == ["opencode"]
        assert _resolve_targets("all") == ["copilot", "opencode"]


# ─── Agent name suffix (workspace vs global distinction) ─────────────────────


class TestAgentSuffix:
    """`agent_suffix` distinguishes workspace-scaffolded agents from globally
    installed ones (e.g. `carter-engineer-local`). Default is "local"; empty
    means "same names as global". Applies to filenames AND every `carter-<role>`
    reference (routing, footer, cross-refs, instructions) — never to skill names.
    """

    SKILLS = (
        "carter-ops",
        "carter-docs",
        "carter-story",
        "carter-pipeline",
        "carter-plan",
        "carter-python",
        "carter-adr",
        "carter-design-review",
    )

    def test_default_suffix_is_local(self):
        assert generate_default_config()["agent_suffix"] == "local"

    def test_default_renders_local_suffixed_filenames(self, env):
        cfg = generate_default_config()
        rendered = render_agents(cfg, env)
        assert "carter-maestro-local.md" in rendered
        assert all(name.endswith("-local.md") for name in rendered)

    def test_empty_suffix_renders_plain_names(self, env):
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        rendered = render_agents(cfg, env)
        assert "carter-maestro.md" in rendered
        assert not any("-local" in name for name in rendered)

    def test_custom_suffix(self, env):
        cfg = generate_default_config()
        cfg["agent_suffix"] = "demo"
        rendered = render_agents(cfg, env)
        assert "carter-engineer-demo.md" in rendered
        assert "carter-engineer-demo" in rendered["carter-maestro-demo.md"]

    def test_suffix_applied_to_routing_footer_and_crossrefs(self, env):
        cfg = generate_default_config()  # default "local"
        rendered = render_agents(cfg, env)
        maestro = rendered["carter-maestro-local.md"]
        # Routing table + Available Agents footer use suffixed names
        assert "carter-engineer-local" in maestro
        assert "carter-narrator-local" in maestro
        # Cross-reference inside a subagent is suffixed too
        engineer = rendered["carter-engineer-local.md"]
        assert "carter-architect-local" in engineer
        # No bare role reference leaks through
        import re

        assert not re.search(r"carter-engineer(?!-local)", maestro)

    def test_skill_names_never_suffixed(self, env):
        cfg = generate_default_config()
        rendered = render_agents(cfg, env)
        rendered.update(render_instructions(cfg, env))
        for content in rendered.values():
            for skill in self.SKILLS:
                assert f"{skill}-local" not in content, f"{skill} was wrongly suffixed"

    def test_instructions_references_suffixed(self, env):
        cfg = generate_default_config()
        instr = render_instructions(cfg, env)["copilot-instructions.md"]
        assert "carter-maestro-local" in instr

    def test_default_suffix_end_to_end(self, tmp_path, env):
        """A real default `carter init` lands suffixed files in the discovery path."""
        from carter.cli import _render_and_write

        cfg = generate_default_config()  # target copilot, suffix local
        _render_and_write(tmp_path, cfg, env)
        assert (tmp_path / ".github" / "agents" / "carter-maestro-local.md").exists()
        assert (tmp_path / ".github" / "agents" / "carter-engineer-local.md").exists()

    def test_invalid_suffix_rejected(self, tmp_path):
        cfg = generate_default_config()
        cfg["agent_suffix"] = "Bad Suffix!"
        config_path = tmp_path / "carter.yaml"
        write_config(config_path, cfg)
        with pytest.raises(ConfigError, match="agent_suffix"):
            load_config(config_path)

    def test_agent_filename_helper(self):
        """`agent_filename` (used by `carter check`) honors the suffix."""
        from carter.scaffold import agent_filename

        cfg = generate_default_config()
        assert agent_filename("maestro", cfg) == "carter-maestro-local.md"
        cfg["agent_suffix"] = ""
        assert agent_filename("maestro", cfg) == "carter-maestro.md"
        cfg["agent_suffix"] = "demo"
        assert agent_filename("engineer", cfg) == "carter-engineer-demo.md"


# ─── Config warnings (narrator/redaction edge case) ──────────────────────────


class TestConfigWarnings:
    """`config_warnings` flags the redaction gap: narrator enabled but redaction
    disabled means the scaffolded narrator has no redaction rules even though
    Maestro routes external content to it.
    """

    def test_warns_when_narrator_on_redaction_off(self):
        from carter.scaffold import config_warnings

        cfg = generate_default_config()
        cfg["redaction"]["enabled"] = False
        cfg["policy"]["level"] = "loose"  # only loose leaves the narrator ruleless
        warnings = config_warnings(cfg)
        assert len(warnings) == 1
        assert "redaction" in warnings[0].lower()
        assert "narrator" in warnings[0].lower()

    def test_no_config_warning_at_guarded_redaction_off(self):
        # At guarded the redaction pass is forced, so the narrator DOES carry
        # rules — config_warnings stays quiet (the lint surfaces the contradiction).
        from carter.scaffold import config_warnings

        cfg = generate_default_config()  # guarded
        cfg["redaction"]["enabled"] = False
        assert config_warnings(cfg) == []

    def test_no_warning_when_both_on(self):
        from carter.scaffold import config_warnings

        cfg = generate_default_config()  # narrator in agents, redaction on
        assert config_warnings(cfg) == []

    def test_no_warning_when_narrator_absent(self):
        from carter.scaffold import config_warnings

        cfg = generate_default_config()
        cfg["agents"] = [a for a in cfg["agents"] if a != "narrator"]
        cfg["redaction"]["enabled"] = False
        assert config_warnings(cfg) == []


# ─── Policy gate table + migration notice + R6 handoff (P2 step 5) ────────────


class TestPolicyGateTable:
    """`policy_gate_table` drives the always-on maestro risk/gate table."""

    def test_guarded_table_has_all_seven_categories(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded"}})
        assert [r["category"] for r in rows] == ["R0", "R1", "R2", "R3", "R4", "R5", "R6"]
        assert all(r["label"] for r in rows)

    def test_guarded_gates_match_taxonomy(self):
        from carter.config import policy_gate_table

        gates = {
            r["category"]: r["gate"] for r in policy_gate_table({"policy": {"level": "guarded"}})
        }
        assert gates == {
            "R0": "allow",
            "R1": "allow",
            "R2": "ask",
            "R3": "gate",
            "R4": "ask",
            "R5": "gate",
            "R6": "gate",
        }

    def test_loose_table_is_all_allow(self):
        from carter.config import policy_gate_table

        gates = {r["gate"] for r in policy_gate_table({"policy": {"level": "loose"}})}
        assert gates == {"allow"}

    def test_strict_table_emits_deny(self):
        """P2->P3 gate is open (step 9): strict now emits deny for R3/R5."""
        from carter.config import policy_gate_table

        gates = {
            r["category"]: r["gate"] for r in policy_gate_table({"policy": {"level": "strict"}})
        }
        assert gates["R3"] == "deny"
        assert gates["R5"] == "deny"
        assert gates["R2"] == "gate"

    def test_missing_policy_defaults_loose(self):
        from carter.config import policy_gate_table

        gates = {r["gate"] for r in policy_gate_table({})}
        assert gates == {"allow"}


class TestMaestroPolicyTable:
    """The maestro renders the policy gate table regardless of skepticism."""

    def _render_maestro(self, skepticism: str) -> str:
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        cfg["personality"]["skepticism"] = skepticism
        return render_agents(cfg, create_env())["carter-maestro.md"]

    def test_table_renders_when_skepticism_off(self):
        body = self._render_maestro("off")
        assert "Strictness Policy" in body
        assert "remote-write" in body  # a taxonomy row is present

    def test_table_renders_when_skepticism_scaled(self):
        body = self._render_maestro("scaled")
        assert "Strictness Policy" in body
        # skepticism calibration remains, as a tone sub-section
        assert "Skepticism Calibration" in body

    def test_skepticism_off_drops_only_calibration_not_policy(self):
        body = self._render_maestro("off")
        assert "Skepticism Calibration" not in body
        assert "Strictness Policy" in body


class TestPolicyNotice:
    """`policy_notice` surfaces the 'you're guarded now' migration message at P2."""

    def test_notice_fires_for_guarded(self):
        from carter.scaffold import policy_notice

        msg = policy_notice(generate_default_config())  # new install -> guarded
        assert msg is not None
        assert "guarded" in msg.lower()

    def test_no_notice_for_loose(self):
        from carter.scaffold import policy_notice

        cfg = generate_default_config()
        cfg["policy"]["level"] = "loose"
        assert policy_notice(cfg) is None


class TestNarratorR6Handoff:
    """The narrator template wires the R6 overlay: author + redact -> devops transmits."""

    def test_narrator_describes_devops_transmit_handoff(self):
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        body = render_agents(cfg, create_env())["carter-narrator.md"]
        assert "devops" in body.lower()
        assert "transmit" in body.lower()


# ─── carter init CLI flags (--target / --agent-suffix) ───────────────────────


class TestInitFlags:
    """`carter init` flags override config before it is persisted and rendered."""

    def _run_init(self, tmp_path, *args):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        return runner.invoke(main, ["init", str(tmp_path), "--no-git-state", *args])

    def test_target_flag_writes_opencode(self, tmp_path):
        result = self._run_init(tmp_path, "--target", "opencode")
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".opencode" / "agents").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".github").exists()

    def test_target_flag_persisted_in_config(self, tmp_path):
        self._run_init(tmp_path, "--target", "all")
        config = load_config(tmp_path / ".carter" / "carter.yaml")
        assert config["target"] == "all"

    def test_agent_suffix_flag(self, tmp_path):
        result = self._run_init(tmp_path, "--agent-suffix", "demo")
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".github" / "agents" / "carter-maestro-demo.md").exists()
        config = load_config(tmp_path / ".carter" / "carter.yaml")
        assert config["agent_suffix"] == "demo"

    def test_empty_agent_suffix_flag(self, tmp_path):
        result = self._run_init(tmp_path, "--agent-suffix", "")
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".github" / "agents" / "carter-maestro.md").exists()

    def test_invalid_target_rejected(self, tmp_path):
        result = self._run_init(tmp_path, "--target", "bogus")
        assert result.exit_code != 0

    def test_invalid_agent_suffix_rejected(self, tmp_path):
        result = self._run_init(tmp_path, "--agent-suffix", "Bad!")
        assert result.exit_code != 0
        assert "agent_suffix" in result.output

    def test_init_warns_on_redaction_gap(self, tmp_path):
        # Default config has narrator + redaction on, so no warning by default;
        # this asserts the happy path stays clean.
        result = self._run_init(tmp_path)
        assert result.exit_code == 0
        assert "NO redaction" not in result.output


# ─── Risk-Based Strictness Policy Frontmatter (P2 / ADR-0005) ────────────────


_ALL_ROLES = ["maestro", "architect", "engineer", "devops", "pm", "learner", "narrator"]


def _policy_config(level: str = "guarded", target: str = "copilot") -> dict:
    """Default config pinned to a policy level + target, canonical agent names."""
    cfg = generate_default_config(workspace_name="policy", mode="single")
    cfg["agent_suffix"] = ""
    cfg["policy"]["level"] = level
    cfg["target"] = target
    return cfg


def _policy_block(config: dict, role: str) -> dict:
    """Parse the emitted policy frontmatter for a role into a dict."""
    return yaml.safe_load(policy_frontmatter(config, role))


class TestPolicyFrontmatterModel:
    """The deterministic ``policy:`` block is the target-agnostic source of truth."""

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_allow_matches_effective_allowlist(self, role):
        cfg = _policy_config()
        block = _policy_block(cfg, role)
        expected = sorted(c for c, on in effective_allowlist(cfg)[role].items() if on)
        assert block["policy"]["allow"] == expected

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_gates_match_guarded_level(self, role):
        block = _policy_block(_policy_config(level="guarded"), role)
        for cat, gate in block["policy"]["gates"].items():
            assert gate == RISK_TAXONOMY[cat]["guarded"]

    @pytest.mark.parametrize("role", _ALL_ROLES)
    def test_gates_cover_exactly_allowed_categories(self, role):
        block = _policy_block(_policy_config(), role)
        assert sorted(block["policy"]["gates"]) == block["policy"]["allow"]

    def test_devops_holds_remote_infra_destructive(self):
        block = _policy_block(_policy_config(), "devops")
        assert block["policy"]["allow"] == ["R0", "R1", "R2", "R3", "R4", "R5"]

    def test_narrator_holds_external_publish(self):
        block = _policy_block(_policy_config(), "narrator")
        assert block["policy"]["allow"] == ["R0", "R1", "R6"]

    def test_orchestrators_hold_read_only(self):
        for role in ("maestro", "architect", "learner"):
            block = _policy_block(_policy_config(), role)
            assert block["policy"]["allow"] == ["R0"]

    def test_guarded_gates_are_concrete(self):
        gates = _policy_block(_policy_config(), "devops")["policy"]["gates"]
        assert gates["R0"] == "allow"
        assert gates["R2"] == "ask"
        assert gates["R3"] == "gate"
        assert gates["R5"] == "gate"

    def test_loose_emits_all_allow(self):
        gates = _policy_block(_policy_config(level="loose"), "devops")["policy"]["gates"]
        assert set(gates.values()) == {"allow"}

    def test_policy_block_emitted_for_every_target(self):
        for target in ("copilot", "opencode", "all"):
            block = _policy_block(_policy_config(target=target), "devops")
            assert "policy" in block


class TestPolicyStrictEnabled:
    """P2->P3 gate open (step 9): ``strict`` emits the real deny maps, backed by
    the step-7 lint (hard ack) and the step-8 escape hatch."""

    def test_strict_emits_deny_gates(self):
        block = _policy_block(_policy_config(level="strict"), "devops")
        gates = block["policy"]["gates"]
        assert gates["R3"] == "deny"
        assert gates["R5"] == "deny"

    def test_strict_level_is_strict(self):
        block = _policy_block(_policy_config(level="strict"), "devops")
        assert block["policy"]["level"] == "strict"

    def test_strict_has_no_pending_marker(self):
        raw = policy_frontmatter(_policy_config(level="strict"), "devops")
        assert "pending P3" not in raw

    def test_strict_permission_bash_denies_destructive(self):
        block = _policy_block(_policy_config(level="strict", target="opencode"), "devops")
        bash = block["permission"]["bash"]
        # devops holds R3/R5 (deny at strict) -> those commands deny on OpenCode,
        # but local shell stays available so the agent can still work.
        assert bash["*"] == "allow"
        assert bash["terraform apply*"] == "deny"
        assert bash["rm -rf*"] == "deny"

    def test_read_only_agents_unaffected_by_strict(self):
        # architect holds only R0 (allow at every level) -> no deny leaks in.
        block = _policy_block(_policy_config(level="strict"), "architect")
        assert set(block["policy"]["gates"].values()) == {"allow"}


class TestStrictGateMatrix:
    """Step 9: strict emission + lint across targets (the P2->P3 gate proof).
    Runtime denial itself is out of scope (Q17) — we prove emission + lint."""

    def _installed(self, config: dict) -> dict:
        return {role: yaml.safe_load(policy_frontmatter(config, role)) for role in _ALL_ROLES}

    def test_strict_on_opencode_lints_clean(self):
        from carter.scaffold import lint_policy

        cfg = _policy_config(level="strict", target="opencode")
        errors, _ = lint_policy(cfg, self._installed(cfg))
        assert errors == []  # OpenCode enforces -> no hard-ack needed

    def test_strict_on_copilot_fails_closed(self):
        from carter.scaffold import lint_policy

        cfg = _policy_config(level="strict", target="copilot")
        errors, _ = lint_policy(cfg, self._installed(cfg))
        assert any("accept-degraded" in e for e in errors)

    def test_strict_on_copilot_passes_with_ack(self):
        from carter.scaffold import lint_policy

        cfg = _policy_config(level="strict", target="copilot")
        errors, warnings = lint_policy(cfg, self._installed(cfg), accept_degraded=True)
        assert errors == []
        assert any("degrades to advisory" in w for w in warnings)

    def test_strict_emitted_frontmatter_lints_without_drift(self):
        from carter.scaffold import lint_policy

        cfg = _policy_config(level="strict", target="opencode")
        errors, _ = lint_policy(cfg, self._installed(cfg))
        # The emitted strict frontmatter matches the strict model — no drift.
        assert not [e for e in errors if "drifted" in e]


class TestPolicyTargetShaping:
    """Native enforcement keys follow the resolved target (copilot|opencode|all)."""

    def test_copilot_emits_tools_only(self):
        block = _policy_block(_policy_config(target="copilot"), "devops")
        assert "tools" in block
        assert "permission" not in block

    def test_opencode_emits_permission_only(self):
        block = _policy_block(_policy_config(target="opencode"), "devops")
        assert "permission" in block
        assert "tools" not in block

    def test_all_emits_both_native_forms(self):
        block = _policy_block(_policy_config(target="all"), "devops")
        assert "tools" in block
        assert "permission" in block

    def test_tools_are_per_agent_mcp_scope(self):
        assert _policy_block(_policy_config(), "devops")["tools"] == [
            "carter-github/*",
            "carter-terraform/*",
        ]
        assert _policy_block(_policy_config(), "pm")["tools"] == [
            "carter-atlassian/*",
            "carter-github/*",
        ]
        assert _policy_block(_policy_config(), "learner")["tools"] == ["carter-atlassian/*"]

    def test_agents_without_mcp_scope_omit_tools(self):
        for role in ("maestro", "narrator"):
            block = _policy_block(_policy_config(target="copilot"), role)
            assert "tools" not in block

    def test_tools_track_the_scope_constant(self):
        # Guard the role->servers map from drifting out of the emitted tools.
        for role, servers in AGENT_MCP_SCOPE.items():
            block = _policy_block(_policy_config(target="copilot"), role)
            if servers:
                assert block["tools"] == [f"carter-{s}/*" for s in sorted(servers)]
            else:
                assert "tools" not in block


class TestPolicyOpenCodePermission:
    """Best-effort OpenCode permission map derived from allowlist x gates."""

    def test_devops_permission_guarded(self):
        perm = _policy_block(_policy_config(target="opencode"), "devops")["permission"]
        assert perm["edit"] == "allow"
        assert perm["webfetch"] == "allow"
        # devops holds R2/R3/R5 (gate->ask at guarded); local shell stays open.
        assert perm["bash"]["*"] == "allow"
        assert perm["bash"]["git push*"] == "ask"
        assert perm["bash"]["rm -rf*"] == "ask"

    def test_edit_denied_without_local_write(self):
        perm = _policy_block(_policy_config(target="opencode"), "architect")["permission"]
        assert perm["edit"] == "deny"

    def test_local_write_agent_keeps_local_bash_denies_remote(self):
        # The regression fix: an R0/R1 agent (engineer) must run local shell
        # (pytest, git status/add/commit) yet cannot push/apply/destroy.
        perm = _policy_block(_policy_config(target="opencode"), "engineer")["permission"]
        assert perm["bash"]["*"] == "allow"
        assert perm["bash"]["git push*"] == "deny"
        assert perm["bash"]["terraform apply*"] == "deny"
        assert perm["bash"]["rm -rf*"] == "deny"

    def test_read_only_agent_bash_baseline_is_ask(self):
        # architect holds only R0 (no local-write) -> shell prompts, dangerous deny.
        perm = _policy_block(_policy_config(target="opencode"), "architect")["permission"]
        assert perm["bash"]["*"] == "ask"
        assert perm["bash"]["git push*"] == "deny"

    def test_webfetch_always_allowed(self):
        for role in _ALL_ROLES:
            perm = _policy_block(_policy_config(target="opencode"), role)["permission"]
            assert perm["webfetch"] == "allow"

    def test_loose_bash_allowed_for_pusher(self):
        perm = _policy_block(_policy_config(level="loose", target="opencode"), "devops")[
            "permission"
        ]
        # loose: every gate is allow, so even remote/destructive shell is allowed.
        assert perm["bash"]["*"] == "allow"
        assert perm["bash"]["git push*"] == "allow"


class TestPolicyRenderedIntegration:
    """The policy block lands in rendered agent frontmatter as valid YAML."""

    def test_rendered_frontmatter_parses_with_policy(self, env):
        rendered = render_agents(_policy_config(), env)
        assert rendered
        for name, content in rendered.items():
            assert content.startswith("---\n"), f"{name}: no frontmatter"
            _, fm, _ = content.split("---", 2)
            data = yaml.safe_load(fm)
            assert data["description"], f"{name}: lost description"
            assert data["mode"], f"{name}: lost mode"
            assert "policy" in data, f"{name}: missing policy block"
            assert "allow" in data["policy"] and "gates" in data["policy"]

    def test_rendered_devops_policy_matches_model(self, env):
        content = render_agents(_policy_config(), env)["carter-devops.md"]
        _, fm, _ = content.split("---", 2)
        data = yaml.safe_load(fm)
        assert data["policy"]["allow"] == ["R0", "R1", "R2", "R3", "R4", "R5"]
        assert data["tools"] == ["carter-github/*", "carter-terraform/*"]


class TestConfigureMcpServersUnchanged:
    """Per-agent MCP scope lives in agent frontmatter, NOT the global wiring."""

    def test_global_server_set_is_the_shipped_triple(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(["opencode"], tmp_path, manifest, {}, tmp_path / "backup")
        assert manifest["mcp_servers"] == [
            "carter-github",
            "carter-terraform",
            "carter-atlassian",
        ]
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        assert {"carter-github", "carter-terraform", "carter-atlassian"} <= set(opencode_cfg["mcp"])

    def test_no_per_agent_dimension_in_global_wiring(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(["opencode"], tmp_path, manifest, {}, tmp_path / "backup")
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        for role in _ALL_ROLES:
            assert role not in opencode_cfg["mcp"]
