"""Tests for the Carter installer."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from carter.aplus.handoff import OWN_TERMINAL
from carter.config import generate_default_config
from carter.identity.config import DEFAULT_FOOTER
from carter.install import components, files, mcp, paths
from carter.install import uninstall as uninstall_mod
from carter.install.components import _ATTRIBUTION_RULE, _OPENCODE_AGENTS_MD
from carter.install.files import (
    _install_file,
    _install_rendered_file,
    _sha256,
)
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

    def test_opencode_agents_are_permission_shaped_not_tools_array(self, base_dir: Path) -> None:
        """OpenCode rejects a ``tools:`` ARRAY ("Expected object | undefined, got
        [...]"). Installed agents must carry a V2 ``permissions`` list, a
        ``provider/model`` id, and no ``tools`` key. This guards the regression that
        broke the ``opencode`` CLI on a fresh global install.
        """
        import yaml

        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents = sorted((base_dir / "opencode" / "agents").glob("carter-*.md"))
        assert agents, "no agents installed"
        for agent in agents:
            fm = yaml.safe_load(agent.read_text().split("---")[1])
            assert "tools" not in fm, (
                f"{agent.name}: agent carries a 'tools' key (OpenCode rejects the array)"
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
        assert len(skill_dirs) == 27
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
# MCP server list — single source
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
    """The shipped GitHub MCP server is the official
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

    def _github_cfg(self) -> dict:
        path = install.REPO_ROOT / "mcp" / "opencode" / "github.json"
        return json.loads(path.read_text())["carter-github"]

    def _command_str(self, entry: dict) -> str:
        # opencode shape: command=list (a str command + args list is also accepted).
        cmd = entry["command"]
        parts = [cmd, *entry.get("args", [])] if isinstance(cmd, str) else list(cmd)
        return " ".join(parts)

    def test_no_archived_server_in_shipped_configs(self) -> None:
        configs = sorted((install.REPO_ROOT / "mcp").rglob("*.json"))
        assert configs, "no shipped MCP configs found"
        for cfg in configs:
            assert "@modelcontextprotocol/server-github" not in cfg.read_text(), (
                f"{cfg}: still references the archived GitHub MCP server"
            )

    def test_uses_official_docker_image(self) -> None:
        cmd = self._command_str(self._github_cfg())
        assert "docker" in cmd, "not a docker invocation"
        assert "ghcr.io/github/github-mcp-server@sha256:" in cmd, (
            "official image must be pinned by digest, not a tag"
        )
        assert ":latest" not in cmd, "must not use :latest"

    def test_is_read_only(self) -> None:
        assert "--read-only" in self._command_str(self._github_cfg())

    def test_carries_surgical_tool_allowlist(self) -> None:
        cmd = self._command_str(self._github_cfg())
        assert "--tools" in cmd, "missing --tools allowlist"
        for tool in self.EXPECTED_TOOLS:
            assert tool in cmd, f"surgical tool {tool!r} absent"

    def test_token_is_a_file_placeholder_not_literal_not_env(self) -> None:
        entry = self._github_cfg()
        env = entry.get("env") or entry.get("environment", {})
        # RFC-0007 App C.7: the read-only PAT lives in a 0600 file, never in the environment
        # (an exported GITHUB_TOKEN would also reach agent shells) and never baked in.
        assert env == {"GITHUB_PERSONAL_ACCESS_TOKEN": "{file:~/.carter/secrets/gh-read.token}"}
        assert "{env:" not in str(env) and "github_pat_" not in str(env)


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

    def test_realistic_jsonc_document(self) -> None:
        """Parse a realistic JSONC document mixing comments, nesting and trailing commas."""
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
            "files": ["/some/file.md"],
            "file_hashes": {"/some/file.md": "sha256:abc123"},
            "mcp_servers": ["carter-github"],
        }
        install.write_manifest(manifest, base_dir)
        loaded = install.read_manifest(base_dir)

        assert loaded is not None
        assert loaded["version"] == "1.0.0"
        assert loaded["files"] == ["/some/file.md"]
        assert loaded["mcp_servers"] == ["carter-github"]

    def test_read_manifest_fills_missing_lists(self, base_dir: Path) -> None:
        install.write_manifest({"version": "1.0.0"}, base_dir)
        loaded = install.read_manifest(base_dir)

        assert loaded is not None
        assert loaded["files"] == []
        assert loaded["file_hashes"] == {}
        assert loaded["mcp_servers"] == []

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

    def test_uninstall_leaves_unmanaged_ops_paths(self, base_dir: Path) -> None:
        """Nothing is installed under ~/.carter/ops or ~/.local/bin; uninstall must not
        delete user files there just because of their name."""
        install.write_manifest({"files": [], "file_hashes": {}, "mcp_servers": []}, base_dir)
        ops_file = base_dir / "carter" / "ops" / "mine.txt"
        wrapper = base_dir / "local" / "bin" / "carter-ops"
        for f in (ops_file, wrapper):
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("user\n")

        install.uninstall(base_dir)

        assert ops_file.exists()
        assert wrapper.exists()


class TestInstallPrimitives:
    def test_install_file_updates_with_backup(self, tmp_path: Path) -> None:
        src, dst, backup = tmp_path / "src.md", tmp_path / "out" / "dst.md", tmp_path / "bk"
        src.write_text("new\n")
        dst.parent.mkdir()
        dst.write_text("old\n")
        manifest: dict = {"files": [], "file_hashes": {}}

        assert _install_file(src, dst, manifest, backup) == "updated"
        assert dst.read_text() == "new\n"
        assert (backup / "dst.md").read_text() == "old\n"
        assert manifest["file_hashes"][str(dst)] == _sha256(src)
        assert _install_file(src, dst, manifest, backup) == "unchanged"
        assert manifest["files"] == [str(dst), str(dst)]

    def test_rendered_file_created_then_unchanged(self, tmp_path: Path) -> None:
        dst, manifest = tmp_path / "a" / "x.md", {"files": [], "file_hashes": {}}
        assert _install_rendered_file("hi\n", dst, manifest, tmp_path / "bk") == "created"
        assert manifest["file_hashes"][str(dst)] == _sha256(dst)
        assert _install_rendered_file("hi\n", dst, manifest, tmp_path / "bk") == "unchanged"
        assert not (tmp_path / "bk").exists()


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


SCHEMA1_INSTALLED = (
    "[attribution]\n"
    'name = "carter-bot"\n'
    'email = "carter-bot@users.noreply.github.com"\n'
    'footer = "This comment was generated by carter-bot."\n'
    "\n[git]\n"
    'signing_key = "/home/dev/.ssh/HUMAN_SIGNING_KEY"\n'
)


class TestInstallOps:
    def test_generates_schema_2_config_toml(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        assert install.install_ops(base_dir, manifest) is True

        config = base_dir / "carter" / "config.toml"
        content = config.read_text()
        assert "schema = 2" in content
        assert "[attribution]" in content
        assert "[git]" not in content and "signing_key" not in content
        assert "[jira]" not in content
        assert (config.stat().st_mode & 0o777) == 0o600

    def test_fresh_config_is_t0_without_the_carter_bot_email(self, base_dir: Path) -> None:
        from carter.identity import load_identity, resolve

        install.install_ops(base_dir, {"files": [], "file_hashes": {}})
        config = base_dir / "carter" / "config.toml"

        assert "carter-bot@" not in config.read_text()
        loaded = load_identity(config)
        assert loaded.state == "current"
        assert resolve(loaded, workspace=None, env={}).tier == "t0"

    def test_humans_signing_key_never_reaches_the_file(
        self, base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Hermetic: the fixture HOME/GIT_CONFIG_GLOBAL are temp files, not the developer's.
        import os
        import subprocess

        subprocess.run(
            ["git", "config", "--global", "user.signingkey", "SECRET-HUMAN-KEY-ID"], check=True
        )
        ssh = Path(os.environ["HOME"]) / ".ssh"
        ssh.mkdir()
        (ssh / "id_ed25519").write_text("not-a-real-key")

        install.install_ops(base_dir, {"files": [], "file_hashes": {}})

        content = (base_dir / "carter" / "config.toml").read_text()
        assert "SECRET-HUMAN-KEY-ID" not in content
        assert "id_ed25519" not in content
        assert str(ssh) not in content

    def test_existing_schema_2_config_is_left_byte_identical(self, base_dir: Path) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        text = 'schema = 2\n[attribution]\nfooter = "my footer"\n[extra]\nkeep = 1\n'
        config.write_text(text)

        created = install.install_ops(base_dir, {"files": [], "file_hashes": {}})

        assert created is False
        assert config.read_text() == text

    def test_existing_schema_1_config_is_migrated_with_a_backup(self, base_dir: Path) -> None:
        from carter.identity import load_identity

        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(SCHEMA1_INSTALLED)

        install.install_ops(base_dir, {"files": [], "file_hashes": {}})

        backup = config.with_name("config.toml.schema1.bak")
        assert backup.read_text() == SCHEMA1_INSTALLED
        loaded = load_identity(config)
        assert loaded.state == "current"
        assert loaded.attribution.footer == DEFAULT_FOOTER  # the old default is "unset" (D68 i)
        assert "HUMAN_SIGNING_KEY" not in config.read_text()

    def test_second_install_is_a_no_op(self, base_dir: Path) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(SCHEMA1_INSTALLED)
        install.install_ops(base_dir, {"files": [], "file_hashes": {}})
        before = (config.read_bytes(), config.stat().st_mtime_ns)

        created_again = install.install_ops(base_dir, {"files": [], "file_hashes": {}})

        assert created_again is False
        assert (config.read_bytes(), config.stat().st_mtime_ns) == before
        assert len(list(config.parent.glob("config.toml*"))) == 2

    def test_manifest_tracks_config_but_not_the_backup(self, base_dir: Path) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(SCHEMA1_INSTALLED)
        manifest = {"files": [], "file_hashes": {}}
        install.install_ops(base_dir, manifest)

        assert str(config) in manifest["files"]
        # The backup is the user's safety net: uninstall must never delete it.
        assert not any(f.endswith(".schema1.bak") for f in manifest["files"])

    def test_idempotent(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        install.install_ops(base_dir, manifest)

        manifest2 = {"files": [], "file_hashes": {}}
        created_again = install.install_ops(base_dir, manifest2)

        assert created_again is False

    @pytest.mark.parametrize(
        "broken",
        ['[attribution]\nname = "unterminated\n', "schema = 3\n"],
        ids=["syntax", "future"],
    )
    def test_unmigratable_config_is_reported_and_left_untouched(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str], broken: str
    ) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(broken)
        manifest = {"files": [], "file_hashes": {}}

        changed = install.install_ops(base_dir, manifest)  # must not abort the install

        assert changed is False
        assert config.read_text() == broken
        assert not config.with_name("config.toml.schema1.bak").exists()
        assert "not migrated" in seen(capsys)

    def test_migration_warnings_are_surfaced(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(SCHEMA1_INSTALLED)
        install.install_ops(base_dir, {"files": [], "file_hashes": {}})
        out = capsys.readouterr()
        text = out.out + out.err
        assert "signing_key" in text
        assert "HUMAN_SIGNING_KEY" not in text

    def test_components_no_longer_import_the_humans_key_reader(self) -> None:
        source = Path(components.__file__).read_text(encoding="utf-8")
        assert "git_signing_key" not in source
        assert "signingkey" not in source.lower().replace("signing_key", "")


# ──────────────────────────────────────────────────────────────────────────────
# Bot name (deprecated)
# ──────────────────────────────────────────────────────────────────────────────


class TestBotNameIsIgnored:
    def test_install_ops_has_no_bot_name_input(self) -> None:
        import inspect

        assert "bot_name" not in inspect.signature(install.install_ops).parameters

    def test_config_never_carries_a_bot_name(self, base_dir: Path) -> None:
        install.install_ops(base_dir, {"files": [], "file_hashes": {}})
        content = (base_dir / "carter" / "config.toml").read_text()
        assert 'name = "carter-bot"' not in content
        assert "acme-bot" not in content


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

    def test_carter_ops_skill_is_installed_verbatim(self, base_dir: Path) -> None:
        """No install-time substitution: runtime values come from `carter ops config --emit`."""
        install.install_skills(base_dir, {"files": [], "file_hashes": {}}, base_dir / "backup")

        installed = base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md"
        source = install.REPO_ROOT / "skills" / "carter-ops" / "SKILL.md"
        assert installed.read_bytes() == source.read_bytes()
        assert "{{" not in installed.read_text()

    def test_a_configured_identity_is_not_baked_into_the_skill(self, base_dir: Path) -> None:
        config = base_dir / "carter" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text(
            'schema = 2\n[identity]\nlogin = "llm-bot"\nid = 12345\n'
            'email = "12345+llm-bot@users.noreply.github.com"\n'
            '[attribution]\nfooter = "BAKED-FOOTER-MARK"\n'
        )
        install.install_skills(base_dir, {"files": [], "file_hashes": {}}, base_dir / "backup")

        skill = (base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md").read_text()
        for value in ("llm-bot", "12345", "BAKED-FOOTER-MARK", "users.noreply.github.com"):
            assert value not in skill

    def test_files_module_has_no_templating(self) -> None:
        assert not hasattr(files, "_get_template_vars")
        assert not hasattr(files, "_install_templated_file")

    def test_humans_signing_key_is_not_substituted_into_the_skill(self, base_dir: Path) -> None:
        import os
        import subprocess

        subprocess.run(
            ["git", "config", "--global", "user.signingkey", "SECRET-HUMAN-KEY-ID"], check=True
        )
        ssh = Path(os.environ["HOME"]) / ".ssh"
        ssh.mkdir()
        (ssh / "id_ed25519").write_text("x")
        install.install_skills(base_dir, {"files": [], "file_hashes": {}}, base_dir / "backup")

        skill = (base_dir / "opencode" / "skills" / "carter-ops" / "SKILL.md").read_text()
        assert "SECRET-HUMAN-KEY-ID" not in skill
        assert "id_ed25519" not in skill

    def test_templated_skill_unchanged_on_reinstall(self, base_dir: Path) -> None:
        """A re-install must not rewrite (and back up) the unchanged templated skill."""
        backup = base_dir / "backup"
        install.install_skills(base_dir, {"files": [], "file_hashes": {}}, backup)
        stats = install.install_skills(base_dir, {"files": [], "file_hashes": {}}, backup)
        assert stats["updated"] == 0
        assert not backup.exists()


class TestOpenCodeRules:
    def test_creates_agents_md(self, base_dir: Path) -> None:
        """OpenCode global rules file should be created."""
        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

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
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text("# Custom rules\n")

        install.install_opencode_rules(base_dir, manifest)
        assert agents_md.read_text() == "# Custom rules\n"


class TestOpenCodeRulesUpgrade:
    """``install_opencode_rules`` writes the global rules once and never clobbers
    a file whose content differs from the current text (treated as user-modified).
    """

    def test_fresh_install_has_communication_section(self, base_dir: Path) -> None:
        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

        content = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert "## Communication" in content
        assert "Be concise and clear" in content
        assert "## Memory" in content

    def test_older_rules_text_is_treated_as_user_modified(self, base_dir: Path) -> None:
        """Only the current text is recognized; an older one is never overwritten."""
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        old = _OPENCODE_AGENTS_MD.split("\n## Git & Language", 1)[0] + "\n"
        agents_md.write_text(old)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

        assert agents_md.read_text() == old
        assert str(agents_md) not in manifest["files"]
        assert any("user-modified" in note for note in manifest["notes"])

    def test_current_rules_text_is_left_unchanged(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        agents_md.write_text(_OPENCODE_AGENTS_MD)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert str(agents_md) in manifest["files"]
        assert "notes" not in manifest

    def test_git_language_section_has_core_rules(self) -> None:
        """The global AGENTS.md Git & Language section keeps its core rules."""
        section = _OPENCODE_AGENTS_MD.split("## Git & Language\n", 1)[1].split("\n## ", 1)[0]
        assert "`--author`" in section and "coauthor_trailer" in section
        assert "English" in section
        assert "docs_language" in section

    def test_user_modified_file_is_skipped_with_warning(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True, exist_ok=True)
        custom = _OPENCODE_AGENTS_MD + "\n## My own rules\n"
        agents_md.write_text(custom)

        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

        assert agents_md.read_text() == custom, "user-modified AGENTS.md was clobbered"
        out = seen(capsys)
        assert "user-modified" in out
        assert any("user-modified" in note for note in manifest.get("notes", []))


# The global Git & Language rule as shipped up to v0.16.x (the "known previous version").
_V016_GIT_LANGUAGE = (
    "\n## Git & Language\n"
    "- You (the user) are always the commit author and sign with your own key. Never"
    " pass `--author`; credit Carter only with a trailer:"
    " `Co-authored-by: <name> <email>` from `[attribution]` in"
    " `~/.carter/config.toml` (default `carter-bot <carter-bot@users.noreply.github.com>`).\n"
    "- Everything that lands in a repository or leaves the workspace is written in"
    " English, whatever language the conversation uses: commit messages, branch names,"
    " code comments, repo docs, PR/issue titles and bodies, review comments, release"
    " notes, Jira and Slack text.\n"
    "- Carter's internal docs (ADRs, RFCs, `.carter/` plans/knowledge/checkpoints,"
    " memories) use the workspace `docs_language` from `.carter/carter.yaml`; without"
    " one, English unless the user asks for another language.\n"
    "- Talk to the user in their own language.\n"
)


def _v016_text() -> str:
    head = _OPENCODE_AGENTS_MD.split("\n## Git & Language", 1)[0]
    return head + _V016_GIT_LANGUAGE


def seen(capsys: pytest.CaptureFixture[str]) -> str:
    """Everything printed: warnings go to stderr, results to stdout (D68 a)."""
    got = capsys.readouterr()
    return got.out + got.err


# The push sentence before D68 g: the pinned hashes below are of files that carried it.
OLD_OWN_TERMINAL = (
    "Run `carter push` and then `carter pr` in your own terminal, not through an agent."
)


class TestGlobalAttributionRule:
    """The global AGENTS.md carries the tier-based rule (plan 002 step 17)."""

    def _install(self, base_dir: Path, manifest: dict | None = None, previous=None):
        manifest = manifest if manifest is not None else {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest, previous)
        return manifest

    def test_fresh_install_has_the_new_rule_and_not_the_old_one(self, base_dir: Path) -> None:
        self._install(base_dir)
        text = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert _ATTRIBUTION_RULE in text
        for needed in ("coauthor_trailer", "carter ops config --emit", "Signed-off-by"):
            assert needed in text
        for stale in ("sign with your own key", "carter-bot", "[attribution]"):
            assert stale not in text

    def test_rule_names_every_forbidden_flag_and_the_refusal(self) -> None:
        for flag in ("--author", "--no-verify", "`-s`", "`-S`"):
            assert flag in _ATTRIBUTION_RULE, flag
        assert "`refused`" in _ATTRIBUTION_RULE and "stop" in _ATTRIBUTION_RULE

    def test_rule_is_short(self) -> None:
        assert len(_ATTRIBUTION_RULE) <= 700  # AGENTS.md loads every session (plan 005: +committer)

    def test_the_rule_carries_the_handoff_sentence_and_stays_short(self) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        assert OWN_TERMINAL in _ATTRIBUTION_RULE and "human-only" in _ATTRIBUTION_RULE
        assert len(_ATTRIBUTION_RULE) <= 700  # AGENTS.md loads every session

    def test_a_file_from_before_d68_is_upgraded_in_place(self, base_dir: Path) -> None:
        old_first = (
            "- Commits: the user is the author (their own git config) unless `carter ops config"
            " --emit` says `author` is `llm` (role b: the Carter plugin sets it); the committer is"
            " the user, or the LLM at T2. Never pass `--author`, `--no-verify`, `-s` or `-S`,"
            " never set `GIT_AUTHOR_*` or `GIT_COMMITTER_*`, and never add `Signed-off-by` unless"
            " the user asks. Credit comes only from the `coauthor_trailer` it prints; if"
            " `commits` is `refused`, stop and report.\n"
        )
        before = _OPENCODE_AGENTS_MD.replace(
            _ATTRIBUTION_RULE.splitlines(keepends=True)[0], old_first
        ).replace(OWN_TERMINAL, OLD_OWN_TERMINAL)
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(before)

        self._install(base_dir)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert not (base_dir / "carter" / "upgrade-notes").exists()

    def test_unmodified_v017_file_is_upgraded_in_place(self, base_dir: Path) -> None:
        # v0.17.x shipped the commit rule without the push rule: no user edit, so upgrade.
        first, push_rule = _ATTRIBUTION_RULE.splitlines(keepends=True)[:2]
        old_first = (
            "- Commits: the user is the author and committer (their own git config). Never pass"
            " `--author`, `--no-verify`, `-s` or `-S`, and never add `Signed-off-by` unless the"
            " user asks for it on that commit. Credit comes only from the `coauthor_trailer` that"
            " `carter ops config --emit` prints; if `commits` is `refused`, stop and report.\n"
        )
        v017 = _OPENCODE_AGENTS_MD.replace(first, old_first).replace(push_rule, "")
        assert v017 != _OPENCODE_AGENTS_MD
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(v017)

        manifest = self._install(base_dir)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert str(agents_md) in manifest["files"]
        assert not (base_dir / "carter" / "upgrade-notes").exists()

    def test_unmodified_v018_file_is_upgraded_in_place_to_the_signing_aware_rule(
        self, base_dir: Path
    ) -> None:
        import hashlib

        old_rule = (
            "- Commits: the user is the author and committer (their own git config). Never pass"
            " `--author`, `--no-verify`, `-s` or `-S`, and never add `Signed-off-by` unless the"
            " user asks for it on that commit. Credit comes only from the `coauthor_trailer` that"
            " `carter ops config --emit` prints; if `commits` is `refused`, stop and report.\n"
        )
        v018 = _OPENCODE_AGENTS_MD.replace(
            _ATTRIBUTION_RULE.splitlines(keepends=True)[0], old_rule
        ).replace(OWN_TERMINAL, OLD_OWN_TERMINAL)
        assert (
            hashlib.sha256(v018.encode()).hexdigest()
            == "7aea1b84a6693292380e2c15796dcd33b612e8c2787af40e90b1b3c83f31e0a1"
        )
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(v018)

        self._install(base_dir)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert not (base_dir / "carter" / "upgrade-notes").exists()

    def test_unmodified_2b_file_is_upgraded_in_place_to_the_role_b_aware_rule(
        self, base_dir: Path
    ) -> None:
        """Plan 006: the AGENTS.md text of 2b (author = the user only) is replaced, not kept."""
        import hashlib

        old_first = (
            "- Commits: the user is the author (their own git config); the committer is the user,"
            " or the LLM identity at T2 when the Carter plugin signs for you. Never pass"
            " `--author`, `--no-verify`, `-s` or `-S`, never set `GIT_COMMITTER_*`, and never"
            " add `Signed-off-by` unless the user asks for it on that commit. Credit comes only"
            " from the"
            " `coauthor_trailer` that `carter ops config --emit` prints; if `commits` is `refused`,"
            " stop and report.\n"
        )
        v2b = _OPENCODE_AGENTS_MD.replace(
            _ATTRIBUTION_RULE.splitlines(keepends=True)[0], old_first
        ).replace(OWN_TERMINAL, OLD_OWN_TERMINAL)
        assert (
            hashlib.sha256(v2b.encode()).hexdigest()
            == "15a896f96a1c6e172e66e51c54a1553cac04c8ba0bef913c0cd8072a8144a6c6"
        )
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(v2b)

        self._install(base_dir)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert (
            "role b" in _ATTRIBUTION_RULE and not (base_dir / "carter" / "upgrade-notes").exists()
        )

    def test_a_modified_v017_file_is_kept_and_the_note_has_both_rules(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from carter import __version__
        from carter.aplus.handoff import OWN_TERMINAL

        push_rule = _ATTRIBUTION_RULE.splitlines(keepends=True)[1]
        mine = _OPENCODE_AGENTS_MD.replace(push_rule, "") + "\n## Mine\n"
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(mine)

        self._install(base_dir)

        assert agents_md.read_text() == mine
        printed = capsys.readouterr().out
        note = (base_dir / "carter" / "upgrade-notes" / f"{__version__}.md").read_text()
        for text in (printed, note):
            assert _ATTRIBUTION_RULE in text and OWN_TERMINAL in text

    def test_unmodified_v016_file_is_upgraded_in_place(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(_v016_text())

        manifest = self._install(base_dir)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD
        assert str(agents_md) in manifest["files"]
        assert not (base_dir / "carter" / "upgrade-notes").exists()

    def test_file_matching_the_recorded_manifest_hash_is_upgraded(self, base_dir: Path) -> None:
        from carter.install.ownership import sha256_bytes

        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        older = _OPENCODE_AGENTS_MD.replace("Be concise and clear", "Be brief and clear")
        agents_md.write_text(older)
        previous = {"file_hashes": {str(agents_md): sha256_bytes(older.encode())}}

        self._install(base_dir, previous=previous)

        assert agents_md.read_text() == _OPENCODE_AGENTS_MD

    def test_user_modified_file_is_kept_and_the_note_is_printed_and_written(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from carter import __version__

        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        custom = _v016_text() + "\n## My own rules\n"
        agents_md.write_text(custom)

        self._install(base_dir)

        assert agents_md.read_text() == custom
        out = capsys.readouterr().out
        assert _ATTRIBUTION_RULE in out  # printed
        note = base_dir / "carter" / "upgrade-notes" / f"{__version__}.md"
        assert note.is_file()
        assert _ATTRIBUTION_RULE in note.read_text()  # the same single constant
        assert (note.stat().st_mode & 0o777) == 0o644

    def test_second_install_does_not_duplicate_the_note(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(_v016_text() + "\n## Mine\n")
        self._install(base_dir)
        notes = base_dir / "carter" / "upgrade-notes"
        (first,) = list(notes.iterdir())
        before = (first.read_bytes(), first.stat().st_mtime_ns)
        capsys.readouterr()

        self._install(base_dir)

        assert [p.name for p in notes.iterdir()] == [first.name]
        assert (first.read_bytes(), first.stat().st_mtime_ns) == before
        second_out = seen(capsys)
        assert _ATTRIBUTION_RULE not in second_out  # not repeated, only pointed to
        assert first.name in second_out

    def test_an_unmodified_current_file_needs_no_note(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(_OPENCODE_AGENTS_MD)
        self._install(base_dir)
        assert not (base_dir / "carter" / "upgrade-notes").exists()

    def test_note_write_is_atomic_and_never_blocks_the_install(
        self, base_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import os

        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text(_v016_text() + "\n## Mine\n")
        monkeypatch.setattr(os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))

        self._install(base_dir)  # must not raise

        notes = base_dir / "carter" / "upgrade-notes"
        assert not notes.exists() or list(notes.iterdir()) == []  # no half-written file
        assert _ATTRIBUTION_RULE in capsys.readouterr().out  # still printed

    def test_the_note_is_not_listed_in_the_manifest(self, base_dir: Path) -> None:
        agents_md = base_dir / "opencode" / "AGENTS.md"
        agents_md.parent.mkdir(parents=True)
        agents_md.write_text("# mine\n")
        manifest = self._install(base_dir)
        assert not any("upgrade-notes" in f for f in manifest["files"])


class TestOpsOneLiner:
    def test_no_critical_section_in_agents(self, base_dir: Path) -> None:
        """Agent files should not have the old CRITICAL section."""
        manifest = {"files": [], "file_hashes": {}}
        backup = base_dir / "backup"
        install.install_agents(base_dir, manifest, backup)

        agents = sorted((base_dir / "opencode" / "agents").glob("carter-*.md"))
        assert agents, "no agents installed"
        for agent_file in agents:
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
    """The narrator is a first-class, always-installed agent."""

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
    """carter-docs and carter-story skills with anti-drift delegation."""

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
    """Agents author dated frontmatter but have a training cutoff, so
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
        templates = sorted((repo_root / "templates").rglob("*.j2"))
        assert templates, "no templates found"
        offenders = []
        for tmpl in templates:
            text = tmpl.read_text().lower()
            if "today is" in text:
                offenders.append(tmpl.name)
        assert not offenders, f"templates bake a literal date (stale on render): {offenders}"


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


class TestVisibleMemoryReferences:
    def test_opencode_rules_reference_visible_memory(self, base_dir: Path) -> None:
        """OpenCode AGENTS.md should reference ~/.carter/memories/."""
        manifest = {"files": [], "file_hashes": {}}
        install.install_opencode_rules(base_dir, manifest)

        agents_md = (base_dir / "opencode" / "AGENTS.md").read_text()
        assert "~/.carter/memories/" in agents_md
        assert "knowledge" in agents_md

    def test_maestro_has_reflect_skill(self) -> None:
        """The rendered maestro lists carter-reflect."""
        maestro = render_agents(generate_default_config(), create_env())["carter-maestro-local.md"]
        assert "carter-reflect" in maestro


class TestRetiredSkills:
    """Skills Carter no longer ships are removed only when provably Carter-owned."""

    @staticmethod
    def _seed(base_dir: Path, name: str, record: bool = True) -> tuple[Path, dict]:
        skill = base_dir / "opencode" / "skills" / name
        (skill / "ref").mkdir(parents=True)
        files = [skill / "SKILL.md", skill / "ref" / "notes.md"]
        for f in files:
            f.write_text(f"# {name} {f.name}\n")
        manifest: dict = {"files": [], "file_hashes": {}}
        if record:
            for f in files:
                manifest["files"].append(str(f))
                manifest["file_hashes"][str(f)] = _sha256(f)
        return skill, manifest

    def test_retired_unmodified_skill_is_removed(self, base_dir: Path) -> None:
        skill, previous = self._seed(base_dir, "carter-triage")
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert not skill.exists()

    def test_retired_edited_skill_is_kept_with_warning(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        skill, previous = self._seed(base_dir, "carter-triage")
        (skill / "SKILL.md").write_text("my edits\n")
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert (skill / "SKILL.md").read_text() == "my edits\n"
        out = seen(capsys)
        assert "carter-triage" in out and "rm -r" in out

    def test_retired_skill_without_recorded_hash_is_kept(
        self, base_dir: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        skill, previous = self._seed(base_dir, "carter-triage", record=False)
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert skill.exists()
        assert "carter-triage" in seen(capsys)

    def test_retired_skill_with_extra_user_file_is_kept(self, base_dir: Path) -> None:
        skill, previous = self._seed(base_dir, "carter-triage")
        (skill / "mine.md").write_text("user file\n")
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert (skill / "mine.md").exists()

    def test_no_previous_manifest_keeps_everything(self, base_dir: Path) -> None:
        skill, _ = self._seed(base_dir, "carter-triage")
        components.remove_retired_skills(base_dir, None, base_dir / "backup")
        assert skill.exists()

    def test_non_carter_skill_is_untouched(self, base_dir: Path) -> None:
        skill, previous = self._seed(base_dir, "my-skill")
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert (skill / "SKILL.md").exists()

    def test_current_skill_is_untouched(self, base_dir: Path) -> None:
        skill, previous = self._seed(base_dir, "carter-adr")
        components.remove_retired_skills(base_dir, previous, base_dir / "backup")
        assert (skill / "SKILL.md").exists()
