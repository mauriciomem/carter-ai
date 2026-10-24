"""Tests for Carter scaffold — template rendering and workspace initialization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from carter.config import (
    ConfigError,
    generate_default_config,
    load_config,
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
            "security",
        ]
        # Should not raise
        results = render_agents(default_config, env)
        assert len(results) == 8


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
        (the policy gate is independent of skepticism)."""
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
        """The quality-gate must_haves directive is omitted when spec_handoff is
        false. Scoped to the <quality_gate> block: the <communication> block
        legitimately names must_haves as Carter protocol vocabulary."""
        default_config["quality_gate"]["enabled"] = True
        default_config["tdd"]["spec_handoff"] = False
        results = render_agents(default_config, env)
        maestro = results["carter-maestro.md"]
        gate = maestro.split("<quality_gate>")[1].split("</quality_gate>")[0]
        assert "must_haves" not in gate

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
    tools actually discover: .opencode/agents/ + AGENTS.md (ADR-0014: OpenCode only).
    skip-if-exists.
    """

    def _agent_names(self, config: dict) -> list[str]:
        return [f"carter-{a}.md" for a in config["agents"]]

    def test_writes_opencode_paths_only(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        _render_and_write(tmp_path, default_config, env)

        agents_dir = tmp_path / ".opencode" / "agents"
        for name in self._agent_names(default_config):
            assert (agents_dir / name).exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".github").exists()
        assert not (tmp_path / "agents").exists()

    def test_instructions_skip_if_exists(self, tmp_path, default_config, env):
        from carter.cli import _render_and_write

        instr = tmp_path / "AGENTS.md"
        instr.write_text("USER CONTENT")

        _render_and_write(tmp_path, default_config, env)

        assert instr.read_text() == "USER CONTENT"
        assert (tmp_path / ".opencode" / "agents" / "carter-maestro.md").exists()

    def test_agents_rewritten_on_update(self, tmp_path, default_config, env):
        """Carter-owned agents are overwritten so `carter update` refreshes them."""
        from carter.cli import _render_and_write

        agent = tmp_path / ".opencode" / "agents" / "carter-maestro.md"
        agent.parent.mkdir(parents=True)
        agent.write_text("STALE")

        _render_and_write(tmp_path, default_config, env)

        assert agent.read_text() != "STALE"
        assert "Carter Maestro" in agent.read_text()


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

    def test_agents_roster_rendered_only_for_primary(self, env):
        cfg = generate_default_config()
        rendered = render_agents(cfg, env)
        for name, content in rendered.items():
            has_roster = "## Available Agents" in content
            assert has_roster == name.startswith("carter-maestro"), name

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

        cfg = generate_default_config()  # suffix local
        _render_and_write(tmp_path, cfg, env)
        assert (tmp_path / ".opencode" / "agents" / "carter-maestro-local.md").exists()
        assert (tmp_path / ".opencode" / "agents" / "carter-engineer-local.md").exists()

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


# ─── Policy gate table + notice + redaction handoff (P2 / ADR-0010 D4/D5) ──────


class TestPolicyGateTable:
    """`policy_gate_table` drives the always-on maestro risk/gate table."""

    def test_guarded_table_has_all_four_categories(self):
        from carter.config import policy_gate_table

        rows = policy_gate_table({"policy": {"level": "guarded"}})
        assert [r["category"] for r in rows] == [
            "read",
            "local-write",
            "remote-write",
            "dangerous",
        ]

    def test_guarded_gates_match_taxonomy(self):
        from carter.config import policy_gate_table

        gates = {
            r["category"]: r["gate"] for r in policy_gate_table({"policy": {"level": "guarded"}})
        }
        assert gates == {
            "read": "allow",
            "local-write": "allow",
            "remote-write": "ask",
            "dangerous": "gate",
        }

    def test_strict_table_emits_deny(self):
        """strict emits deny for dangerous and gate for remote-write."""
        from carter.config import policy_gate_table

        gates = {
            r["category"]: r["gate"] for r in policy_gate_table({"policy": {"level": "strict"}})
        }
        assert gates["dangerous"] == "deny"
        assert gates["remote-write"] == "gate"

    def test_missing_policy_defaults_guarded(self):
        from carter.config import policy_gate_table

        # ADR-0010 D3: an absent policy block resolves to guarded (the floor).
        gates = {r["category"]: r["gate"] for r in policy_gate_table({})}
        assert gates["remote-write"] == "ask"
        assert gates["dangerous"] == "gate"


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
    """`policy_notice` surfaces the active-level notice. ADR-0010 D3: both shipped
    levels enforce gates, so the notice always fires (no quiet advisory level)."""

    def test_notice_fires_for_guarded(self):
        from carter.scaffold import policy_notice

        msg = policy_notice(generate_default_config())  # new install -> guarded
        assert msg is not None
        assert "guarded" in msg.lower()

    def test_notice_fires_for_strict(self):
        from carter.scaffold import policy_notice

        cfg = generate_default_config()
        cfg["policy"]["level"] = "strict"
        msg = policy_notice(cfg)
        assert msg is not None
        assert "strict" in msg.lower()


class TestNarratorRedactionHandoff:
    """The narrator template wires the enforced `gate`-tier redaction handoff
    (ADR-0010 D5): narrator drafts + redacts locally, devops (sole remote-write
    holder) transmits. No R6 overlay; narrator is first-class."""

    def test_narrator_describes_devops_transmit_handoff(self):
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        body = render_agents(cfg, create_env())["carter-narrator.md"].lower()
        assert "devops" in body
        assert "transmit" in body
        assert "gate`-tier" in body  # the enforced handoff, not a convention
        assert "remote-write" in body  # narrator does not hold it

    def test_maestro_encodes_gate_tier_redaction_handoff(self):
        # ADR-0010 D5: substantive outward content is a `gate`-tier narrator handoff
        # routed to devops to transmit; one-liners = ask + inline check. No R6 overlay.
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        body = render_agents(cfg, create_env())["carter-maestro.md"]
        assert "gate`-tier redaction handoff" in body
        assert "carter-narrator" in body and "carter-devops" in body
        assert "inline redaction check" in body  # the one-liner lane
        assert "R6 overlay" not in body and "external-publish" not in body

    def test_force_pass_is_decoupled_from_r6(self):
        # ADR-0010 D5.2: the guarded/strict forced redaction pass is retained and
        # independent of the dropped R6 — it hangs off policy.level, not a category.
        cfg = generate_default_config()
        cfg["agent_suffix"] = ""
        cfg["redaction"]["enabled"] = False
        for level in ("guarded", "strict"):
            cfg["policy"]["level"] = level
            body = render_agents(cfg, create_env())["carter-narrator.md"]
            assert "<redaction_rules>" in body, f"{level}: forced pass missing"


# ─── carter init CLI flags (--agent-suffix) ───────────────────────


class TestInitFlags:
    """`carter init` flags override config before it is persisted and rendered."""

    def _run_init(self, tmp_path, *args):
        from click.testing import CliRunner

        from carter.cli import main

        runner = CliRunner()
        return runner.invoke(main, ["init", str(tmp_path), "--no-git-state", *args])

    def test_init_writes_opencode(self, tmp_path):
        result = self._run_init(tmp_path)
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".opencode" / "agents").exists()
        assert (tmp_path / "AGENTS.md").exists()
        assert not (tmp_path / ".github").exists()
        assert "target" not in load_config(tmp_path / ".carter" / "carter.yaml")

    def test_agent_suffix_flag(self, tmp_path):
        result = self._run_init(tmp_path, "--agent-suffix", "demo")
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".opencode" / "agents" / "carter-maestro-demo.md").exists()
        config = load_config(tmp_path / ".carter" / "carter.yaml")
        assert config["agent_suffix"] == "demo"

    def test_empty_agent_suffix_flag(self, tmp_path):
        result = self._run_init(tmp_path, "--agent-suffix", "")
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".opencode" / "agents" / "carter-maestro.md").exists()

    def test_target_flag_removed(self, tmp_path):
        result = self._run_init(tmp_path, "--target", "opencode")
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


_ALL_ROLES = ["maestro", "architect", "engineer", "devops", "pm", "learner", "narrator", "security"]


# ─── Rendered V2 frontmatter (ADR-0014 D1/D5) ──────────────────────────────
# The rule-order contract itself lives in tests/test_policy_lint.py.


class TestPolicyRenderedIntegration:
    """Rendered agents carry V2 ``permissions:`` and no ``carter:policy`` comment."""

    def test_rendered_frontmatter_is_v2(self, env, default_config):
        rendered = render_agents(default_config, env)
        assert rendered
        for name, content in rendered.items():
            assert content.startswith("---\n"), f"{name}: no frontmatter"
            _, fm, body = content.split("---", 2)
            data = yaml.safe_load(fm)
            assert data["description"], f"{name}: lost description"
            assert data["mode"], f"{name}: lost mode"
            assert isinstance(data["permissions"], list), name
            assert "policy" not in data and "permission" not in data, name
            assert "carter:policy" not in body, name

    def test_strict_devops_denies_dangerous(self, env, default_config):
        default_config["policy"]["level"] = "strict"
        content = render_agents(default_config, env)["carter-devops.md"]
        rules = yaml.safe_load(content.split("---", 2)[1])["permissions"]
        assert {"action": "shell", "resource": "rm -rf *", "effect": "deny"} in rules
        assert rules[-1]["effect"] == "deny"


class TestConfigureMcpServersUnchanged:
    """Per-agent MCP scope lives in agent frontmatter, NOT the global wiring."""

    def test_global_server_set_is_the_shipped_triple(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(["opencode"], tmp_path, manifest, {}, tmp_path / "backup")
        assert manifest["mcp_servers"] == {
            "opencode": ["carter-github", "carter-terraform", "carter-atlassian"]
        }
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        assert {"carter-github", "carter-terraform", "carter-atlassian"} <= set(opencode_cfg["mcp"])

    def test_no_per_agent_dimension_in_global_wiring(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(["opencode"], tmp_path, manifest, {}, tmp_path / "backup")
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        for role in _ALL_ROLES:
            assert role not in opencode_cfg["mcp"]


class TestMcpServerOptIn:
    """`configure_mcp_servers` installs only the
    servers a workspace selects; an unused server adds zero tool-schema tokens. Omitting
    the selection preserves today's behaviour (all shipped servers).
    """

    def test_subset_wires_only_selected_opencode(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(
            ["opencode"], tmp_path, manifest, {}, tmp_path / "backup", servers=["github"]
        )
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        wired = set(opencode_cfg["mcp"])
        # Only the selected server's schema is present; the others contribute nothing.
        assert "carter-github" in wired
        assert "carter-terraform" not in wired
        assert "carter-atlassian" not in wired
        assert manifest["mcp_servers"] == {"opencode": ["carter-github"]}

    def test_subset_wires_only_selected_copilot_vscode(self, tmp_path):
        from carter import installer

        # A VS Code settings.json must exist for the copilot path to write to it.
        (tmp_path / ".vscode").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".vscode" / "settings.json").write_text("{}")
        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        installer.configure_mcp_servers(
            ["copilot"],
            tmp_path,
            manifest,
            {},
            tmp_path / "backup",
            servers=["github", "terraform"],
        )
        assert manifest["mcp_servers"] == {"copilot": ["carter-github", "carter-terraform"]}

    def test_default_is_all_servers_backward_compatible(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        # No `servers=` arg → today's behaviour: the full shipped set.
        installer.configure_mcp_servers(["opencode"], tmp_path, manifest, {}, tmp_path / "backup")
        assert manifest["mcp_servers"] == {
            "opencode": ["carter-github", "carter-terraform", "carter-atlassian"]
        }

    def test_atlassian_skipped_for_copilot_wired_for_opencode(self, tmp_path, capsys):
        from carter import installer

        settings = tmp_path / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True)
        # A stale npx bridge entry from an older install is removed.
        settings.write_text(json.dumps({"mcp.servers": {"carter-atlassian": {"command": "npx"}}}))
        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        count = installer.configure_mcp_servers(
            ["copilot", "opencode"],
            tmp_path,
            manifest,
            {},
            tmp_path / "backup",
            servers=["atlassian"],
        )
        assert "carter-atlassian: not available for copilot" in capsys.readouterr().out
        assert count == 1  # only the OpenCode entry
        assert manifest["mcp_servers"] == {"copilot": [], "opencode": ["carter-atlassian"]}
        assert "carter-atlassian" not in json.loads(settings.read_text())["mcp.servers"]
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        assert opencode_cfg["mcp"]["carter-atlassian"]["type"] == "remote"

    def test_cli_atlassian_copilot_only_succeeds(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main,
            [
                "install",
                "--target",
                "copilot",
                "--mcp",
                "--mcp-servers",
                "atlassian",
                "--base-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        assert "carter-atlassian: not available for copilot" in result.output

    def test_unknown_server_is_rejected(self, tmp_path):
        from carter import installer

        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        with pytest.raises(ValueError, match="bogus"):
            installer.configure_mcp_servers(
                ["opencode"], tmp_path, manifest, {}, tmp_path / "backup", servers=["bogus"]
            )

    def test_cli_mcp_servers_subset(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main,
            [
                "install",
                "--target",
                "opencode",
                "--mcp",
                "--mcp-servers",
                "github",
                "--base-dir",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0, result.output
        opencode_cfg = json.loads((tmp_path / "opencode" / "opencode.json").read_text())
        wired = set(opencode_cfg["mcp"])
        assert "carter-github" in wired
        assert "carter-terraform" not in wired
        assert "carter-atlassian" not in wired

    def test_cli_mcp_servers_rejects_unknown(self, tmp_path):
        from click.testing import CliRunner

        from carter.cli import main

        result = CliRunner().invoke(
            main,
            ["install", "--mcp", "--mcp-servers", "bogus", "--base-dir", str(tmp_path)],
        )
        assert result.exit_code != 0
        assert "bogus" in result.output


class TestInitProfileFlag:
    """`carter init --profile` seeds the cost profile into the scaffolded carter.yaml and
    it flows through to the rendered agent models.
    """

    def _run(self, tmp_path, *args):
        from click.testing import CliRunner

        from carter.cli import main

        return CliRunner().invoke(main, ["init", str(tmp_path), *args])

    def test_quality_profile_seeds_key_and_renders_opus(self, tmp_path):
        result = self._run(tmp_path, "--profile", "quality")
        assert result.exit_code == 0, result.output
        cfg = load_config(tmp_path / ".carter" / "carter.yaml")
        assert cfg["profile"] == "quality"
        # narrator (default Sonnet) is lifted to Opus under quality in the rendered file.
        narrator = (tmp_path / ".opencode" / "agents" / "carter-narrator-local.md").read_text()
        assert "model: anthropic/claude-opus-5-5" in narrator

    def test_default_init_has_no_profile_key(self, tmp_path):
        result = self._run(tmp_path)
        assert result.exit_code == 0, result.output
        cfg = load_config(tmp_path / ".carter" / "carter.yaml")
        assert cfg.get("profile") is None
        # narrator ships on Sonnet by default.
        narrator = (tmp_path / ".opencode" / "agents" / "carter-narrator-local.md").read_text()
        assert "model: anthropic/claude-sonnet-5-5" in narrator

    def test_invalid_profile_is_rejected(self, tmp_path):
        result = self._run(tmp_path, "--profile", "cheapest")
        assert result.exit_code != 0
        # click.Choice rejects it before any scaffolding happens.
        assert not (tmp_path / ".carter").exists()


class TestLanguageAndCoAuthorRules:
    """Decisions A/B/C: English repository output, docs_language for internal docs,
    and the user as commit author with a Co-authored-by trailer."""

    def _render(self, **overrides):
        cfg = generate_default_config(workspace_name="lang", mode="single")
        cfg["agent_suffix"] = ""
        cfg.update(overrides)
        env = create_env()
        return render_agents(cfg, env), render_instructions(cfg, env)

    def test_workspace_docs_language_is_named(self):
        agents, instructions = self._render(docs_language="es")
        for role in ("maestro", "pm", "architect", "security"):
            assert "`es` (`docs_language`)" in agents[f"carter-{role}.md"], role
        assert "`es` (`docs_language`)" in instructions["copilot-instructions.md"]

    def test_global_render_defers_to_workspace_setting(self):
        agents, _ = self._render(docs_language=None)
        assert "the workspace `docs_language`" in agents["carter-pm.md"]

    def test_committers_use_trailer_never_author(self):
        agents, instructions = self._render()
        for role in ("engineer", "devops", "maestro"):
            text = agents[f"carter-{role}.md"]
            assert "Co-authored-by:" in text, role
            assert "never pass `--author`" in text.lower() or "never `--author`" in text, role
        assert "Co-authored-by:" in instructions["copilot-instructions.md"]

    def test_narrator_outward_content_is_english(self):
        agents, _ = self._render(docs_language="es")
        assert "is written in English, whatever language" in agents["carter-narrator.md"]

    def test_global_opencode_install_defers_docs_language(self):
        from carter.install.components import _render_opencode_agents

        pm = _render_opencode_agents()["carter-pm.md"]
        assert "the workspace `docs_language`" in pm
        assert "`en` (`docs_language`)" not in pm
