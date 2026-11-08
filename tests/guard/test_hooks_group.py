"""The ``hooks`` consent group is live (plan 004 step 24; RFC-0007 C.6.2, C.6.4, D61).

``carter guard install`` writes ``~/.carter/hooks/carter-guard`` (0755) and the first Carter git
keys into ``~/.carter/gitconfig``, then adds ONE include line to the global git config, unless
that config is a symlink or read-only (dotfiles): then it prints the exact line and records
nothing. Everything runs under the sandbox HOME with a fake OpenCode.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard import hooks
from carter.guard.state import load
from carter.identity.errors import E_GIT_OLD, registry
from carter.install.paths import carter_gitconfig_path, guard_script_path, guard_state_path
from guard.conftest import REAL_GIT
from guard.helpers import debug_config, decline, install_old_git, verbose


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def global_cfg() -> Path:
    return Path(os.environ["GIT_CONFIG_GLOBAL"])


def read_key(path: Path, key: str) -> str:
    done = subprocess.run(
        ["git", "config", "--file", str(path), "--get", key], capture_output=True, text=True
    )
    return done.stdout.rstrip("\n")


def read_all(path: Path, key: str) -> list[str]:
    done = subprocess.run(
        ["git", "config", "--file", str(path), "--get-all", key], capture_output=True, text=True
    )
    return done.stdout.splitlines()


class TestEntries:
    def test_only_when_hooks_is_accepted(self) -> None:
        assert gc.carter_git_entries() == []
        assert gc.carter_git_entries(["g2", "sudo-docker"]) == []
        entries = dict(gc.carter_git_entries(["hooks"], hooks_rev=1))  # what revision 1 wrote
        assert set(entries) == {
            "hook.carter-guard-pre-push.event",
            "hook.carter-guard-pre-push.command",
        }
        assert entries["hook.carter-guard-pre-push.event"] == "pre-push"

    def test_the_command_quotes_the_script_path(self, tmp_path: Path) -> None:
        entries = dict(gc.carter_git_entries(["hooks"], base_dir=tmp_path / "it's here"))
        assert "'\"'\"'" in entries["hook.carter-guard-pre-push.command"]  # shlex.quote of '

    def test_the_template_key_needs_repo_hooks_and_a_directory(self, tmp_path: Path) -> None:
        assert gc.carter_git_entries(["repo_hooks"]) == []
        assert gc.carter_git_entries(["hooks"], template_dir=tmp_path) == gc.carter_git_entries(
            ["hooks"]
        )
        assert gc.carter_git_entries(["repo_hooks"], template_dir=tmp_path) == [
            ("init.templateDir", str(tmp_path))
        ]


class TestInstall:
    def test_the_script_and_the_gitconfig_are_written_hashed_and_recorded(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        script, cfg = guard_script_path(None), carter_gitconfig_path(None)
        assert (
            stat.S_IMODE(script.stat().st_mode) == 0o755
            and script.read_text() == hooks.render_script()
        )
        assert stat.S_IMODE(cfg.stat().st_mode) == 0o600 and cfg.read_text().startswith(
            "# Managed by Carter"
        )
        state = load(guard_state_path(None))
        assert state.owned_unchanged(script) and state.owned_unchanged(cfg)
        assert state.guard_version == hooks.GUARD_VERSION
        assert state.gitconfig == {
            "file": str(global_cfg()), "key": "include.path", "value": str(cfg),
        }  # fmt: skip
        assert read_key(global_cfg(), "include.path") == str(cfg)

    def test_git_sees_the_hook_as_global(self, stack, tmp_path: Path) -> None:
        stack.fake()
        guard("install", "--yes")
        repo = tmp_path / "r"
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        done = subprocess.run(
            ["git", "hook", "list", "--show-scope", "pre-push"],
            cwd=repo, capture_output=True, text=True,
        )  # fmt: skip
        assert done.stdout.split() == ["global", "carter-guard-pre-push"]

    def test_a_second_run_changes_nothing_and_never_doubles_the_include_line(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        before = (global_cfg().read_bytes(), guard_state_path(None).read_bytes())
        stack.fake(before=debug_config(stack.live))
        assert guard("install", "--yes").exit_code == 0
        assert (global_cfg().read_bytes(), guard_state_path(None).read_bytes()) == before
        assert read_all(global_cfg(), "include.path") == [str(carter_gitconfig_path(None))]

    def test_declined_hooks_write_nothing_and_are_listed(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        decline("hooks")
        res = guard("install", input="y\n")  # a group declined earlier is not asked again
        assert res.exit_code == 0, res.output
        assert not guard_script_path(None).exists() and not carter_gitconfig_path(None).exists()
        assert "include" not in global_cfg().read_text()
        out = guard("status").output
        assert "hooks" in out and "declined" in out and "residual" in out

    def test_the_consent_prompt_shows_the_effect_line(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n")
        question = res.output.split("Install?")[0]
        assert "git hooks check agent commits and block agent pushes in every repo" in question
        assert "not yours" in question

    def test_remove_takes_back_the_script_the_file_and_the_line(self, stack) -> None:
        before = global_cfg().read_bytes()
        stack.fake()
        guard("install", "--yes")
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert global_cfg().read_bytes() == before
        assert not guard_script_path(None).exists() and not carter_gitconfig_path(None).exists()

    def test_remove_only_hooks_keeps_the_denies(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--yes", "--only", "hooks")
        assert res.exit_code == 0, res.output
        assert (
            not guard_script_path(None).exists()
            and "carter-gitconfig" not in global_cfg().read_text()
        )
        state = load(guard_state_path(None))
        assert "hooks" not in state.consents and "g2" in state.consents
        assert state.agent_permissions  # the per-agent denies stay


class TestDotfiles:
    """A symlinked or read-only global config is never written (003 decision 4)."""

    def symlinked(self, tmp_path: Path) -> Path:
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        real.write_bytes(global_cfg().read_bytes())
        global_cfg().unlink()
        global_cfg().symlink_to(real)
        return real

    def test_a_symlinked_config_gets_the_line_printed_and_nothing_written(
        self, stack, tmp_path: Path
    ) -> None:
        real = self.symlinked(tmp_path)
        before = real.read_bytes()
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        line = f"git config --global --add include.path {carter_gitconfig_path(None)}"
        assert line in res.output and "symlink" in res.output
        assert real.read_bytes() == before and global_cfg().is_symlink()
        state = load(guard_state_path(None))
        assert state.gitconfig is None  # not ours: nothing recorded
        assert state.owned_unchanged(guard_script_path(None)) and state.owned_unchanged(
            carter_gitconfig_path(None)
        )

    def test_status_says_the_hook_is_inactive_until_the_line_is_added(
        self, stack, tmp_path: Path
    ) -> None:
        real = self.symlinked(tmp_path)
        stack.fake()
        guard("install", "--yes")
        stack.fake(before=debug_config(stack.live))
        assert "inactive" in guard("status").output
        subprocess.run(
            [
                "git",
                "config",
                "--file",
                str(real),
                "--add",
                "include.path",
                str(carter_gitconfig_path(None)),
            ],
            check=True,
        )
        assert "present (you added it" in guard("status").output

    def test_remove_prints_the_unset_line_when_you_added_it(self, stack, tmp_path: Path) -> None:
        real = self.symlinked(tmp_path)
        stack.fake()
        guard("install", "--yes")
        value = str(carter_gitconfig_path(None))
        subprocess.run(
            ["git", "config", "--file", str(real), "--add", "include.path", value], check=True
        )
        before = real.read_bytes()
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert f"git config --global --fixed-value --unset-all include.path {value}" in res.output
        assert real.read_bytes() == before  # still the human's to edit

    def test_a_read_only_config_is_treated_the_same(
        self, stack, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        locked = tmp_path / "locked"
        locked.mkdir()
        cfg = locked / "gitconfig"
        cfg.write_bytes(global_cfg().read_bytes())
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(cfg))
        cfg.chmod(0o444)
        locked.chmod(0o555)
        try:
            before = cfg.read_bytes()
            stack.fake()
            res = guard("install", "--yes")
            assert res.exit_code == 0, res.output
            assert "not writable" in res.output
            assert "git config --global --add include.path" in res.output
            assert cfg.read_bytes() == before
            assert load(guard_state_path(None)).gitconfig is None
        finally:
            locked.chmod(0o755)
            cfg.chmod(0o644)

    def test_a_dry_run_on_such_a_host_prints_the_line_and_writes_nothing(
        self, stack, tmp_path: Path
    ) -> None:
        real = self.symlinked(tmp_path)
        before = (real.read_bytes(), sorted(p.name for p in global_cfg().parent.iterdir()))
        stack.fake()
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        assert "include.path" in res.output and "Add the line yourself" in res.output
        assert before == (real.read_bytes(), sorted(p.name for p in global_cfg().parent.iterdir()))
        assert not guard_script_path(None).exists() and not guard_state_path(None).exists()


class TestMalformedAndEdited:
    def test_an_unreadable_rendered_file_is_never_moved_into_place(
        self, stack, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gc, "render_gitconfig", lambda entries: "[hook\n\tbroken =\n")
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 1 and "not valid git config" in res.output
        assert (
            not carter_gitconfig_path(None).exists() and "include" not in global_cfg().read_text()
        )
        assert not guard_state_path(None).exists()  # the install rolled back as a whole
        assert not guard_script_path(None).exists()

    def test_git_still_works_when_the_included_file_is_malformed_later(
        self, stack, tmp_path: Path
    ) -> None:
        stack.fake()
        guard("install", "--yes")
        carter_gitconfig_path(None).write_text("[hook\n\tbroken =\n")
        # the removal uses `--file` with the global config switched off, so it still works
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert "include" not in global_cfg().read_text()

    def test_a_user_edited_gitconfig_is_kept(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        cfg = carter_gitconfig_path(None)
        cfg.write_text(cfg.read_text() + "[carter]\n\tmine = 1\n")
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and "kept your edited" in res.output
        assert cfg.read_text().endswith("mine = 1\n")

    def test_a_user_edited_script_is_kept(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        script = guard_script_path(None)
        script.write_text(script.read_text() + "# mine\n")
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes")
        assert "kept your edited" in res.output and script.read_text().endswith("# mine\n")


class TestGitUnusable:
    def test_an_install_without_a_working_git_installs_no_hook_and_removes_nothing(
        self, stack
    ) -> None:
        stack.fake()
        guard("install", "--yes")
        (Path(os.environ["PATH"].split(":")[0]) / "git").unlink()  # git vanishes from PATH
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        (Path(os.environ["PATH"].split(":")[0]) / "git").unlink(missing_ok=True)
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert "git is not usable here" in res.output
        assert guard_script_path(None).exists() and carter_gitconfig_path(None).exists()
        assert load(guard_state_path(None)).gitconfig is not None


class TestOldGit:
    """git < 2.54 (simulated, spike E 6): no consent is asked for nothing (G10)."""

    def old(self, stack) -> None:
        stack.fake()
        install_old_git(Path(os.environ["PATH"].split(":")[0]), REAL_GIT)

    def test_hooks_is_not_prompted_or_recorded_and_the_error_text_is_the_registered_one(
        self, stack
    ) -> None:
        self.old(stack)
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert registry()[E_GIT_OLD].message in res.output
        state = load(guard_state_path(None))
        assert "hooks" not in state.consents
        assert not guard_script_path(None).exists() or "repo_hooks" in state.consents

    def test_the_hook_group_is_listed_as_not_on_this_machine_in_a_dry_run(self, stack) -> None:
        self.old(stack)
        out = guard("install", "--dry-run").output
        assert "hooks              not on this machine: E-GIT-OLD" in out
