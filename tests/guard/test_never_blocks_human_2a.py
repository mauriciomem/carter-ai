"""A broken or partial 2a install never blocks the human's own git (plan 004 step 28, T16).

Real git, a ``file://`` bare remote, the sandbox HOME. After each kind of damage a plain
``git commit`` and ``git push`` still succeed and the remote ref moves.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import plugin
from carter.install.mcp import config_target
from carter.install.paths import (
    carter_gitconfig_path,
    guard_script_path,
    guard_state_path,
    isolation_path,
    plugin_dir,
)
from guard.helpers import debug_config, verbose


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True
    )


def guard(*args: str):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False)


@pytest.fixture
def repo(tmp_path: Path, stack) -> Path:
    stack.fake()
    remote = tmp_path / "remote.git"
    assert git("init", "-q", "--bare", "-b", "main", str(remote)).returncode == 0
    work = tmp_path / "work"
    assert git("init", "-q", "-b", "main", str(work)).returncode == 0
    git("remote", "add", "origin", f"file://{remote}", cwd=work)
    (work / "seed").write_text("seed")
    git("add", "seed", cwd=work)
    assert git("commit", "-q", "-m", "seed", cwd=work).returncode == 0
    assert git("push", "-q", "origin", "main", cwd=work).returncode == 0
    return work


def human_works(work: Path, name: str) -> None:
    (work / name).write_text(name)
    assert git("add", name, cwd=work).returncode == 0
    commit = git("commit", "-q", "-m", name, cwd=work)
    assert (commit.returncode, commit.stderr) == (0, ""), commit.stderr
    push = git("push", "origin", "main", cwd=work)
    assert push.returncode == 0, push.stderr
    remote = Path(
        git("remote", "get-url", "origin", cwd=work).stdout.strip().removeprefix("file://")
    )
    head = git("rev-parse", "HEAD", cwd=work).stdout.strip()
    assert git("rev-parse", "refs/heads/main", cwd=remote).stdout.strip() == head


def installed(stack) -> None:
    stack.fake()
    assert guard("install", "--yes").exit_code == 0


class TestDamage:
    def test_a_full_install_changes_nothing_for_the_human(self, stack, repo: Path) -> None:
        installed(stack)
        human_works(repo, "a")

    def test_an_install_killed_midway_leaves_git_working(
        self, stack, repo: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*_a, **_k):
            raise KeyboardInterrupt

        monkeypatch.setattr(plugin, "install", boom)
        stack.fake()
        assert guard("install", "--yes").exit_code != 0  # click turns the interrupt into Abort
        assert not guard_state_path(None).exists()  # rolled back as a whole
        human_works(repo, "b")

    def test_the_include_line_present_and_the_file_deleted(self, stack, repo: Path) -> None:
        installed(stack)
        carter_gitconfig_path(None).unlink()
        human_works(repo, "c")

    def test_the_guard_script_deleted_or_not_executable(self, stack, repo: Path) -> None:
        installed(stack)
        guard_script_path(None).chmod(0o644)
        human_works(repo, "d")
        guard_script_path(None).unlink()
        human_works(repo, "e")
        agent = git("push", "origin", "main", cwd=repo, env={"AGENT": "1"})
        assert agent.returncode != 0 or "up-to-date" in agent.stderr + agent.stdout

    def test_carter_missing_from_path(self, stack, repo: Path) -> None:
        installed(stack)
        assert shutil.which("carter") is None
        human_works(repo, "f")

    def test_a_corrupt_guard_state(self, stack, repo: Path) -> None:
        installed(stack)
        guard_state_path(None).write_text("{broken")
        human_works(repo, "g")

    def test_the_plugin_files_missing(self, stack, repo: Path) -> None:
        installed(stack)
        shutil.rmtree(plugin_dir(None))
        isolation_path(None).unlink()
        human_works(repo, "h")


class TestMalformedIncludedGitconfig:
    def break_it(self) -> None:
        carter_gitconfig_path(None).write_text("[hook\n\tbroken =\n")

    def test_git_itself_fails_and_remove_still_works(self, stack, repo: Path) -> None:
        installed(stack)
        self.break_it()
        assert git("status", cwd=repo).returncode != 0  # why this is checked first
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert git("status", cwd=repo).returncode == 0
        human_works(repo, "i")

    def test_the_emergency_path_deleting_the_file_restores_git(self, stack, repo: Path) -> None:
        installed(stack)
        self.break_it()
        carter_gitconfig_path(None).unlink()  # what the docs say, with carter unusable
        human_works(repo, "j")

    def test_restoring_the_saved_opencode_config_restores_opencode(self, stack, home: Path) -> None:
        config = config_target(None)
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text('{"keep": 1}\n')
        installed(stack)
        backups = sorted((home / ".carter" / "backups").rglob("opencode.json*"))
        assert backups, "the first config write is backed up"
        shutil.copy(backups[0], config)
        assert config.read_text() == '{"keep": 1}\n'
