"""User docs for the parts of slice 1G that exist (plan 003 step 24, partial).

Checked against the code like ``test_docs_slice1.py``: documented options equal ``--help``,
the consent groups equal ``g2_rules.json``, the TOML example loads, and the interim shape is
stated plainly. Pending with the github-token / push / pr steps: their commands, the A+ flow
in ``write-operations.md``, the PAT guide in ``mcp-servers.md`` and the no-``export
GITHUB_TOKEN`` rule.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.identity.policyset import consent_groups

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"


def text(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def section(doc: str, heading: str, level: str = "##") -> str:
    start = doc.index(f"\n{level} {heading}\n")
    rest = doc[start + 1 :]
    nxt = re.search(rf"\n#{{1,{len(level)}}} ", rest[5:])  # next heading of the same or higher rank
    return rest if not nxt else rest[: nxt.start() + 5]


def help_options(*command: str) -> set[str]:
    out = CliRunner().invoke(main, [*command, "--help"]).output
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]+)", out)) - {"--help", "--base-dir"}


def documented(block: str) -> set[str]:
    return set(re.findall(r"`(?:-\w, )?(--[a-z][a-z0-9-]+)", block)) - {"--help", "--base-dir"}


class TestCliReference:
    @pytest.mark.parametrize("sub", ["install", "remove"])
    def test_guard_options_equal_help(self, sub: str) -> None:
        block = section(text("reference/cli.md"), f"carter guard {sub}", "###")
        assert documented(block) == help_options("guard", sub), sub

    def test_guard_status_has_no_options(self) -> None:
        assert help_options("guard", "status") == set()
        assert "carter guard status\n" in section(
            text("reference/cli.md"), "carter guard status", "###"
        )

    def test_every_guard_command_is_listed(self) -> None:
        out = CliRunner().invoke(main, ["guard", "--help"]).output
        doc = text("reference/cli.md")
        for cmd in ("install", "status", "remove"):
            assert cmd in out and f"### carter guard {cmd}" in doc

    def test_check_host_is_documented_as_read_only_and_names_only(self) -> None:
        assert "--host" in help_options("check")
        block = " ".join(section(text("reference/cli.md"), "carter check --host", "###").split())
        assert "never writes" in block and "never prints environment values" in block
        assert "slice 2a" in block

    def test_uninstall_and_install_flags_equal_help(self) -> None:
        doc = text("reference/cli.md")
        assert documented(section(doc, "carter uninstall")) == help_options("uninstall")
        assert documented(section(doc, "carter install")) == help_options("install")

    def test_check_probe_is_not_documented_because_it_is_not_registered(self) -> None:
        assert "--probe" not in help_options("check")
        assert "--probe" not in text("reference/cli.md")


class TestInstallGuide:
    def test_the_consent_groups_listed_are_the_live_ones_in_the_data_file(self) -> None:
        guards = section(text("guides/install.md"), "Guards")
        listed = set(re.findall(r"^\| `([a-z0-9_-]+)` \|", guards, flags=re.M))
        live = {g.id for g in consent_groups() if g.live}
        assert listed == live

    def test_it_explains_yes_non_tty_dry_run_remove_and_restart(self) -> None:
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        for needle in (
            "carter install --yes",
            "skipped with a notice",
            "carter guard install --dry-run",
            "carter guard remove",
            "Restart the OpenCode server",
            "--print-policies",
            "carter uninstall --keep-guards",
            "read-only token file and `~/.carter/state/audit/` stay",
        ):
            assert needle in guards, needle

    def test_the_interim_paragraph_is_honest(self) -> None:
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        assert "speed bump" in guards and "not a boundary" in guards
        assert "plugin and the shell isolation" in guards and "not installed yet" in guards
        assert "agent commits still use your own git config" in guards

    def test_the_restore_story_is_told(self) -> None:
        guards = " ".join(section(text("guides/install.md"), "Guards").split())
        assert "restores the backup" in guards


class TestConfigurationReference:
    def test_the_d52_example_loads_through_the_schema(self, tmp_path: Path) -> None:
        from carter.identity import load_identity

        doc = section(text("reference/configuration.md"), "User config: `~/.carter/config.toml`")
        block = next(
            b
            for b in re.findall(r"```toml\n(.*?)```", doc, flags=re.S)
            if "allow_project_opencode_edit" in b
        )
        data = tomllib.loads(block)
        (path,) = data["workspaces"]
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text("schema = 2\n" + block.replace("/abs/path/to/project", str(tmp_path)))
        loaded = load_identity(cfg_file)
        assert loaded.workspaces[str(tmp_path)].allow_project_opencode_edit is True
        assert path.startswith("/abs")

    def test_it_says_only_a_human_run_apply_turns_it_into_policy(self) -> None:
        doc = " ".join(text("reference/configuration.md").split())
        assert "only when a human runs `carter guard install` or `carter update`" in doc


class TestFilesAndPaths:
    @pytest.mark.parametrize(
        "needle",
        [
            "~/.carter/guard-state.json",
            "~/.carter/backups/<timestamp>/opencode.json[c]",
            "~/.carter/gitconfig",
            "~/.carter/secrets/gh-read.token",
            "~/.carter/state/audit/",
            ".carter/state/handoff/<branch>.md",
        ],
    )
    def test_each_new_path_is_listed(self, needle: str) -> None:
        assert needle in text("reference/files-and-paths.md")

    def test_the_handoff_dir_is_said_to_be_outside_state_snapshots(self) -> None:
        doc = " ".join(text("reference/files-and-paths.md").split())
        assert "Never part of the `.carter/.git` snapshots" in doc

    def test_guard_state_is_0600_and_survives_older_installers(self) -> None:
        row = next(
            ln
            for ln in text("reference/files-and-paths.md").splitlines()
            if ln.startswith("| `~/.carter/guard-state.json`")
        )
        assert "0600" in row and "older installer" in row and "never rebuilt" in row


class TestTroubleshooting:
    @pytest.mark.parametrize(
        "needle",
        [
            "E-POLICIES-MISSING", "E-HUMAN-TERMINAL", "E-STATE-INVALID",
            "Blocked by configuration policy", "opencode.json[c]", "bad config line",
        ],
    )  # fmt: skip
    def test_each_guard_symptom_has_a_row(self, needle: str) -> None:
        assert needle in section(text("troubleshooting.md"), "Guards") or needle in text(
            "troubleshooting.md"
        )

    def test_no_row_still_tells_the_user_devops_pushes(self) -> None:
        assert "Ask Maestro to hand the push to carter-devops" not in text("troubleshooting.md")
