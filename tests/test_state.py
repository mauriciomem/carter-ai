"""Tests for carter.state git operations — the ADR-0003 recovery primitive.

``commit_state`` is what makes "I deleted a plan/session" recoverable: the nested
.carter/.git must carry ongoing history beyond the single init commit.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from carter.config import generate_default_config
from carter.state import commit_state, init_workspace


@pytest.fixture
def config() -> dict:
    cfg = generate_default_config(workspace_name="state-test", mode="umbrella")
    cfg["agent_suffix"] = ""
    return cfg


def _git(carter_dir: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=carter_dir, capture_output=True, text=True, check=False
    )


class TestCommitState:
    def test_init_makes_exactly_one_commit(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        log = _git(carter_dir, "log", "--oneline")
        assert "init carter state" in log.stdout
        assert len(log.stdout.strip().splitlines()) == 1

    def test_commits_new_changes(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        (carter_dir / "state" / "sessions" / "checkpoint.md").write_text(
            "---\nupdated: 2026-06-09\n---\n", encoding="utf-8"
        )
        assert commit_state(carter_dir, "test: add checkpoint") is True
        log = _git(carter_dir, "log", "--oneline")
        assert "add checkpoint" in log.stdout
        assert len(log.stdout.strip().splitlines()) == 2

    def test_returns_false_when_nothing_to_commit(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        # init already committed everything; nothing new staged
        assert commit_state(carter_dir, "test: noop") is False

    def test_returns_false_without_git_repo(self, tmp_path, config):
        carter_dir = init_workspace(tmp_path, config, git_state=False)
        assert not (carter_dir / ".git").exists()
        assert commit_state(carter_dir, "test: no repo") is False

    def test_deleted_plan_is_recoverable(self, tmp_path, config):
        """The headline recovery contract: a deleted plan dir is restorable."""
        carter_dir = init_workspace(tmp_path, config, git_state=True)
        plan = carter_dir / "state" / "plans" / "active" / "001-x"
        plan.mkdir(parents=True)
        (plan / "README.md").write_text("---\nid: 001-x\n---\n", encoding="utf-8")
        commit_state(carter_dir, "test: add plan 001-x")

        shutil.rmtree(plan)
        assert not plan.exists()

        _git(carter_dir, "checkout", "HEAD", "--", "state/plans/active/001-x/README.md")
        assert (plan / "README.md").exists()


class TestSaveCommand:
    def _runner(self):
        from click.testing import CliRunner

        from carter.cli import main

        return CliRunner(), main

    def test_save_commits_changes(self, tmp_path):
        runner, main = self._runner()
        runner.invoke(main, ["init", str(tmp_path)])
        cp = tmp_path / ".carter" / "state" / "sessions" / "checkpoint.md"
        cp.write_text("---\nupdated: 2026-06-09\n---\n", encoding="utf-8")
        result = runner.invoke(main, ["save", str(tmp_path), "-m", "test: cp"])
        assert result.exit_code == 0, result.output
        assert "Saved" in result.output

    def test_save_nothing_to_commit(self, tmp_path):
        runner, main = self._runner()
        runner.invoke(main, ["init", str(tmp_path)])
        result = runner.invoke(main, ["save", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert "Nothing to save" in result.output

    def test_save_not_a_workspace(self, tmp_path):
        runner, main = self._runner()
        result = runner.invoke(main, ["save", str(tmp_path)])
        assert result.exit_code != 0
