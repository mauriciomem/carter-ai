"""A broken or partial install never blocks the human's own git (plan 003 step 15, T16;
RFC-0007 §4.4 wrapper principle applied to 1G's artifacts).

Real git, a ``file://`` bare remote and the sandbox HOME: after each kind of damage, a plain
``git commit`` and ``git push`` still succeed (exit 0, the remote ref moves) and
``carter guard status`` says what is wrong."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import gitconfig as gc
from carter.guard.state import load
from carter.install.mcp import config_target
from carter.install.paths import carter_gitconfig_path, guard_state_path
from guard.helpers import debug_config


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def guard(*args: str):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False)


@pytest.fixture
def repo(tmp_path: Path, stack) -> Path:
    """A work repo whose ``origin`` is a local bare repository (``fake_opencode`` narrowed
    PATH to its own bin dir; ``stack.fake()`` links real git into it)."""
    stack.fake()
    remote = tmp_path / "remote.git"
    assert git("init", "-q", "--bare", "-b", "main", str(remote)).returncode == 0
    work = tmp_path / "work"
    assert git("init", "-q", "-b", "main", str(work)).returncode == 0
    assert git("remote", "add", "origin", f"file://{remote}", cwd=work).returncode == 0
    (work / "seed").write_text("seed")
    git("add", "seed", cwd=work)
    assert git("commit", "-q", "-m", "seed", cwd=work).returncode == 0
    assert git("push", "-q", "origin", "main", cwd=work).returncode == 0
    return work


def human_commit_and_push(work: Path, name: str) -> None:
    """What the human does: no flags, no Carter."""
    (work / name).write_text(name)
    assert git("add", name, cwd=work).returncode == 0
    commit = git("commit", "-q", "-m", f"human {name}", cwd=work)
    assert (commit.returncode, commit.stderr) == (0, ""), commit.stderr
    push = git("push", "origin", "main", cwd=work)
    assert push.returncode == 0, push.stderr
    remote = work.parent / "remote.git"
    local = git("rev-parse", "HEAD", cwd=work).stdout.strip()
    assert git("--git-dir", str(remote), "rev-parse", "main").stdout.strip() == local


@pytest.fixture
def installed_with_git_key(stack, monkeypatch: pytest.MonkeyPatch):
    """A full guard install that also writes a Carter git key (so the include line exists)."""
    monkeypatch.setattr(gc, "carter_git_entries", lambda *_a, **_k: [("carter.tier", "t1")])
    stack.fake()
    assert guard("install", "--yes").exit_code == 0
    assert carter_gitconfig_path(None).exists()
    return stack


class TestDamagedInstallLeavesGitAlone:
    def test_include_line_present_but_carters_gitconfig_deleted(
        self, installed_with_git_key, repo: Path
    ) -> None:
        carter_gitconfig_path(None).unlink()
        human_commit_and_push(repo, "a")
        installed_with_git_key.fake(before=debug_config(installed_with_git_key.live))
        out = guard("status").output
        assert "MISSING" in out and str(carter_gitconfig_path(None)) in out
        assert "include.path: present" in out

    def test_a_corrupt_guard_state(self, installed_with_git_key, repo: Path) -> None:
        guard_state_path(None).write_text("{this is not json")
        human_commit_and_push(repo, "b")
        res = guard("status")
        assert res.exit_code == 0 and "CORRUPT" in res.output
        assert guard_state_path(None).read_text() == "{this is not json"

    def test_a_half_written_temp_file_next_to_the_state(
        self, installed_with_git_key, repo: Path
    ) -> None:
        stray = guard_state_path(None).parent / ".guard-state.json.k3j2h1"
        stray.write_text('{"schema": 1, "consents": {"g2": ')
        human_commit_and_push(repo, "c")
        installed_with_git_key.fake(before=debug_config(installed_with_git_key.live))
        res = guard("status")
        assert res.exit_code == 0 and "Guard state:" in res.output and "CORRUPT" not in res.output
        # ... and the next install still converges (no change) instead of tripping on it
        installed_with_git_key.fake(before=debug_config(installed_with_git_key.live))
        assert guard("install", "--yes").exit_code == 0

    def test_an_unwritable_guard_state_does_not_matter_to_git(
        self, installed_with_git_key, repo: Path
    ) -> None:
        guard_state_path(None).unlink()
        human_commit_and_push(repo, "d")
        assert "absent (nothing installed)" in guard("status").output

    def test_a_hand_corrupted_carter_gitconfig_is_reported_and_remove_rescues_git(
        self, installed_with_git_key, repo: Path
    ) -> None:
        """Finding: git treats a malformed *included* file as fatal for every command, so this
        is the one damage that does block git. Carter never writes such a file (atomic, git-
        rendered), so it takes a hand edit; `guard status` names it and `guard remove` unsets
        the include line (keeping the edited file) to free git again."""
        carter_file = carter_gitconfig_path(None)
        carter_file.write_text("[carter\n\ttier = ")
        assert git("status", cwd=repo).returncode != 0  # the hazard, stated honestly
        out = guard("status").output
        assert f"INVALID {carter_file}" in out and "carter guard remove" in out
        installed_with_git_key.fake(
            before=debug_config(installed_with_git_key.live), after=debug_config()
        )
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert carter_file.exists() and f"kept {carter_file}" in res.output
        assert str(carter_file) not in Path(os.environ["GIT_CONFIG_GLOBAL"]).read_text()
        human_commit_and_push(repo, "i")


class TestKilledInstall:
    def test_a_process_killed_between_the_policy_write_and_the_git_write(
        self, stack, repo: Path
    ) -> None:
        script = (
            "import os, signal\n"
            "from carter.guard import gitconfig as gc\n"
            "gc.carter_git_entries = lambda *_a, **_k: [('carter.tier', 't1')]\n"
            "def die(*a, **k):\n"
            "    os.kill(os.getpid(), signal.SIGKILL)\n"
            "gc.apply_keys = die\n"
            "from carter.cli import main\n"
            "main(['guard', 'install', '--yes'])\n"
        )
        proc = subprocess.run(
            [sys.executable, "-c", script], env=os.environ.copy(), capture_output=True, text=True
        )
        assert proc.returncode == -signal.SIGKILL, proc.stdout + proc.stderr

        # Policies are in the config AND recorded as Carter's: no orphans.
        assert json.loads(config_target(None).read_text())["policies"]
        state = load(guard_state_path(None))
        assert len(state.owned_policies()) == len(stack.live)
        assert state.gitconfig is None and not carter_gitconfig_path(None).exists()

        human_commit_and_push(repo, "e")
        stack.fake(before=debug_config(stack.live))
        status = guard("status")
        assert status.exit_code == 0 and "MISSING" not in status.output

        # a clean remove finishes the job, because ownership was recorded
        stack.fake(before=debug_config(stack.live), after=debug_config())
        assert guard("remove", "--yes").exit_code == 0
        assert config_target(None).read_text().strip() == "{}"


class TestNoCarterOnTheHumansPath:
    def test_carter_missing_from_path_changes_nothing(
        self, installed_with_git_key, repo: Path
    ) -> None:
        assert shutil.which("carter") is None  # PATH holds only fake opencode and git
        human_commit_and_push(repo, "f")

    def test_2a_installs_one_config_hook_and_no_repo_hook_on_a_new_git(
        self, stack, repo: Path
    ) -> None:
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        hooks = git("config", "--global", "--includes", "--get-regexp", r"^hook\.")
        assert hooks.returncode == 0
        assert {ln.split()[0] for ln in hooks.stdout.splitlines()} == {
            "hook.carter-guard-pre-push.event",
            "hook.carter-guard-pre-push.command",
        }
        assert not (repo / ".git" / "hooks" / "pre-push").exists()
        human_commit_and_push(repo, "g")  # the hook runs and passes: this is a human env

    def test_a_full_install_then_uninstall_leaves_the_users_git_config_as_it_was(
        self, stack, repo: Path
    ) -> None:
        global_cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        before = global_cfg.read_bytes()
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        stack.fake(before=debug_config(stack.live), after=debug_config())
        assert guard("remove", "--yes").exit_code == 0
        assert global_cfg.read_bytes() == before
        human_commit_and_push(repo, "h")
