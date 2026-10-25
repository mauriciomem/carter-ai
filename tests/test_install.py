"""Tests for the Carter installer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from carter.config import generate_default_config
from carter.install import components, legacy, mcp, paths
from carter.install import uninstall as uninstall_mod
from carter.install.components import (
    _OPENCODE_AGENTS_MD,
    _OPENCODE_AGENTS_MD_LEGACY,
    _OPENCODE_AGENTS_MD_V2,
)
from carter.install.files import _sha256
from carter.install.jsonc import _load_jsonc, _strip_jsonc
from carter.scaffold import create_env, render_agents

# One namespace over the installer leaves so the tests read like the CLI surface.
install = SimpleNamespace(
    REPO_ROOT=paths.REPO_ROOT,
    MCP_SERVERS=mcp.MCP_SERVERS,
    install_agents=components.install_agents,
    install_skills=components.install_skills,
    install_knowledge=components.install_knowledge,
    install_memories=components.install_memories,
    install_ops=components.install_ops,
    install_opencode_rules=components.install_opencode_rules,
    remove_legacy_opencode_instructions=legacy.remove_legacy_opencode_instructions,
    read_manifest=components.read_manifest,
    write_manifest=components.write_manifest,
    uninstall=uninstall_mod.uninstall,
)

# ──────────────────────────────────────────────────────────────────────────────
# File operations
# ──────────────────────────────────────────────────────────────────────────────


class TestInstallAgents:
    def test_creates_agents(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents_dir = base_dir / "opencode" / "agents"
        assert agents_dir.exists()

        expected = [
            "carter-architect.md",
            "carter-devops.md",
            "carter-engineer.md",
            "carter-learner.md",
            "carter-maestro.md",
            "carter-narrator.md",
            "carter-pm.md",
            "carter-security.md",
        ]
        actual = sorted(f.name for f in agents_dir.glob("carter-*.md"))
        assert actual == expected

    def test_creates_opencode_agents(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents_dir = base_dir / "opencode" / "agents"
        assert agents_dir.exists()
        actual = sorted(f.name for f in agents_dir.glob("carter-*.md"))
        assert len(actual) == 8

    def test_opencode_agents_are_permission_shaped_not_tools_array(self, base_dir: Path) -> None:
        """OpenCode rejects the copilot ``tools:`` ARRAY ("Expected object | undefined,
        got [...]"). The installer must render OpenCode-shaped frontmatter for the
        opencode target — a V2 ``permissions`` list, a ``provider/model`` id, and NO
        ``tools`` array — never copy the copilot static file verbatim (ADR-0012). This
        is the regression that broke ``opencode`` CLI on a fresh global install.
        """
        import yaml

        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents_dir = base_dir / "opencode" / "agents"
        for agent in sorted(agents_dir.glob("carter-*.md")):
            fm = yaml.safe_load(agent.read_text().split("---")[1])
            assert "tools" not in fm, (
                f"{agent.name}: opencode agent carries a copilot 'tools' key "
                "(OpenCode rejects the array)"
            )
            assert isinstance(fm.get("permissions"), list), (
                f"{agent.name}: opencode agent missing the V2 'permissions' list"
            )
            assert "permission" not in fm, f"{agent.name}: opencode agent carries V1 'permission'"
            model = fm.get("model", "")
            assert str(model).startswith("anthropic/"), (
                f"{agent.name}: opencode agent must use a provider/model id, got {model!r}"
            )

    def test_manifest_tracks_files(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        assert len(manifest["files"]) == 8
        assert len(manifest["file_hashes"]) == 8
        for h in manifest["file_hashes"].values():
            assert h.startswith("sha256:")


class TestInstallSkills:
    def test_creates_skills(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        assert skills_dir.exists()

        skill_dirs = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
        assert len(skill_dirs) == 28
        for d in skill_dirs:
            assert d.startswith("carter-")
            assert (skills_dir / d / "SKILL.md").exists()

        # carter-terraform has sub-files alongside SKILL.md
        tf_dir = skills_dir / "carter-terraform"
        for sub in ("testing.md", "modules.md", "import.md", "stacks.md"):
            assert (tf_dir / sub).exists()

        # carter-packer has sub-files alongside SKILL.md
        pk_dir = skills_dir / "carter-packer"
        for sub in ("aws.md", "azure.md", "windows.md", "hcp.md"):
            assert (pk_dir / sub).exists()

        # carter-pipeline has sub-files alongside SKILL.md
        pl_dir = skills_dir / "carter-pipeline"
        for sub in ("github-cli.md", "strategies.md", "actions.md"):
            assert (pl_dir / sub).exists()

    def test_creates_opencode_skills(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        skill_dirs = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
        assert len(skill_dirs) == 28


_SHIPPED_TEXT = "# Carter — Global Instructions (a version Carter shipped)\n"


class TestInstallInstructions:
    @pytest.fixture(autouse=True)
    def _known_shipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        digest = hashlib.sha256(_SHIPPED_TEXT.encode()).hexdigest()
        monkeypatch.setattr(legacy, "_SHIPPED_INSTRUCTIONS_SHA256", frozenset({f"sha256:{digest}"}))

    @staticmethod
    def _legacy(base_dir: Path, content: str) -> Path:
        stale = base_dir / "opencode" / "instructions" / "copilot-instructions.md"
        stale.parent.mkdir(parents=True)
        stale.write_text(content)
        return stale

    @staticmethod
    def _shipped() -> str:
        return _SHIPPED_TEXT

    def test_carter_owned_legacy_copy_removed(self, base_dir: Path) -> None:
        stale = self._legacy(base_dir, self._shipped())
        install.remove_legacy_opencode_instructions(base_dir, base_dir / "backup")
        assert not stale.exists()
        assert not stale.parent.exists()  # empty instructions/ dir removed

    def test_manifest_recorded_hash_counts_as_carter_owned(self, base_dir: Path) -> None:
        stale = self._legacy(base_dir, "an older shipped version\n")
        install.write_manifest(
            {"files": [str(stale)], "file_hashes": {str(stale): _sha256(stale)}}, base_dir
        )
        install.remove_legacy_opencode_instructions(base_dir, base_dir / "backup")
        assert not stale.exists()

    def test_user_modified_copy_backed_up_not_deleted(self, base_dir: Path, capsys) -> None:
        stale = self._legacy(base_dir, "my own notes\n")
        (stale.parent / "other.md").write_text("keep")
        backup = base_dir / "backup"
        install.remove_legacy_opencode_instructions(base_dir, backup)
        assert not stale.exists()
        moved = backup / "opencode-instructions" / "copilot-instructions.md"
        assert moved.read_text() == "my own notes\n"
        assert (stale.parent / "other.md").exists()  # non-empty dir kept
        assert "was modified" in capsys.readouterr().out

    def test_symlink_not_followed(self, base_dir: Path, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere.md"
        target.write_text(self._shipped())
        link = base_dir / "opencode" / "instructions" / "copilot-instructions.md"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        install.remove_legacy_opencode_instructions(base_dir, base_dir / "backup")
        assert link.is_symlink()
        assert target.read_text() == self._shipped()

    def test_uninstall_without_manifest_removes_carter_owned_copy(self, base_dir: Path) -> None:
        stale = self._legacy(base_dir, self._shipped())
        install.uninstall(base_dir)
        assert not stale.exists()

    def test_uninstall_without_manifest_keeps_modified_copy(self, base_dir: Path, capsys) -> None:
        stale = self._legacy(base_dir, "my own notes\n")
        install.uninstall(base_dir)
        assert stale.read_text() == "my own notes\n"
        assert "left in place" in capsys.readouterr().out


class TestInstallKnowledge:
    def test_creates_knowledge_files(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        count = install.install_knowledge(base_dir, manifest, backup)

        knowledge_dir = base_dir / "carter" / "knowledge"
        assert knowledge_dir.exists()
        assert count == 6

        expected = [
            "debugging.md",
            "decisions.md",
            "infrastructure.md",
            "mistakes.md",
            "patterns.md",
            "project-history.md",
        ]
        actual = sorted(f.name for f in knowledge_dir.glob("*.md"))
        assert actual == expected

    def test_does_not_overwrite_existing(self, base_dir: Path) -> None:
        # Pre-create a knowledge file with custom content
        knowledge_dir = base_dir / "carter" / "knowledge"
        knowledge_dir.mkdir(parents=True, exist_ok=True)
        existing = knowledge_dir / "mistakes.md"
        existing.write_text("# My custom mistakes\n\nKeep this content.\n")

        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_knowledge(base_dir, manifest, backup)

        assert existing.read_text().startswith("# My custom mistakes")


# ──────────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_second_run_unchanged(self, base_dir: Path) -> None:
        # First install
        manifest1 = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest1, backup)

        # Second install
        manifest2 = {"files": [], "file_hashes": {}}
        stats = install.install_agents(base_dir, manifest2, backup)

        assert stats["unchanged"] == 8
        assert stats["created"] == 0
        assert stats["updated"] == 0

    def test_modified_file_detected_as_updated(self, base_dir: Path) -> None:
        # First install
        manifest1 = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest1, backup)

        # Modify an installed file
        agent_file = base_dir / "opencode" / "agents" / "carter-maestro.md"
        agent_file.write_text("modified content\n")

        # Second install
        manifest2 = {"files": [], "file_hashes": {}}
        stats = install.install_agents(base_dir, manifest2, backup)

        assert stats["updated"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# MCP merging
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# MCP server list — single source (D5)
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPServerSingleSource:
    """The MCP server triple must come from one module constant,
    not be hardcoded separately in install and uninstall (drift risk).
    """

    def test_mcp_servers_constant_is_the_triple(self) -> None:
        assert tuple(install.MCP_SERVERS) == ("github", "terraform", "atlassian")

    def test_server_triple_not_hardcoded_twice(self) -> None:
        """Both install and uninstall must reference install.MCP_SERVERS — the
        literal list may not be hardcoded anywhere in the module."""
        for module in (mcp, uninstall_mod):
            src = Path(module.__file__).read_text()
            assert '["github", "terraform", "atlassian"]' not in src


class TestOfficialGitHubServer:
    """ADR-0008 D2: the shipped GitHub MCP server is the official
    github/github-mcp-server via Docker, digest-pinned, read-only, with a surgical tool
    allowlist. The archived @modelcontextprotocol/server-github must be gone from the
    shipped configs (grep-clean over mcp/).
    """

    # The surgical read-only tool set (~6,650 tok, +68% over archived).
    EXPECTED_TOOLS = {
        "get_me",
        "get_file_contents",
        "search_code",
        "search_repositories",
        "list_commits",
        "get_commit",
        "pull_request_read",
        "issue_read",
        "list_issues",
        "list_pull_requests",
    }

    def _github_cfg(self, target: str) -> dict:
        path = install.REPO_ROOT / "mcp" / target / "github.json"
        return json.loads(path.read_text())["carter-github"]

    def _command_str(self, entry: dict) -> str:
        # opencode shape: command=list (a str command + args list is also accepted).
        cmd = entry["command"]
        parts = [cmd, *entry.get("args", [])] if isinstance(cmd, str) else list(cmd)
        return " ".join(parts)

    def test_no_archived_server_in_shipped_configs(self) -> None:
        mcp_dir = install.REPO_ROOT / "mcp"
        for cfg in mcp_dir.rglob("*.json"):
            assert "@modelcontextprotocol/server-github" not in cfg.read_text(), (
                f"{cfg}: still references the archived GitHub MCP server"
            )

    def test_opencode_use_official_docker_image(self) -> None:
        for target in ("opencode",):
            cmd = self._command_str(self._github_cfg(target))
            assert "docker" in cmd, f"{target}: not a docker invocation"
            assert "ghcr.io/github/github-mcp-server@sha256:" in cmd, (
                f"{target}: official image must be pinned by digest, not a tag"
            )
            assert ":latest" not in cmd, f"{target}: must not use :latest"

    def test_opencode_are_read_only(self) -> None:
        for target in ("opencode",):
            cmd = self._command_str(self._github_cfg(target))
            assert "--read-only" in cmd, f"{target}: missing --read-only"

    def test_opencode_carry_surgical_tool_allowlist(self) -> None:
        for target in ("opencode",):
            cmd = self._command_str(self._github_cfg(target))
            assert "--tools" in cmd, f"{target}: missing --tools allowlist"
            for tool in self.EXPECTED_TOOLS:
                assert tool in cmd, f"{target}: surgical tool {tool!r} absent"

    def test_token_is_env_placeholder_not_literal(self) -> None:
        for target in ("opencode",):
            entry = self._github_cfg(target)
            env = entry.get("env") or entry.get("environment", {})
            # The PAT is passed by env placeholder, never a baked literal.
            # opencode: {env:VAR} (OpenCode docs, mcp-servers).
            assert any("{env:" in str(v) for v in env.values()), (
                f"{target}: GitHub token must be an env placeholder"
            )


# ──────────────────────────────────────────────────────────────────────────────
# JSONC parsing
# ──────────────────────────────────────────────────────────────────────────────


class TestJSONCParsing:
    def test_strip_single_line_comments(self) -> None:
        text = '{\n  // comment\n  "key": "value"\n}'
        result = json.loads(_strip_jsonc(text))
        assert result == {"key": "value"}

    def test_strip_block_comments(self) -> None:
        text = '{\n  /* block\n     comment */\n  "key": "value"\n}'
        result = json.loads(_strip_jsonc(text))
        assert result == {"key": "value"}

    def test_strip_trailing_commas(self) -> None:
        text = '{\n  "a": 1,\n  "b": 2,\n}'
        result = json.loads(_strip_jsonc(text))
        assert result == {"a": 1, "b": 2}

    def test_preserves_comments_inside_strings(self) -> None:
        text = '{\n  "url": "https://example.com // not a comment",\n  "key": "value"\n}'
        result = json.loads(_strip_jsonc(text))
        assert result["url"] == "https://example.com // not a comment"

    def test_preserves_slashes_inside_strings(self) -> None:
        text = '{\n  "path": "/* keep this */"\n}'
        result = json.loads(_strip_jsonc(text))
        assert result["path"] == "/* keep this */"

    def test_load_jsonc_returns_none_on_garbage(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        assert _load_jsonc(f) is None

    def test_load_jsonc_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.json"
        assert _load_jsonc(f) is None

    def test_realistic_vscode_settings(self) -> None:
        """Parse a realistic VS Code settings.json with mixed JSONC features."""
        text = """{
  "workbench.colorTheme": "Lunar-dark-theme",
  // Font settings
  "editor.fontFamily": "Fira Code",
  "custom-ui-style.stylesheet": {
    // Hide tab close buttons until hover
    ".tab:not(:hover) .tab-actions": {
      "opacity": "0",
      "transition": "opacity 0.15s ease"
    },
    ".tab .tab-actions": {
      "transition": "opacity 0.15s ease"
    }
  },
  /* MCP configuration */
  "mcp.servers": {},
}"""
        result = json.loads(_strip_jsonc(text))
        assert result["workbench.colorTheme"] == "Lunar-dark-theme"
        assert result["editor.fontFamily"] == "Fira Code"
        assert ".tab:not(:hover) .tab-actions" in result["custom-ui-style.stylesheet"]
        assert "mcp.servers" in result


# ──────────────────────────────────────────────────────────────────────────────
# Manifest
# ──────────────────────────────────────────────────────────────────────────────


class TestManifest:
    def test_write_and_read_manifest(self, base_dir: Path) -> None:
        manifest = {
            "version": "1.0.0",
            "installed_at": "2026-05-09T10:00:00+00:00",
            "targets": ["copilot"],
            "files": ["/some/file.md"],
            "file_hashes": {"/some/file.md": "sha256:abc123"},
            "mcp_servers": {"copilot": ["carter-github"]},
        }
        install.write_manifest(manifest, base_dir)
        loaded = install.read_manifest(base_dir)

        assert loaded is not None
        assert loaded["version"] == "1.0.0"
        assert loaded["files"] == ["/some/file.md"]

    def test_read_nonexistent_manifest(self, base_dir: Path) -> None:
        assert install.read_manifest(base_dir) is None


# ──────────────────────────────────────────────────────────────────────────────
# Uninstall
# ──────────────────────────────────────────────────────────────────────────────


class TestUninstall:
    def test_uninstall_removes_carter_files(self, base_dir: Path) -> None:
        # Install first
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)
        install.install_skills(base_dir, manifest, backup)
        manifest["mcp_servers"] = []
        install.write_manifest(manifest, base_dir)

        # Verify files exist
        agents_dir = base_dir / "opencode" / "agents"
        assert len(list(agents_dir.glob("carter-*.md"))) == 8

        # Uninstall
        install.uninstall(base_dir)

        # Verify carter files removed
        assert len(list(agents_dir.glob("carter-*.md"))) == 0

    def test_uninstall_preserves_non_carter_files(self, base_dir: Path) -> None:
        # Install Carter
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)
        manifest["mcp_servers"] = []
        install.write_manifest(manifest, base_dir)

        # Add a non-Carter file
        other = base_dir / "opencode" / "agents" / "other-agent.md"
        other.write_text("not carter\n")

        # Uninstall
        install.uninstall(base_dir)

        # Non-Carter file preserved
        assert other.exists()


# ──────────────────────────────────────────────────────────────────────────────
# Hashing
# ──────────────────────────────────────────────────────────────────────────────


class TestHashing:
    def test_sha256_consistent(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")
        h1 = _sha256(f)
        h2 = _sha256(f)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_sha256_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello\n")
        f2.write_text("world\n")
        assert _sha256(f1) != _sha256(f2)


# ──────────────────────────────────────────────────────────────────────────────
# Ops installation
# ──────────────────────────────────────────────────────────────────────────────


class TestInstallOps:
    def test_generates_config_toml(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup)

        config = base_dir / "carter" / "config.toml"
        assert config.exists()
        content = config.read_text()
        assert "[attribution]" in content
        assert "carter-bot" in content
        assert "[git]" in content
        assert "[jira]" in content

    def test_does_not_overwrite_existing_config(self, base_dir: Path) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('[attribution]\nname = "my-custom-bot"\n')

        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup)

        assert "my-custom-bot" in config.read_text()

    def test_manifest_tracks_config(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup)

        config = base_dir / "carter" / "config.toml"
        assert str(config) in manifest["files"]

    def test_idempotent(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup)

        manifest2 = {"files": [], "file_hashes": {}}
        stats2 = install.install_ops(base_dir, manifest2, backup)

        assert stats2["unchanged"] > 0
        assert stats2["created"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Bot name
# ──────────────────────────────────────────────────────────────────────────────


class TestBotName:
    def test_default_bot_name(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup)

        config = base_dir / "carter" / "config.toml"
        content = config.read_text()
        assert 'name = "carter-bot"' in content
        assert 'email = "carter-bot@users.noreply.github.com"' in content

    def test_custom_bot_name(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup, bot_name="acme-bot")

        config = base_dir / "carter" / "config.toml"
        content = config.read_text()
        assert 'name = "acme-bot"' in content
        assert 'email = "acme-bot@users.noreply.github.com"' in content

    def test_custom_bot_name_footer(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_ops(base_dir, manifest, backup, bot_name="acme-bot")

        config = base_dir / "carter" / "config.toml"
        content = config.read_text()
        assert 'footer = "This comment was generated by acme-bot."' in content


# ──────────────────────────────────────────────────────────────────────────────
# MCP flag
# ──────────────────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────────────────
# Cross-platform path + prerequisite resolution (macOS / Linux)
# ──────────────────────────────────────────────────────────────────────────────


class TestCarterOpsSkill:
    def test_carter_ops_skill_installed(self, base_dir: Path) -> None:
        """carter-ops skill should be installed alongside other skills."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "ops:" in content
        assert "carter-ops" in content
        # Skill teaches direct execution with attribution
        assert "APPROVE" in content
        assert "git commit" in content

    def test_carter_ops_skill_template_substitution(self, base_dir: Path) -> None:
        """carter-ops skill should have template vars substituted at install time."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md"
        content = skill_md.read_text()
        # Template placeholders should be replaced with actual values
        assert "{{BOT_NAME}}" not in content
        assert "{{BOT_EMAIL}}" not in content
        assert "{{SIGNING_KEY}}" not in content

    def test_templated_skill_unchanged_on_reinstall(self, base_dir: Path) -> None:
        """A re-install must not rewrite (and back up) the unchanged templated skill."""
        backup = base_dir / "backup"
        install.install_skills(base_dir, {"files": [], "file_hashes": {}}, backup)
        stats = install.install_skills(base_dir, {"files": [], "file_hashes": {}}, backup)
        assert stats["updated"] == 0
        assert not backup.exists()

    def test_carter_ops_skill_opencode(self, base_dir: Path) -> None:
        """carter-ops skill should be installed for OpenCode target too."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md"
        assert skill_md.exists()


class TestOpenCodeRules:
    def test_creates_agents_md(self, base_dir: Path) -> None:
        """OpenCode global rules file should be created."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_opencode_rules(base_dir, manifest, backup)

        agents_md = base_dir / "opencode" / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "ops:" in content
        assert "carter-ops" in content
        assert "knowledge" in content
        assert "/memories/" in content

    def test_does_not_overwrite(self, base_dir: Path) -> None:
        """Existing AGENTS.md should not be overwritten."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text("# Custom rules\n")

        install.install_opencode_rules(base_dir, manifest, backup)
        assert agents_md.read_text() == "# Custom rules\n"


class TestOpenCodeRulesUpgrade:
    """D3 upgrade path: ``install_opencode_rules`` used to skip whenever the file
    existed, so every legacy install would never receive a content fix. Now it
    content-hashes: byte-identical legacy content is upgraded, user-modified
    content is never clobbered (matching the installer's SHA-256 idempotency
    philosophy).
    """

    def test_fresh_install_has_communication_section(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest, base_dir / "backup")

        content = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert "## Communication" in content
        assert "Be concise and clear" in content
        assert "## Memory" in content  # legacy content retained

    def test_legacy_file_is_upgraded(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text(_OPENCODE_AGENTS_MD_LEGACY)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest, base_dir / "backup")

        content = agents_md.read_text()
        assert "## Communication" in content
        assert content == _OPENCODE_AGENTS_MD

    def test_previous_version_is_upgraded(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text(_OPENCODE_AGENTS_MD_V2)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest, base_dir / "backup")

        content = agents_md.read_text()
        assert content == _OPENCODE_AGENTS_MD
        assert "## Git & Language" in content
        assert "Co-authored-by:" in content
        assert "docs_language" in content

    def test_git_language_section_has_core_rules(self) -> None:
        """The global AGENTS.md Git & Language section keeps its core rules."""
        section = _OPENCODE_AGENTS_MD.split("## Git & Language\n", 1)[1].split("\n## ", 1)[0]
        assert "Never pass `--author`" in section
        assert "Co-authored-by:" in section
        assert "English" in section
        assert "docs_language" in section

    def test_user_modified_file_is_skipped_with_warning(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        custom = _OPENCODE_AGENTS_MD_LEGACY + "\n## My own rules\n"
        agents_md.write_text(custom)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest, base_dir / "backup")

        assert agents_md.read_text() == custom, "user-modified AGENTS.md was clobbered"
        out = capsys.readouterr().out
        assert "user-modified" in out
        assert any("user-modified" in note for note in manifest.get("notes", []))


class TestOpsOneLiner:
    def test_agents_have_ops_oneliner(self, base_dir: Path) -> None:
        """All static agent files should contain the ops: one-liner.

        The installer renders agents from templates now; the static `agents/` set is
        checked at the source until it is folded into templates (ADR-0014 phase 5).
        """
        agents_dir = install.REPO_ROOT / "agents"
        for agent_file in agents_dir.glob("carter-*.md"):
            content = agent_file.read_text()
            assert "ops:" in content, f"{agent_file.name} missing ops: reference"
            assert "carter-ops" in content, f"{agent_file.name} missing carter-ops reference"

    def test_no_critical_section_in_agents(self, base_dir: Path) -> None:
        """Agent files should not have the old CRITICAL section."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents_dir = base_dir / "opencode" / "agents"
        for agent_file in agents_dir.glob("carter-*.md"):
            content = agent_file.read_text()
            assert "## CRITICAL: Write Operations" not in content, (
                f"{agent_file.name} still has CRITICAL section"
            )

    def test_no_deterministic_ops_in_skills(self, base_dir: Path) -> None:
        """Pipeline and atlassian skills should not have deterministic-operations blocks."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        for skill_name in ("carter-pipeline", "carter-atlassian"):
            skill_md = skills_dir / skill_name / "SKILL.md"
            content = skill_md.read_text()
            assert "<deterministic-operations>" not in content, (
                f"{skill_name}/SKILL.md still has deterministic-operations block"
            )


class TestNarratorAgent:
    """ADR-0001: narrator is a first-class, always-installed agent."""

    def test_narrator_installed(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        narrator = base_dir / "opencode" / "agents" / "carter-narrator.md"
        assert narrator.exists()

    def test_narrator_has_all_redaction_categories(self, base_dir: Path) -> None:
        """Static source bakes in redaction ON with all 7 categories (no carter.yaml)."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        content = (base_dir / "opencode" / "agents" / "carter-narrator.md").read_text()
        assert "Redaction Rules — NON-NEGOTIABLE" in content
        for category in (
            "Secrets",
            "Internal URLs",
            "Security Incidents",
            "PII",
            "Financial Figures",
            "Employee Data",
            "Infrastructure IDs",
        ):
            assert category in content, f"narrator missing redaction category: {category}"
        assert "Anti-Bypass Clause" in content

    def test_narrator_references_content_skills(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        content = (base_dir / "opencode" / "agents" / "carter-narrator.md").read_text()
        assert "carter-docs" in content
        assert "carter-story" in content


class TestContentSkills:
    """ADR-0001: carter-docs and carter-story skills with anti-drift delegation."""

    def test_content_skills_installed(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        assert (skills_dir / "carter-docs" / "SKILL.md").exists()
        assert (skills_dir / "carter-story" / "SKILL.md").exists()

    def test_docs_skill_delegates(self, base_dir: Path) -> None:
        """carter-docs must delegate ADRs/diagrams/decks, not duplicate them."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        content = (base_dir / "opencode" / "skills" / "carter-docs" / "SKILL.md").read_text()
        for delegate in ("carter-adr", "carter-diagram", "pptx"):
            assert delegate in content, f"carter-docs missing delegation to {delegate}"
        # Diátaxis + changelog conventions
        assert "Diátaxis" in content
        assert "Keep a Changelog" in content
        assert "Conventional Commits" in content

    def test_brief_register_single_source(self, base_dir: Path) -> None:
        """Brief register is defined in carter-docs and only referenced elsewhere."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        docs = (skills_dir / "carter-docs" / "SKILL.md").read_text()
        assert "Brief Register (canonical definition)" in docs
        # Referencing skills point back to carter-docs rather than redefining it
        for skill_name in ("carter-atlassian", "carter-ops"):
            content = (skills_dir / skill_name / "SKILL.md").read_text()
            assert "Brief register" in content
            assert "carter-docs" in content


class TestTimeAwareness:
    """ADR-0010 D6: agents author dated frontmatter but have a training cutoff, so
    they cannot know today's date unaided. The authoring skills + global
    instructions carry a REQUIRED date-fetch checklist item: obtain the current
    date (native harness var or `date`) BEFORE writing any dated frontmatter. No
    literal date is ever baked into a template (it would be stale + poison caching).
    """

    DATED_SKILLS = ("carter-plan", "carter-rfc", "carter-adr")

    def test_authoring_skills_carry_date_fetch_item(self, repo_root: Path) -> None:
        for skill in self.DATED_SKILLS:
            content = (repo_root / "skills" / skill / "SKILL.md").read_text().lower()
            assert "current date" in content, f"{skill}: missing date-fetch checklist item"
            assert "before writing any dated frontmatter" in content, (
                f"{skill}: date-fetch item must gate dated frontmatter writes"
            )

    def test_workspace_instructions_carry_date_fetch_item(self, repo_root: Path) -> None:
        template = repo_root / "templates" / "instructions" / "AGENTS.md.j2"
        content = template.read_text().lower()
        assert "current date" in content, "global instructions missing date-fetch guidance"
        assert "before writing any dated frontmatter" in content

    def test_no_template_bakes_a_literal_date(self, repo_root: Path) -> None:
        """`Today is <date>` (or any baked literal date) must never appear in a
        template — it is stale the moment it renders and invalidates the cache.
        """
        offenders = []
        for tmpl in (repo_root / "templates").rglob("*.j2"):
            text = tmpl.read_text().lower()
            if "today is" in text:
                offenders.append(tmpl.name)
        assert not offenders, f"templates bake a literal date (ADR-0010 D6): {offenders}"


class TestInstallMemories:
    def test_creates_memory_directories(self, base_dir: Path) -> None:
        """Memory directories should be created under ~/.carter/memories/."""
        manifest = {"files": [], "file_hashes": {}}
        count = install.install_memories(base_dir, manifest)

        memories_dir = base_dir / "carter" / "memories"
        assert (memories_dir / "user").is_dir()
        assert (memories_dir / "session").is_dir()
        assert (memories_dir / "repo").is_dir()
        assert count == 3

    def test_idempotent(self, base_dir: Path) -> None:
        """Second install should report 0 new directories."""
        manifest = {"files": [], "file_hashes": {}}
        install.install_memories(base_dir, manifest)
        manifest2 = {"files": [], "file_hashes": {}}
        count = install.install_memories(base_dir, manifest2)
        assert count == 0

    def test_manifest_tracks_directories(self, base_dir: Path) -> None:
        """All memory directories should be tracked in manifest."""
        manifest = {"files": [], "file_hashes": {}}
        install.install_memories(base_dir, manifest)
        assert len(manifest["files"]) == 3


class TestCarterReflectSkill:
    def test_reflect_skill_installed(self, base_dir: Path) -> None:
        """carter-reflect skill should be installed alongside other skills."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-reflect" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "reflect" in content.lower()
        assert "~/.carter/memories/" in content
        assert "~/.carter/knowledge/" in content

    def test_reflect_skill_opencode(self, base_dir: Path) -> None:
        """carter-reflect skill should be installed for OpenCode target too."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-reflect" / "SKILL.md"
        assert skill_md.exists()


class TestVisibleMemoryReferences:
    def test_opencode_rules_reference_visible_memory(self, base_dir: Path) -> None:
        """OpenCode AGENTS.md should reference ~/.carter/memories/."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_opencode_rules(base_dir, manifest, backup)

        agents_md = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert "~/.carter/memories/" in agents_md
        assert "knowledge" in agents_md

    def test_maestro_has_reflect_skill(self) -> None:
        """The rendered maestro lists carter-reflect."""
        maestro = render_agents(generate_default_config(), create_env())["carter-maestro-local.md"]
        assert "carter-reflect" in maestro
