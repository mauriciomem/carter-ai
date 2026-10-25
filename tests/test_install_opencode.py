"""OpenCode-only installer behaviour (ADR-0014 phase 3).

Covers the OpenCode >= 2.1 hard gate (D6), the V2 MCP shape, V1 entry migration,
the Copilot-leftover warning (D7) and the removal of ``--target``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.install.mcp import configure_mcp_servers, merge_mcp_servers, to_v2_server
from carter.install.prereqs import PrerequisiteError, parse_opencode_version, require_opencode


def _install(base_dir: Path, *args: str):
    return CliRunner().invoke(main, ["install", "--base-dir", str(base_dir), *args])


class TestParseOpencodeVersion:
    @pytest.mark.parametrize(
        ("output", "expected"),
        [
            ("opencode v2.1.4", (2, 1, 4)),
            ("v2.1.0", (2, 1, 0)),
            ("2.1", (2, 1, 0)),
            ("opencode 2.2.0-beta.1", (2, 2, 0)),
            ("opencode v3.0.0+build.7", (3, 0, 0)),
            ("garbage", None),
            ("", None),
        ],
    )
    def test_parse(self, output: str, expected: tuple[int, int, int] | None) -> None:
        assert parse_opencode_version(output) == expected


class TestRequireOpencode:
    @pytest.mark.parametrize("output", ["opencode v2.1.0", "opencode v2.1.4", "opencode v3.0.0"])
    def test_supported_versions_pass(self, fake_opencode, output: str) -> None:
        fake_opencode(output)
        assert require_opencode() >= (2, 1, 0)

    @pytest.mark.parametrize(
        ("output", "message"),
        [
            (None, "not found"),
            ("opencode v2.0.9", "too old"),
            ("opencode v1.14.2", "too old"),
            ("no version here", "Could not read"),
        ],
    )
    def test_unsupported_fails(self, fake_opencode, output, message: str) -> None:
        fake_opencode(output)
        with pytest.raises(PrerequisiteError, match=message):
            require_opencode()


class TestInstallGate:
    @pytest.mark.parametrize("output", [None, "opencode v2.0.9", "garbage"])
    def test_install_fails_hard_and_writes_nothing(
        self, fake_opencode, tmp_path: Path, output
    ) -> None:
        fake_opencode(output)
        base = tmp_path / "home"
        base.mkdir()
        result = _install(base, "--mcp")
        assert result.exit_code != 0
        assert "Nothing was installed" in result.output
        assert list(base.iterdir()) == []

    @pytest.mark.parametrize("output", ["opencode v2.1.0", "opencode v2.1.4", "opencode v3.0.0"])
    def test_install_succeeds(self, fake_opencode, tmp_path: Path, output: str) -> None:
        fake_opencode(output)
        result = _install(tmp_path / "home", "--mcp")
        assert result.exit_code == 0, result.output
        oc = tmp_path / "home" / "opencode"
        assert len(list((oc / "agents").glob("carter-*.md"))) == 8
        cfg = json.loads((oc / "opencode.json").read_text())
        assert set(cfg["mcp"]["servers"]) == {
            "carter-github",
            "carter-terraform",
            "carter-atlassian",
        }

    def test_nothing_written_to_copilot_locations(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        base = tmp_path / "home"
        assert _install(base, "--mcp").exit_code == 0
        assert not (base / "copilot" / "agents").exists()
        assert not (base / "copilot" / "skills").exists()
        assert not (base / "copilot" / "instructions").exists()
        assert not (base / "vscode").exists()

    def test_target_flag_removed(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        result = _install(tmp_path, "--target", "opencode")
        assert result.exit_code == 2
        assert "No such option" in result.output and "--target" in result.output

    def test_uninstall_flag_removed(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        result = _install(tmp_path, "--uninstall")
        assert result.exit_code == 2
        assert "No such option" in result.output and "--uninstall" in result.output
        assert not (tmp_path / "carter").exists()

    def test_uninstall_does_not_require_opencode(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode(None)
        result = CliRunner().invoke(main, ["uninstall", "--base-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output


class TestV2McpShape:
    def _wire(self, base: Path, servers: list[str] | None = None) -> dict:
        manifest: dict = {}
        configure_mcp_servers(base, manifest, base / "backup", servers=servers)
        return json.loads((base / "opencode" / "opencode.json").read_text())

    def test_servers_live_under_mcp_servers(self, tmp_path: Path) -> None:
        cfg = self._wire(tmp_path)
        assert set(cfg["mcp"]) == {"servers"}
        for entry in cfg["mcp"]["servers"].values():
            assert "enabled" not in entry
            assert not isinstance(entry.get("timeout"), int)

    def test_objective1_fixes_intact(self, tmp_path: Path) -> None:
        servers = self._wire(tmp_path)["mcp"]["servers"]
        gh = servers["carter-github"]
        assert gh["environment"] == {"GITHUB_PERSONAL_ACCESS_TOKEN": "{env:GITHUB_TOKEN}"}
        assert any("ghcr.io/github/github-mcp-server@sha256:" in c for c in gh["command"])
        tf = servers["carter-terraform"]
        assert tf["environment"] == {"TFE_TOKEN": "{env:TFE_TOKEN}"}
        assert any("hashicorp/terraform-mcp-server@sha256:" in c for c in tf["command"])
        assert servers["carter-atlassian"] == {
            "type": "remote",
            "url": "https://mcp.atlassian.com/v2/mcp",
        }

    def test_default_wires_the_shipped_triple(self, tmp_path: Path) -> None:
        """Omitting the selection wires all servers. Per-agent MCP scope lives in agent
        frontmatter, so the global wiring has exactly the server keys, no role keys."""
        manifest: dict = {}
        configure_mcp_servers(tmp_path, manifest, tmp_path / "backup")
        triple = ["carter-github", "carter-terraform", "carter-atlassian"]
        assert manifest["mcp_servers"] == triple
        servers = json.loads((tmp_path / "opencode" / "opencode.json").read_text())["mcp"]
        assert set(servers["servers"]) == set(triple)

    def test_subset_wires_only_selected(self, tmp_path: Path) -> None:
        """An unselected server adds zero tool-schema tokens."""
        manifest: dict = {}
        count = configure_mcp_servers(tmp_path, manifest, servers=["github"])
        assert count == 1
        assert manifest["mcp_servers"] == ["carter-github"]
        assert set(self._wire(tmp_path, ["github"])["mcp"]["servers"]) == {"carter-github"}

    def test_unknown_server_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="bogus"):
            configure_mcp_servers(tmp_path, {}, servers=["bogus"])

    @pytest.mark.parametrize(
        ("v1", "v2"),
        [
            ({"type": "local", "enabled": True}, {"type": "local"}),
            ({"type": "local", "enabled": False}, {"type": "local", "disabled": True}),
            (
                {"type": "local", "timeout": 30000},
                {"type": "local", "timeout": {"catalog": 30000, "execution": 30000}},
            ),
            (
                {"type": "local", "timeout": {"catalog": 5}},
                {"type": "local", "timeout": {"catalog": 5}},
            ),
        ],
    )
    def test_to_v2_server(self, v1: dict, v2: dict) -> None:
        assert to_v2_server(v1) == v2


class TestMergeIntoUserConfig:
    def _cfg(self, tmp_path: Path, content: str) -> Path:
        path = tmp_path / "opencode.json"
        path.write_text(content)
        return path

    def test_preserves_unrelated_keys_and_servers(self, tmp_path: Path) -> None:
        path = self._cfg(
            tmp_path,
            json.dumps(
                {
                    "model": "anthropic/x",
                    "mcp": {
                        "timeout": {"startup": 1000},
                        "servers": {"mine": {"type": "remote", "url": "https://a"}},
                        "legacy-mine": {"type": "local", "command": ["x"]},
                    },
                }
            ),
        )
        merge_mcp_servers(path, {"carter-github": {"type": "local", "command": ["d"]}})
        data = json.loads(path.read_text())
        assert data["model"] == "anthropic/x"
        assert data["mcp"]["timeout"] == {"startup": 1000}
        assert data["mcp"]["legacy-mine"] == {"type": "local", "command": ["x"]}
        assert set(data["mcp"]["servers"]) == {"mine", "carter-github"}

    def test_v1_carter_entry_migrated(self, tmp_path: Path) -> None:
        path = self._cfg(
            tmp_path,
            json.dumps(
                {"mcp": {"carter-github": {"type": "local", "command": ["old"], "enabled": True}}}
            ),
        )
        merge_mcp_servers(path, {"carter-github": {"type": "local", "command": ["new"]}})
        mcp = json.loads(path.read_text())["mcp"]
        assert "carter-github" not in mcp
        assert mcp["servers"]["carter-github"] == {"type": "local", "command": ["new"]}

    def test_jsonc_with_comments_and_trailing_commas(self, tmp_path: Path) -> None:
        path = self._cfg(tmp_path, '{\n  // mine\n  "theme": "x",\n  "mcp": {},\n}\n')
        merge_mcp_servers(path, {"carter-github": {"type": "local", "command": ["d"]}})
        data = json.loads(path.read_text())
        assert data["theme"] == "x"
        assert "carter-github" in data["mcp"]["servers"]

    def test_unparseable_file_untouched(self, tmp_path: Path) -> None:
        path = self._cfg(tmp_path, "<<<not json>>>")
        assert merge_mcp_servers(path, {"carter-github": {}}) is False
        assert path.read_text() == "<<<not json>>>"

    def test_backup_before_modify(self, tmp_path: Path) -> None:
        path = self._cfg(tmp_path, json.dumps({"theme": "x"}))
        merge_mcp_servers(path, {"carter-github": {}}, tmp_path / "backup")
        assert json.loads((tmp_path / "backup" / "opencode.json").read_text()) == {"theme": "x"}


class TestLegacyCopilotWarning:
    def _leftovers(self, base: Path) -> None:
        agents = base / "copilot" / "agents"
        agents.mkdir(parents=True)
        (agents / "carter-engineer.md").write_text("old")
        settings = base / "vscode" / "settings.json"
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({"mcp.servers": {"carter-github": {}}}))
        (base / "copilot" / "mcp-config.json").write_text(
            json.dumps({"mcpServers": {"carter-terraform": {}}})
        )

    def test_warns_once_and_deletes_nothing(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        base = tmp_path / "home"
        self._leftovers(base)
        result = _install(base, "--mcp")
        assert result.exit_code == 0, result.output
        assert result.output.count("no longer managed") == 1
        assert "carter uninstall --legacy" in result.output
        assert (base / "copilot" / "agents" / "carter-engineer.md").read_text() == "old"
        assert (
            "carter-github"
            in json.loads((base / "vscode" / "settings.json").read_text())["mcp.servers"]
        )
        assert (base / "copilot" / "mcp-config.json").exists()

    def test_no_warning_on_clean_home(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        result = _install(tmp_path / "home")
        assert result.exit_code == 0, result.output
        assert "no longer managed" not in result.output


class TestUninstallV2:
    def test_removes_v1_and_v2_carter_entries_only(self, fake_opencode, tmp_path: Path) -> None:
        fake_opencode()
        base = tmp_path / "home"
        assert _install(base, "--mcp").exit_code == 0
        cfg = base / "opencode" / "opencode.json"
        data = json.loads(cfg.read_text())
        data["mcp"]["carter-old"] = {"type": "local", "command": ["x"]}
        data["mcp"]["servers"]["mine"] = {"type": "remote", "url": "https://a"}
        cfg.write_text(json.dumps(data))

        assert CliRunner().invoke(main, ["uninstall", "--base-dir", str(base)]).exit_code == 0
        mcp = json.loads(cfg.read_text())["mcp"]
        assert mcp == {"servers": {"mine": {"type": "remote", "url": "https://a"}}}
        assert not list((base / "opencode" / "agents").glob("carter-*.md"))
