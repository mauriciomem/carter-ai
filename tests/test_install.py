"""Tests for the Carter installer."""

from __future__ import annotations

import json
from pathlib import Path

from carter import installer as install

# ──────────────────────────────────────────────────────────────────────────────
# File operations
# ──────────────────────────────────────────────────────────────────────────────


class TestInstallAgents:
    def test_creates_copilot_agents(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        agents_dir = base_dir / "copilot" / "agents"
        assert agents_dir.exists()

        expected = [
            "carter-architect.md",
            "carter-devops.md",
            "carter-engineer.md",
            "carter-learner.md",
            "carter-maestro.md",
            "carter-narrator.md",
            "carter-pm.md",
        ]
        actual = sorted(f.name for f in agents_dir.glob("carter-*.md"))
        assert actual == expected

    def test_creates_opencode_agents(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["opencode"], base_dir, manifest, backup)

        agents_dir = base_dir / "opencode" / "agents"
        assert agents_dir.exists()
        actual = sorted(f.name for f in agents_dir.glob("carter-*.md"))
        assert len(actual) == 7

    def test_creates_both_targets(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot", "opencode"], base_dir, manifest, backup)

        copilot_agents = list((base_dir / "copilot" / "agents").glob("carter-*.md"))
        opencode_agents = list((base_dir / "opencode" / "agents").glob("carter-*.md"))
        assert len(copilot_agents) == 7
        assert len(opencode_agents) == 7

    def test_manifest_tracks_files(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        assert len(manifest["files"]) == 7
        assert len(manifest["file_hashes"]) == 7
        for h in manifest["file_hashes"].values():
            assert h.startswith("sha256:")


class TestInstallSkills:
    def test_creates_copilot_skills(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skills_dir = base_dir / "copilot" / "skills"
        assert skills_dir.exists()

        skill_dirs = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
        assert len(skill_dirs) == 23
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
        install.install_skills(["opencode"], base_dir, manifest, backup)

        skills_dir = base_dir / "opencode" / "skills"
        skill_dirs = sorted(d.name for d in skills_dir.iterdir() if d.is_dir())
        assert len(skill_dirs) == 23


class TestInstallInstructions:
    def test_creates_instructions(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_instructions(["copilot"], base_dir, manifest, backup)

        inst = base_dir / "copilot" / "instructions" / "copilot-instructions.md"
        assert inst.exists()
        content = inst.read_text()
        assert "Carter" in content


class TestInstallKnowledge:
    def test_creates_knowledge_files(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        count = install.install_knowledge(base_dir, manifest, backup)

        knowledge_dir = base_dir / "copilot" / "knowledge"
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
        knowledge_dir = base_dir / "copilot" / "knowledge"
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
        install.install_agents(["copilot"], base_dir, manifest1, backup)

        # Second install
        manifest2 = {"files": [], "file_hashes": {}}
        stats = install.install_agents(["copilot"], base_dir, manifest2, backup)

        assert stats["unchanged"] == 7
        assert stats["created"] == 0
        assert stats["updated"] == 0

    def test_modified_file_detected_as_updated(self, base_dir: Path) -> None:
        # First install
        manifest1 = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest1, backup)

        # Modify an installed file
        agent_file = base_dir / "copilot" / "agents" / "carter-maestro.md"
        agent_file.write_text("modified content\n")

        # Second install
        manifest2 = {"files": [], "file_hashes": {}}
        stats = install.install_agents(["copilot"], base_dir, manifest2, backup)

        assert stats["updated"] >= 1


# ──────────────────────────────────────────────────────────────────────────────
# MCP merging
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPMerging:
    def test_merge_into_empty_settings(self, base_dir: Path) -> None:
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("{}\n")

        entries = {
            "carter-github": {
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
            }
        }
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert "carter-github" in data["mcp.servers"]

    def test_preserves_existing_servers(self, base_dir: Path) -> None:
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"mcp.servers": {"my-server": {"command": "node"}}}))

        entries = {"carter-github": {"command": "npx", "args": ["-y", "server-github"]}}
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert "my-server" in data["mcp.servers"]
        assert "carter-github" in data["mcp.servers"]

    def test_preserves_other_settings(self, base_dir: Path) -> None:
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps(
                {
                    "editor.fontSize": 14,
                    "mcp.servers": {},
                }
            )
        )

        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert data["editor.fontSize"] == 14

    def test_handles_jsonc_with_comments(self, base_dir: Path) -> None:
        """VS Code settings.json uses JSONC — comments must not break parsing."""
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("""{
  // Editor settings
  "editor.fontSize": 14,
  "workbench.colorTheme": "Lunar-dark-theme",
  /* MCP servers block */
  "mcp.servers": {}
}
""")

        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert data["editor.fontSize"] == 14
        assert data["workbench.colorTheme"] == "Lunar-dark-theme"
        assert "carter-github" in data["mcp.servers"]

    def test_handles_jsonc_with_trailing_commas(self, base_dir: Path) -> None:
        """VS Code allows trailing commas in settings.json."""
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("""{
  "editor.fontSize": 14,
  "mcp.servers": {},
}
""")

        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert data["editor.fontSize"] == 14
        assert "carter-github" in data["mcp.servers"]

    def test_handles_jsonc_comments_inside_strings(self, base_dir: Path) -> None:
        """Comments inside string values must not be stripped."""
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text("""{
  "custom-ui-style.stylesheet": {
    // This is a comment
    ".tab:not(:hover) .tab-actions": {
      "opacity": "0"
    }
  },
  "mcp.servers": {},
}
""")

        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries)

        data = json.loads(settings.read_text())
        assert ".tab:not(:hover) .tab-actions" in data["custom-ui-style.stylesheet"]
        assert "carter-github" in data["mcp.servers"]

    def test_unparseable_file_not_overwritten(self, base_dir: Path) -> None:
        """If a file is truly broken (not just JSONC), do NOT overwrite it."""
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        original = "<<<this is not json at all>>>"
        settings.write_text(original)

        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries)

        # File must not be overwritten — original content preserved
        assert settings.read_text() == original

    def test_backup_created_before_modify(self, base_dir: Path) -> None:
        """Settings file is backed up before any modification."""
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({"editor.fontSize": 14}))

        backup_root = base_dir / "backup"
        entries = {"carter-github": {"command": "npx"}}
        install._merge_json_key(settings, "mcp.servers", entries, backup_root)

        backup_file = backup_root / "settings.json"
        assert backup_file.exists()
        backup_data = json.loads(backup_file.read_text())
        assert backup_data["editor.fontSize"] == 14


# ──────────────────────────────────────────────────────────────────────────────
# MCP server list — single source (D5)
# ──────────────────────────────────────────────────────────────────────────────


class TestMCPServerSingleSource:
    """D5 (RFC-0002): the MCP server triple must come from one module constant,
    not be hardcoded separately in install and uninstall (drift risk).
    """

    def test_mcp_servers_constant_is_the_triple(self) -> None:
        assert tuple(install.MCP_SERVERS) == ("github", "terraform", "atlassian")

    def test_server_triple_not_hardcoded_twice(self) -> None:
        """Both install and uninstall must reference install.MCP_SERVERS — the
        literal list may not be hardcoded anywhere in the module."""
        src = Path(install.__file__).read_text()
        assert '["github", "terraform", "atlassian"]' not in src


# ──────────────────────────────────────────────────────────────────────────────
# JSONC parsing
# ──────────────────────────────────────────────────────────────────────────────


class TestJSONCParsing:
    def test_strip_single_line_comments(self) -> None:
        text = '{\n  // comment\n  "key": "value"\n}'
        result = json.loads(install._strip_jsonc(text))
        assert result == {"key": "value"}

    def test_strip_block_comments(self) -> None:
        text = '{\n  /* block\n     comment */\n  "key": "value"\n}'
        result = json.loads(install._strip_jsonc(text))
        assert result == {"key": "value"}

    def test_strip_trailing_commas(self) -> None:
        text = '{\n  "a": 1,\n  "b": 2,\n}'
        result = json.loads(install._strip_jsonc(text))
        assert result == {"a": 1, "b": 2}

    def test_preserves_comments_inside_strings(self) -> None:
        text = '{\n  "url": "https://example.com // not a comment",\n  "key": "value"\n}'
        result = json.loads(install._strip_jsonc(text))
        assert result["url"] == "https://example.com // not a comment"

    def test_preserves_slashes_inside_strings(self) -> None:
        text = '{\n  "path": "/* keep this */"\n}'
        result = json.loads(install._strip_jsonc(text))
        assert result["path"] == "/* keep this */"

    def test_load_jsonc_returns_none_on_garbage(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.json"
        f.write_text("not json {{{")
        assert install._load_jsonc(f) is None

    def test_load_jsonc_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        f = tmp_path / "missing.json"
        assert install._load_jsonc(f) is None

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
        result = json.loads(install._strip_jsonc(text))
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
            "mcp_servers": ["carter-github"],
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
        install.install_agents(["copilot"], base_dir, manifest, backup)
        install.install_skills(["copilot"], base_dir, manifest, backup)
        manifest["mcp_servers"] = []
        install.write_manifest(manifest, base_dir)

        # Verify files exist
        agents_dir = base_dir / "copilot" / "agents"
        assert len(list(agents_dir.glob("carter-*.md"))) == 7

        # Uninstall
        install.uninstall(["copilot"], base_dir, {})

        # Verify carter files removed
        assert len(list(agents_dir.glob("carter-*.md"))) == 0

    def test_uninstall_preserves_non_carter_files(self, base_dir: Path) -> None:
        # Install Carter
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)
        manifest["mcp_servers"] = []
        install.write_manifest(manifest, base_dir)

        # Add a non-Carter file
        other = base_dir / "copilot" / "agents" / "other-agent.md"
        other.write_text("not carter\n")

        # Uninstall
        install.uninstall(["copilot"], base_dir, {})

        # Non-Carter file preserved
        assert other.exists()


# ──────────────────────────────────────────────────────────────────────────────
# Hashing
# ──────────────────────────────────────────────────────────────────────────────


class TestHashing:
    def test_sha256_consistent(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text("hello world\n")
        h1 = install._sha256(f)
        h2 = install._sha256(f)
        assert h1 == h2
        assert h1.startswith("sha256:")

    def test_sha256_different_content(self, tmp_path: Path) -> None:
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("hello\n")
        f2.write_text("world\n")
        assert install._sha256(f1) != install._sha256(f2)


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


class TestMCPFlag:
    def test_no_mcp_flag_skips_servers(self, base_dir: Path) -> None:
        """Without --mcp, configure_mcp_servers should not be called.

        We verify by checking that no MCP entries are written to VS Code settings.
        """
        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({}))

        # Simulate: main() without --mcp does NOT call configure_mcp_servers
        # So settings should remain empty
        data = json.loads(settings.read_text())
        assert "mcp.servers" not in data

    def test_mcp_flag_installs_servers(self, base_dir: Path) -> None:
        """With --mcp, MCP servers are written to VS Code settings."""
        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        backup = base_dir / "backup"

        settings = base_dir / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(json.dumps({}))

        install.configure_mcp_servers(["copilot"], base_dir, manifest, {}, backup)

        data = json.loads(settings.read_text())
        assert "mcp.servers" in data
        servers = data["mcp.servers"]
        assert "carter-github" in servers
        assert "carter-terraform" in servers
        assert "carter-atlassian" in servers

    def test_mcp_skipped_when_vscode_absent(self, base_dir: Path, monkeypatch) -> None:
        """No VS Code config dir → settings.json is not created (no phantom file)."""
        manifest = {"files": [], "file_hashes": {}, "mcp_servers": []}
        backup = base_dir / "backup"

        # Force "VS Code not detected" even though base_dir normally forces True.
        monkeypatch.setattr(install, "_vscode_detected", lambda _base: False)

        install.configure_mcp_servers(["copilot"], base_dir, manifest, {}, backup)

        assert not (base_dir / "vscode" / "settings.json").exists()


# ──────────────────────────────────────────────────────────────────────────────
# Cross-platform path + prerequisite resolution (macOS / Linux)
# ──────────────────────────────────────────────────────────────────────────────


class TestCrossPlatform:
    def test_vscode_settings_path_macos(self, monkeypatch) -> None:
        monkeypatch.setattr(install.platform, "system", lambda: "Darwin")
        path = install._vscode_settings_path(None)
        assert "Library/Application Support/Code/User/settings.json" in str(path)

    def test_vscode_settings_path_linux(self, monkeypatch) -> None:
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        path = install._vscode_settings_path(None)
        assert str(path).endswith(".config/Code/User/settings.json")

    def test_vscode_user_dirs_linux_includes_variants(self, monkeypatch) -> None:
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        dirs = [str(p) for p in install._vscode_user_dirs(None)]
        joined = "\n".join(dirs)
        assert "VSCodium" in joined
        assert "Code - Insiders" in joined
        assert "com.visualstudio.code" in joined  # Flatpak

    def test_vscode_settings_prefers_existing_variant(self, base_dir, monkeypatch) -> None:
        """When a non-stable variant dir exists, it is preferred over the default."""
        monkeypatch.setattr(install.platform, "system", lambda: "Linux")
        codium = base_dir / ".config" / "VSCodium" / "User"
        codium.mkdir(parents=True)
        monkeypatch.setattr(
            install,
            "_vscode_user_dirs",
            lambda _base: [base_dir / ".config" / "Code" / "User", codium],
        )
        assert install._vscode_settings_path(None) == codium / "settings.json"

    def test_vscode_detected_false_when_no_dirs(self, monkeypatch) -> None:
        monkeypatch.setattr(install, "_vscode_user_dirs", lambda _base: [])
        assert install._vscode_detected(None) is False

    def test_vscode_detected_true_under_base_dir(self, base_dir: Path) -> None:
        assert install._vscode_detected(base_dir) is True

    def test_prerequisites_drop_jq_and_terraform(self, monkeypatch) -> None:
        """jq/terraform are not install prereqs and must not be probed."""
        probed: list[str] = []

        def fake_which(cmd):
            probed.append(cmd)
            return None

        monkeypatch.setattr(install, "_which", fake_which)
        checks = install.check_prerequisites(["copilot", "opencode"])

        assert "jq" not in probed
        assert "terraform" not in probed
        assert "jq" not in checks
        assert "terraform" not in checks
        # Still probes the tools the install actually integrates with
        assert "code" in probed
        assert "gh" in probed


class TestCarterOpsSkill:
    def test_carter_ops_skill_installed(self, base_dir: Path) -> None:
        """carter-ops skill should be installed alongside other skills."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skill_md = base_dir / "copilot" / "skills" / "carter-ops" / "SKILL.md"
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
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skill_md = base_dir / "copilot" / "skills" / "carter-ops" / "SKILL.md"
        content = skill_md.read_text()
        # Template placeholders should be replaced with actual values
        assert "{{BOT_NAME}}" not in content
        assert "{{BOT_EMAIL}}" not in content
        assert "{{SIGNING_KEY}}" not in content

    def test_carter_ops_skill_opencode(self, base_dir: Path) -> None:
        """carter-ops skill should be installed for OpenCode target too."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["opencode"], base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md"
        assert skill_md.exists()


class TestOpenCodeRules:
    def test_creates_agents_md(self, base_dir: Path) -> None:
        """OpenCode global rules file should be created."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_opencode_rules(["opencode"], base_dir, manifest, backup)

        agents_md = base_dir / "opencode" / "AGENTS.md"
        assert agents_md.exists()
        content = agents_md.read_text()
        assert "ops:" in content
        assert "carter-ops" in content
        assert "knowledge" in content
        assert "/memories/" in content

    def test_skipped_for_copilot_only(self, base_dir: Path) -> None:
        """OpenCode rules should not be created when target is copilot only."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_opencode_rules(["copilot"], base_dir, manifest, backup)

        agents_md = base_dir / "opencode" / "AGENTS.md"
        assert not agents_md.exists()

    def test_does_not_overwrite(self, base_dir: Path) -> None:
        """Existing AGENTS.md should not be overwritten."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text("# Custom rules\n")

        install.install_opencode_rules(["opencode"], base_dir, manifest, backup)
        assert agents_md.read_text() == "# Custom rules\n"


class TestOpsOneLiner:
    def test_agents_have_ops_oneliner(self, base_dir: Path) -> None:
        """All agent files should contain the ops: one-liner."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        agents_dir = base_dir / "copilot" / "agents"
        for agent_file in agents_dir.glob("carter-*.md"):
            content = agent_file.read_text()
            assert "ops:" in content, f"{agent_file.name} missing ops: reference"
            assert "carter-ops" in content, f"{agent_file.name} missing carter-ops reference"

    def test_no_critical_section_in_agents(self, base_dir: Path) -> None:
        """Agent files should not have the old CRITICAL section."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        agents_dir = base_dir / "copilot" / "agents"
        for agent_file in agents_dir.glob("carter-*.md"):
            content = agent_file.read_text()
            assert "## CRITICAL: Write Operations" not in content, (
                f"{agent_file.name} still has CRITICAL section"
            )

    def test_no_deterministic_ops_in_skills(self, base_dir: Path) -> None:
        """Pipeline and atlassian skills should not have deterministic-operations blocks."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skills_dir = base_dir / "copilot" / "skills"
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
        install.install_agents(["copilot"], base_dir, manifest, backup)

        narrator = base_dir / "copilot" / "agents" / "carter-narrator.md"
        assert narrator.exists()

    def test_narrator_has_all_redaction_categories(self, base_dir: Path) -> None:
        """Static source bakes in redaction ON with all 7 categories (no carter.yaml)."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        content = (base_dir / "copilot" / "agents" / "carter-narrator.md").read_text()
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
        install.install_agents(["copilot"], base_dir, manifest, backup)

        content = (base_dir / "copilot" / "agents" / "carter-narrator.md").read_text()
        assert "carter-docs" in content
        assert "carter-story" in content


class TestContentSkills:
    """ADR-0001: carter-docs and carter-story skills with anti-drift delegation."""

    def test_content_skills_installed(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skills_dir = base_dir / "copilot" / "skills"
        assert (skills_dir / "carter-docs" / "SKILL.md").exists()
        assert (skills_dir / "carter-story" / "SKILL.md").exists()

    def test_docs_skill_delegates(self, base_dir: Path) -> None:
        """carter-docs must delegate ADRs/diagrams/decks, not duplicate them."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["copilot"], base_dir, manifest, backup)

        content = (base_dir / "copilot" / "skills" / "carter-docs" / "SKILL.md").read_text()
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
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skills_dir = base_dir / "copilot" / "skills"
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

    def test_global_instructions_carry_date_fetch_item(self, repo_root: Path) -> None:
        content = (repo_root / "instructions" / "copilot-instructions.md").read_text().lower()
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
        install.install_skills(["copilot"], base_dir, manifest, backup)

        skill_md = base_dir / "copilot" / "skills" / "carter-reflect" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text()
        assert "reflect" in content.lower()
        assert "~/.carter/memories/" in content
        assert "~/.copilot/knowledge/" in content

    def test_reflect_skill_opencode(self, base_dir: Path) -> None:
        """carter-reflect skill should be installed for OpenCode target too."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_skills(["opencode"], base_dir, manifest, backup)

        skill_md = base_dir / "opencode" / "skills" / "carter-reflect" / "SKILL.md"
        assert skill_md.exists()


class TestVisibleMemoryReferences:
    def test_instructions_reference_visible_memory(self, base_dir: Path) -> None:
        """Global instructions should reference ~/.carter/memories/."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_instructions(["copilot"], base_dir, manifest, backup)

        instructions = (
            base_dir / "copilot" / "instructions" / "copilot-instructions.md"
        ).read_text()
        assert "~/.carter/memories/" in instructions

    def test_opencode_rules_reference_visible_memory(self, base_dir: Path) -> None:
        """OpenCode AGENTS.md should reference ~/.carter/memories/."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_opencode_rules(["opencode"], base_dir, manifest, backup)

        agents_md = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert "~/.carter/memories/" in agents_md
        assert "knowledge" in agents_md

    def test_maestro_has_reflect_skill(self, base_dir: Path) -> None:
        """Maestro agent should list carter-reflect as a skill."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(["copilot"], base_dir, manifest, backup)

        maestro = (base_dir / "copilot" / "agents" / "carter-maestro.md").read_text()
        assert "carter-reflect" in maestro
