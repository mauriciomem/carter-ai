"""Carter state migration ``~/.copilot`` → ``~/.carter`` and ``uninstall --legacy``.

ADR-0014 D3 (copy-only, idempotent, content-compared migration) and D7
(``carter uninstall --legacy`` removes only manifest-listed Carter files).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from click.testing import CliRunner

from carter.cli import main
from carter.install.components import read_manifest
from carter.install.migrate import migrate_copilot_state


def _h(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()


def _seed_old_install(base: Path, *, hashes: bool = True) -> dict:
    """Lay out what a pre-ADR-0014 Carter install left under ``base``."""
    cop = base / "copilot"
    (cop / "knowledge").mkdir(parents=True)
    (cop / "knowledge" / "mistakes.md").write_text("# my mistakes\n")
    (cop / "knowledge" / "decisions.md").write_text("# my decisions\n")
    (cop / "backup" / "20250101T000000").mkdir(parents=True)
    (cop / "backup" / "20250101T000000" / "settings.json").write_text("{}\n")

    agent = cop / "agents" / "carter-engineer.md"
    edited_agent = cop / "agents" / "carter-pm.md"
    user_agent = cop / "agents" / "my-agent.md"
    skill = cop / "skills" / "carter-adr" / "SKILL.md"
    instructions = cop / "instructions" / "copilot-instructions.md"
    for p, text in [
        (agent, "engineer\n"),
        (edited_agent, "pm\n"),
        (user_agent, "mine\n"),
        (skill, "adr\n"),
        (instructions, "instr\n"),
    ]:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    listed = [agent, edited_agent, skill, instructions]
    file_hashes = {str(agent): _h("engineer\n"), str(edited_agent): _h("pm original\n")}
    # Templated files were recorded without the "sha256:" prefix.
    file_hashes[str(skill)] = hashlib.sha256(b"adr\n").hexdigest()
    file_hashes[str(instructions)] = _h("instr\n")

    (cop / "mcp-config.json").write_text(
        json.dumps({"mcpServers": {"carter-github": {"x": 1}, "my-server": {"y": 2}}})
    )
    settings = base / "vscode" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "editor.fontSize": 14,
                "mcp.servers": {"carter-github": {}, "carter-terraform": {}, "user-mcp": {}},
            }
        )
    )
    manifest = {
        "version": "0.9.0",
        "installed_at": "2025-01-01T00:00:00+00:00",
        "targets": ["copilot", "opencode"],
        "files": [str(p) for p in listed] + [str(cop / "knowledge" / "mistakes.md")],
        "mcp_servers": {"copilot": ["carter-github", "carter-terraform"], "opencode": []},
        "file_hashes": file_hashes if hashes else {},
    }
    (cop / ".carter-manifest.json").write_text(json.dumps(manifest))
    return manifest


def _run(*args: str):
    return CliRunner().invoke(main, list(args))


class TestMigration:
    def test_copies_knowledge_manifest_and_backups(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        migrate_copilot_state(tmp_path)
        carter = tmp_path / "carter"
        assert (carter / "knowledge" / "mistakes.md").read_text() == "# my mistakes\n"
        assert (carter / "knowledge" / "decisions.md").read_text() == "# my decisions\n"
        assert (carter / "backups" / "20250101T000000" / "settings.json").read_text() == "{}\n"
        assert (carter / "manifest.json").is_file()
        # Sources are never deleted.
        assert (tmp_path / "copilot" / "knowledge" / "mistakes.md").is_file()
        assert (tmp_path / "copilot" / ".carter-manifest.json").is_file()

    def test_second_run_is_noop(self, tmp_path: Path, capsys) -> None:
        _seed_old_install(tmp_path)
        migrate_copilot_state(tmp_path)
        capsys.readouterr()
        assert migrate_copilot_state(tmp_path).copied == []
        assert capsys.readouterr().out == ""

    def test_identical_destination_is_skipped(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        dst = tmp_path / "carter" / "knowledge" / "mistakes.md"
        dst.parent.mkdir(parents=True)
        dst.write_text("# my mistakes\n")
        result = migrate_copilot_state(tmp_path)
        assert dst not in result.copied
        assert result.conflicts == []

    def test_conflicting_destination_kept_and_warned(self, tmp_path: Path, capsys) -> None:
        _seed_old_install(tmp_path)
        dst = tmp_path / "carter" / "knowledge" / "mistakes.md"
        dst.parent.mkdir(parents=True)
        dst.write_text("# newer\n")
        result = migrate_copilot_state(tmp_path)
        assert dst.read_text() == "# newer\n"
        assert result.conflicts == [dst]
        out = capsys.readouterr().out
        assert "mistakes.md" in out

    def test_no_copilot_dir_does_nothing(self, tmp_path: Path) -> None:
        result = migrate_copilot_state(tmp_path)
        assert result.copied == [] and result.conflicts == []
        assert not (tmp_path / "carter").exists()

    def test_old_manifest_shape_is_read(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        migrate_copilot_state(tmp_path)
        manifest = read_manifest(tmp_path)
        assert manifest is not None
        assert manifest["mcp_servers"] == ["carter-github", "carter-terraform"]


class TestInstallMigrates:
    def test_install_twice(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        _seed_old_install(tmp_path)
        first = _run("install", "--base-dir", str(tmp_path))
        assert first.exit_code == 0, first.output
        assert "Migrated" in first.output
        carter = tmp_path / "carter"
        assert (carter / "knowledge" / "mistakes.md").read_text() == "# my mistakes\n"
        manifest = json.loads((carter / "manifest.json").read_text())
        assert manifest["targets"] == ["opencode"]
        # Nothing new is written under ~/.copilot.
        assert [p.name for p in (tmp_path / "copilot" / "backup").iterdir()] == ["20250101T000000"]
        second = _run("install", "--base-dir", str(tmp_path))
        assert second.exit_code == 0, second.output
        assert "Migrated" not in second.output
        assert "not overwritten" not in second.output

    def test_new_backups_and_manifest_under_carter(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        result = _run("install", "--base-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        assert (tmp_path / "carter" / "manifest.json").is_file()
        assert (tmp_path / "carter" / "knowledge" / "mistakes.md").is_file()
        assert not (tmp_path / "copilot").exists()


class TestUninstallLegacy:
    def test_removes_only_listed_unedited_carter_files(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        result = _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        cop = tmp_path / "copilot"
        assert not (cop / "agents" / "carter-engineer.md").exists()
        assert not (cop / "skills" / "carter-adr").exists()
        assert not (cop / "instructions" / "copilot-instructions.md").exists()
        # Edited since install → kept, warned.
        assert (cop / "agents" / "carter-pm.md").read_text() == "pm\n"
        assert "carter-pm.md" in result.output
        # Not listed → untouched.
        assert (cop / "agents" / "my-agent.md").is_file()
        # Knowledge is state, not a Copilot install artefact.
        assert (cop / "knowledge" / "mistakes.md").is_file()
        assert (cop / ".carter-manifest.json").is_file()

    def test_mcp_and_vscode_entries(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        mcp = json.loads((tmp_path / "copilot" / "mcp-config.json").read_text())
        assert mcp["mcpServers"] == {"my-server": {"y": 2}}
        settings = json.loads((tmp_path / "vscode" / "settings.json").read_text())
        assert settings["mcp.servers"] == {"user-mcp": {}}
        assert settings["editor.fontSize"] == 14

    def test_without_hashes_only_carter_named(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path, hashes=False)
        result = _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        cop = tmp_path / "copilot"
        assert not (cop / "agents" / "carter-engineer.md").exists()
        assert not (cop / "agents" / "carter-pm.md").exists()
        assert (cop / "instructions" / "copilot-instructions.md").is_file()
        assert "no content hashes" in result.output

    def test_without_manifest_deletes_nothing(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        (tmp_path / "copilot" / ".carter-manifest.json").unlink()
        before = sorted(p for p in tmp_path.rglob("*"))
        result = _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        assert result.exit_code == 0, result.output
        assert sorted(p for p in tmp_path.rglob("*")) == before
        assert "Nothing was deleted" in result.output
        assert "agents" in result.output

    def test_is_idempotent(self, tmp_path: Path) -> None:
        _seed_old_install(tmp_path)
        _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        again = _run("uninstall", "--legacy", "--base-dir", str(tmp_path))
        assert again.exit_code == 0, again.output
        assert (tmp_path / "copilot" / "agents" / "my-agent.md").is_file()
