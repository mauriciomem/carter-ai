"""The whole promise in one place: after ``carter uninstall``, Carter leaves nothing behind
except what its report says it keeps.

Hermetic: HOME and the XDG directories are the suite's temp tree and OpenCode is the fake one.
The commands run through the CLI as a user types them (no ``--base-dir``), so the real path
resolution is what is under test. The CI ``lifecycle`` job runs this directory on Linux and
macOS; the home is resolved once (macOS temp dirs sit behind ``/private`` symlinks), paths
are compared relative to it, and no two names differ only by case.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter.cli import main
from carter.install.backups import STAMP_FORMAT
from guard.helpers import agents_json, all_live_statements, debug_config
from host_guard import changed, digest_host
from lifecycle.helpers import Snapshot, tree_diff, tree_snapshot

REAL_GIT = shutil.which("git") or "/usr/bin/git"
STAMP = re.compile(r"\d{8}T\d{6}")
USER_JSON = {
    "mcp": {"servers": {"mine": {"type": "local", "command": ["my-server"]}}},
    "theme": "x",
}


@dataclass
class Life:
    """A home after install, init, update, a second install and the user's own edits."""

    home: Path
    workspace: Path
    outside: Path  # the working directory: nothing in it may change
    before: Snapshot  # the home as the user left it, before Carter ever ran
    outside_before: Snapshot
    real_before: dict[str, str]  # hashes of the developer's real host files
    after_install: Snapshot | None = None
    workspace_before: Snapshot | None = None

    @property
    def carter(self) -> Path:
        return self.home / ".carter"

    @property
    def opencode(self) -> Path:
        return self.home / ".config" / "opencode"

    @property
    def edited_skill(self) -> Path:
        return self.opencode / "skills" / "carter-code-review" / "SKILL.md"

    def run(self, *args: str) -> Result:
        result = CliRunner().invoke(main, list(args))
        assert result.exit_code == 0, result.output
        return result

    def uninstall(self) -> str:
        self.workspace_before = tree_snapshot(self.workspace)
        return self.run("uninstall", "--yes").output

    def edit_skill(self) -> None:
        self.edited_skill.write_text(
            self.edited_skill.read_text() + "\nmy rule\n", encoding="utf-8"
        )


def _seed(home: Path, outside: Path) -> None:
    """What a user has before Carter: notes, a token, an audit log, a skill, an agent, a JSON
    config with an MCP server of their own, a backup folder of an old layout and a stale one."""
    files = {
        home / ".carter" / "memories" / "user" / "me.md": "my notes\n",
        home / ".carter" / "secrets" / "gh-read.token": "not-a-real-token\n",
        home / ".carter" / "state" / "audit" / "ops.log": "one line\n",
        home / ".carter" / "backups" / "agents" / "legacy.md": "from an old layout\n",
        home / ".config" / "opencode" / "skills" / "carter-mine" / "SKILL.md": "my skill\n",
        home / ".config" / "opencode" / "agents" / "my-agent.md": "my agent\n",
        home / ".config" / "opencode" / "opencode.json": json.dumps(USER_JSON, indent=2) + "\n",
        outside / "canary.txt": "do not touch\n",
    }
    stale = (datetime.now(UTC) - timedelta(days=20)).strftime(STAMP_FORMAT)  # past retention
    files[home / ".carter" / "backups" / stale / "old.txt"] = "old backup\n"
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def life(tmp_path: Path, fake_opencode, monkeypatch: pytest.MonkeyPatch, real_home: Path) -> Life:
    home = Path.home().resolve()
    bindir = fake_opencode(
        agents_output=agents_json("build", "plan", "carter-engineer"),
        config_sequence=[debug_config(), debug_config(all_live_statements(str(home)))],
    )
    (bindir / "git").symlink_to(REAL_GIT)  # PATH holds only fakes; init and the guards need git
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.chdir(outside)
    workspace = home / "work" / "proj"
    workspace.mkdir(parents=True)
    _seed(home, outside)
    lived = Life(
        home,
        workspace,
        outside,
        tree_snapshot(home),
        tree_snapshot(outside),
        digest_host(real_home),
    )

    lived.run("install", "--yes", "--mcp")
    lived.run("init", str(workspace))
    lived.run("update", str(workspace))
    lived.after_install = tree_snapshot(home)
    lived.run("install", "--yes")
    # Nothing duplicated and no new backup: only the manifest is rewritten (new timestamp).
    assert tree_diff(lived.after_install, tree_snapshot(home)) == "~ .carter/manifest.json"
    # What the user does while living with it (an edited skill is added by the tests that need it).
    (lived.opencode / "agents" / "carter-pm.md").write_text("# my pm\n", encoding="utf-8")
    (lived.carter / "knowledge" / "patterns.md").write_text("my pattern\n", encoding="utf-8")
    (lived.carter / "memories" / "user" / "later.md").write_text("later\n", encoding="utf-8")
    return lived


def _backups(home: Path) -> set[str]:
    """Backup files by path under ``backups/``, the timestamp folder shown as ``<ts>``."""
    root = home / ".carter" / "backups"
    return {
        STAMP.sub("<ts>", p.relative_to(root).as_posix()) for p in root.rglob("*") if p.is_file()
    }


def test_install_prunes_old_backups_but_not_a_legacy_folder(life: Life) -> None:
    assert not any("old.txt" in b for b in _backups(life.home))
    assert (life.carter / "backups" / "agents" / "legacy.md").read_text() == "from an old layout\n"


def test_uninstall_leaves_only_what_the_user_owns(life: Life) -> None:
    life.edit_skill()
    report = life.uninstall()
    after = tree_snapshot(life.home)
    # Not the workspace (its own test) and not the backups (their folders are named by time).
    diff = [
        line
        for line in tree_diff(life.before, after).splitlines()
        if not line[2:].startswith(("work/", ".carter/backups/"))
    ]
    assert diff == [  # everything Carter put there and the user did not touch is gone
        "+ .carter/knowledge",  # the edited knowledge file stays, the other five seeds go
        "+ .carter/knowledge/patterns.md",
        "+ .carter/memories/user/later.md",  # a note the user added
        "+ .config/opencode/skills/carter-code-review",  # an edited skill may hold work
        "+ .config/opencode/skills/carter-code-review/SKILL.md",
    ]
    # What the user had before is byte for byte what it was (including the git config).
    for rel in life.before:
        if not rel.startswith(("work/", ".carter/backups/")):
            assert after[rel] == life.before[rel], rel
    # Carter's own files are gone, and so is the directory it kept them in.
    assert not (life.carter / "manifest.json").exists()
    assert not (life.opencode / "plugins").exists() and not (life.opencode / "AGENTS.md").exists()
    assert not list((life.opencode / "agents").glob("carter-*"))
    assert sorted(p.name for p in life.carter.iterdir()) == [
        "backups",
        "knowledge",
        "memories",
        "secrets",
        "state",
    ]
    # The report names each thing that stayed.
    for kept in ("memories/", "knowledge/", "state/audit/", "secrets/", "backups/"):
        assert f"~/.carter/{kept}" in report, kept
    assert "~/.config/opencode/skills/carter-code-review/SKILL.md" in report


def test_the_user_mcp_server_stays_and_the_carter_ones_go(life: Life) -> None:
    config = life.opencode / "opencode.json"
    assert "carter-github" in json.loads(config.read_text(encoding="utf-8"))["mcp"]["servers"]
    life.uninstall()
    assert json.loads(config.read_text(encoding="utf-8")) == USER_JSON


def test_an_edited_global_agent_goes_with_a_mirrored_copy_in_backups(life: Life) -> None:
    report = life.uninstall()
    agent = life.opencode / "agents" / "carter-pm.md"
    mirrored = agent.relative_to(life.home).as_posix()  # backups/<ts>/<path below the home>
    assert not agent.exists()
    # The guard step may leave a second copy of the same edit under the next second's stamp.
    copies = list((life.carter / "backups").glob(f"*/{mirrored}"))
    assert copies and {c.read_text(encoding="utf-8") for c in copies} == {"# my pm\n"}
    assert f"~/{mirrored}" in report and "Removed although you edited them" in report
    assert _backups(life.home) >= {f"<ts>/{mirrored}", "<ts>/opencode.json", "agents/legacy.md"}


def test_the_workspace_is_untouched_and_listed_with_a_safe_rm_line(life: Life) -> None:
    report = life.uninstall()
    assert tree_snapshot(life.workspace) == life.workspace_before
    assert "Workspaces, not touched" in report and "~/work/proj" in report
    [rm] = re.findall(r"\brm (\S+/carter-\*\.md)$", report, re.MULTILINE)
    # The line is read, never run: it can only name this workspace's own agent files.
    assert shlex.split(rm) == [f"{life.workspace}/.opencode/agents/carter-*.md"]
    assert list(life.workspace.glob(".opencode/agents/carter-*.md"))
    assert ".carter/" in report and "AGENTS.md" in report  # named, as the user's to delete


def test_config_toml_goes_when_default_and_stays_when_it_holds_a_value(life: Life) -> None:
    config = life.carter / "config.toml"
    assert config.read_text(encoding="utf-8").count("\n") == 2  # a fresh one is two lines
    life.uninstall()
    assert not config.exists()


def test_config_toml_with_a_setting_is_kept_and_listed(life: Life) -> None:
    config = life.carter / "config.toml"
    config.write_text("schema = 2\n[broker]\nmin_dwell_ms = 800\n", encoding="utf-8")
    report = life.uninstall()
    assert "min_dwell_ms = 800" in config.read_text(encoding="utf-8")
    assert "~/.carter/config.toml" in report and "settings you changed" in report


def test_a_second_uninstall_does_nothing(life: Life) -> None:
    life.uninstall()
    done = tree_snapshot(life.home)
    life.uninstall()
    assert tree_diff(done, tree_snapshot(life.home)) == ""


def test_a_second_uninstall_keeps_an_edited_skill_and_still_says_so(life: Life) -> None:
    """The first run deletes the manifest; the second removes shipped names only while the
    content is still what this version ships."""
    life.edit_skill()
    life.uninstall()
    done = tree_snapshot(life.home)
    report = life.uninstall()
    assert life.edited_skill.read_text(encoding="utf-8").endswith("my rule\n")
    assert tree_diff(done, tree_snapshot(life.home)) == ""
    assert "~/.config/opencode/skills/carter-code-review/SKILL.md" in report


def test_without_a_manifest_the_unedited_guarded_agents_go_and_the_edited_one_stays(
    life: Life,
) -> None:
    """The agents carry the guard rules; they are rendered before the guards are removed."""
    (life.carter / "manifest.json").unlink()
    life.uninstall()
    assert [p.name for p in (life.opencode / "agents").glob("carter-*")] == ["carter-pm.md"]
    assert (life.opencode / "agents" / "carter-pm.md").read_text(encoding="utf-8") == "# my pm\n"


def test_nothing_outside_the_fake_home_was_touched(life: Life, real_home: Path) -> None:
    life.uninstall()
    assert tree_snapshot(life.outside) == life.outside_before  # the working directory
    assert not changed(life.real_before, digest_host(real_home))  # the developer's real files
