"""``guard remove`` after the plugin, and ``remove --only plugin`` (plan 004 step 28; freeze G12).

The escape hatch of the live install: a precise, human-run rollback of the plugin that keeps the
1G denies, the hooks and the PAT, and an uninstall that restores everything Carter added.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard.state import load
from carter.install.mcp import config_target
from carter.install.paths import (
    carter_gitconfig_path,
    guard_script_path,
    guard_state_path,
    isolation_path,
    plugin_dir,
    run_dir,
    token_path,
)
from guard.helpers import debug_config, tree_hash, verbose


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def install(stack) -> None:
    stack.fake()
    res = guard("install", "--yes")
    assert res.exit_code == 0, res.output


def reload(stack, after=None) -> None:
    stack.fake(
        before=debug_config(stack.live), after=debug_config(stack.live) if after is None else after
    )


def plugin_files() -> list[Path]:
    return [isolation_path(None), plugin_dir(None) / "index.ts", plugin_dir(None) / "core.ts"]


class TestRoundTrip:
    def test_install_then_remove_restores_every_touched_file(self, stack, home: Path) -> None:
        before = tree_hash(home, skip=("backups",))
        git_before = Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes()
        install(stack)
        assert all(p.exists() for p in plugin_files()) and guard_script_path(None).exists()
        reload(stack, after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        after = tree_hash(home, skip=("backups",))
        diff = {k for k in {*before, *after} if before.get(k) != after.get(k)}
        assert diff <= {".config/opencode/opencode.json"}, diff  # the config, minus our statements
        assert config_target(None).read_text().strip() == "{}"
        assert Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes() == git_before
        assert not run_dir(None).exists() and not plugin_dir(None).parent.exists()

    def test_the_order_is_the_documented_one(self, stack) -> None:
        install(stack)
        reload(stack, after=debug_config())
        out = guard("remove", "--yes").output
        marks = [
            "- build:carter_push",
            f"removed {plugin_dir(None) / 'index.ts'}",
            "removed",
            "Removed guard state",
        ]
        positions = [out.index(m) for m in marks]
        assert positions == sorted(positions)
        assert out.index(f"removed {isolation_path(None)}") < out.index(
            f"removed {guard_script_path(None)}"
        )

    def test_the_pat_and_the_audit_dir_stay(self, stack, home: Path) -> None:
        install(stack)
        token_path(None).parent.mkdir(parents=True, exist_ok=True)
        token_path(None).write_text("not-a-real-token")
        audit = home / ".carter" / "state" / "audit"
        audit.mkdir(parents=True)
        (audit / "x.jsonl").write_text("{}")
        reload(stack, after=debug_config())
        out = guard("remove", "--yes").output
        assert token_path(None).exists() and (audit / "x.jsonl").exists()
        assert "gh-read.token` kept" in out and "not-a-real-token" not in out


class TestOnlyPlugin:
    def test_it_removes_the_plugin_side_and_keeps_everything_else(self, stack) -> None:
        install(stack)
        before = load(guard_state_path(None))
        config = config_target(None).read_bytes()
        reload(stack)
        res = guard("remove", "--yes", "--only", "plugin")
        assert res.exit_code == 0, res.output
        assert not any(p.exists() for p in plugin_files()) and not run_dir(None).exists()
        assert "OpenCode unloads it within seconds" in res.output
        state = load(guard_state_path(None))
        assert state.consents["g2"]["decision"] == "accepted" and state.consents["g2"]["rev"] == 1
        assert state.opencode_policies == before.opencode_policies  # the 1G denies stay
        assert state.agent_permissions == before.agent_permissions
        assert config_target(None).read_bytes() == config  # not even rewritten
        assert guard_script_path(None).exists() and carter_gitconfig_path(None).exists()
        assert state.gitconfig == before.gitconfig and "hooks" in state.consents
        assert not [
            f for f in state.files if "plugins" in f["path"] or f["path"].endswith("isolation.json")
        ]

    def test_a_bare_yes_never_brings_it_back_but_only_g2_does(self, stack) -> None:
        install(stack)
        reload(stack)
        guard("remove", "--yes", "--only", "plugin")
        reload(stack)
        res = guard("install", "--yes")
        assert not isolation_path(None).exists() and "need your confirmation" in res.output
        reload(stack)
        assert guard("install", "--yes", "--only", "g2").exit_code == 0
        assert all(p.exists() for p in plugin_files())
        assert load(guard_state_path(None)).consents["g2"]["rev"] == 3

    def test_a_dry_run_changes_nothing(self, stack, home: Path) -> None:
        install(stack)
        before = tree_hash(home, skip=("backups",))
        res = guard("remove", "--dry-run", "--only", "plugin")
        assert res.exit_code == 0 and "would remove" in res.output
        assert tree_hash(home, skip=("backups",)) == before

    def test_it_asks_nothing_and_needs_no_terminal(self, stack, human_tty) -> None:
        install(stack)
        human_tty(False)  # D68 h
        res = guard("remove", "--only", "plugin")
        assert res.exit_code == 0 and not any(p.exists() for p in plugin_files())

    def test_an_agent_shell_is_refused(self, stack, monkeypatch: pytest.MonkeyPatch) -> None:
        install(stack)
        monkeypatch.setenv("AGENT", "1")
        res = guard("remove", "--yes", "--only", "plugin")
        assert res.exit_code == 1 and "E-HUMAN-TERMINAL" in res.output
        assert all(p.exists() for p in plugin_files())

    def test_install_does_not_accept_it(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes", "--only", "plugin")
        assert res.exit_code == 2 and "use `--only g2`" in res.output

    def test_plugin_can_be_combined_with_groups(self, stack) -> None:
        install(stack)
        reload(stack)
        res = guard("remove", "--yes", "--only", "plugin,sudo-docker")
        assert res.exit_code == 0, res.output
        assert not isolation_path(None).exists()
        assert "sudo-docker" not in load(guard_state_path(None)).consents

    def test_removing_g2_removes_its_plugin_too(self, stack) -> None:
        install(stack)
        reload(stack)
        assert guard("remove", "--yes", "--only", "g2").exit_code == 0
        assert not any(p.exists() for p in plugin_files())


class TestEdited:
    def test_an_edited_plugin_file_is_kept_and_the_rm_line_printed(self, stack) -> None:
        install(stack)
        index = plugin_dir(None) / "index.ts"
        index.write_text(index.read_text() + "// mine\n")
        reload(stack)
        out = guard("remove", "--yes", "--only", "plugin").output
        assert index.exists() and f"kept {index}" in out and f"rm {index}" in out
        assert not isolation_path(None).exists()  # the unchanged ones still go

    def test_an_edited_isolation_json_gitconfig_and_script_are_kept(self, stack) -> None:
        install(stack)
        edited = [isolation_path(None), carter_gitconfig_path(None), guard_script_path(None)]
        for path in edited:
            path.write_text(path.read_text() + "\n# mine\n")
        reload(stack, after=debug_config())
        out = guard("remove", "--yes").output
        for path in edited:
            assert path.exists() and f"kept {path}" in out, path

    def test_a_user_edit_of_a_recorded_deny_is_kept(self, stack) -> None:
        install(stack)
        config = config_target(None)
        data = json.loads(config.read_text())
        data["agents"]["build"]["permissions"][0]["effect"] = "allow"
        config.write_text(json.dumps(data))
        reload(stack, after=debug_config())
        out = guard("remove", "--yes").output
        assert "kept build:carter_push" in out and '"allow"' in config.read_text()


class TestUninstallWiring:
    def test_carter_uninstall_runs_the_guards_first(self, stack) -> None:
        install(stack)
        reload(stack, after=debug_config())
        res = CliRunner().invoke(main, ["uninstall", "--yes"], catch_exceptions=False)
        assert res.exit_code == 0, res.output
        assert not any(p.exists() for p in plugin_files()) and not guard_state_path(None).exists()

    def test_keep_guards_leaves_the_plugin(self, stack) -> None:
        install(stack)
        res = CliRunner().invoke(
            main, ["uninstall", "--keep-guards", "--yes"], catch_exceptions=False
        )
        assert res.exit_code == 0 and all(p.exists() for p in plugin_files())


def test_git_still_works_after_every_step(stack, tmp_path: Path) -> None:
    install(stack)
    reload(stack)
    guard("remove", "--yes", "--only", "plugin")
    repo = tmp_path / "r"
    assert subprocess.run(["git", "init", "-q", str(repo)]).returncode == 0
    assert subprocess.run(["git", "status"], cwd=repo, capture_output=True).returncode == 0
