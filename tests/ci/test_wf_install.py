# ruff: noqa: E501
"""``carter ci install review`` (plan 008 step 5): human-only, never overwrites an edited file."""

from __future__ import annotations

import os
import stat
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.ci import WORKFLOW_REL, check, template
from carter.cli import main
from carter.identity.errors import E_HUMAN_TERMINAL


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "work"
    (root / "sub" / "dir").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    return root


def ci(*args: str):
    return CliRunner().invoke(main, ["ci", "install", "review", *args], catch_exceptions=False)


def target(repo: Path) -> Path:
    return repo / WORKFLOW_REL


class TestWrite:
    def test_it_writes_the_one_file_and_it_passes_the_checker(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        before = sorted(p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts)
        res = ci()
        assert res.exit_code == 0, res.output
        after = sorted(p.relative_to(repo) for p in repo.rglob("*") if ".git" not in p.parts)
        assert [p.as_posix() for p in after if p not in before] == [
            ".github",
            ".github/workflows",
            ".github/workflows/carter-review.yml",
        ]
        text = target(repo).read_text()
        assert text == template.render() and check.check(text) == []
        assert stat.S_IMODE(target(repo).stat().st_mode) == 0o644
        assert not list(target(repo).parent.glob(".carter-review.*"))

    def test_from_a_subdirectory_it_still_writes_at_the_repository_root(
        self, repo: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        monkeypatch.chdir(repo / "sub" / "dir")
        assert ci().exit_code == 0 and target(repo).is_file()

    def test_the_advice_names_the_environment_the_secret_and_codeowners(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        out = ci().output
        for needle in ("carter-review", "LLM_API_KEY", "CODEOWNERS", "commit it and push it yourself",
                       "Fork pull requests are skipped"):  # fmt: skip
            assert needle in out, needle
        assert "WIDENS" not in out

    def test_the_comment_opt_in_says_it_widens_the_scope(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        res = ci("--comment")
        assert res.exit_code == 0 and "WIDENS the scope" in res.output
        assert "pull-requests: write" in res.output and check.check(target(repo).read_text()) == []
        assert target(repo).read_text() == template.render(comment=True)

    def test_a_second_run_is_up_to_date(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        ci()
        mtime = target(repo).stat().st_mtime_ns
        res = ci()
        assert "up to date" in res.output and target(repo).stat().st_mtime_ns == mtime

    def test_an_unedited_file_is_switched_between_variants(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        ci()
        res = ci("--comment")
        assert res.exit_code == 0 and "updated" in res.output
        assert target(repo).read_text() == template.render(comment=True)
        assert ci().exit_code == 0 and target(repo).read_text() == template.render()


class TestPreReleaseNote:
    def test_a_dev_version_is_flagged_because_it_may_not_be_on_pypi(
        self, repo: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import carter

        human_tty(True)
        monkeypatch.setattr(carter, "__version__", "0.17.1.dev3+gabc")
        assert "pre-release" in ci().output

    def test_a_release_is_not(
        self, repo: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import carter

        human_tty(True)
        monkeypatch.setattr(carter, "__version__", "0.17.1")
        assert "pre-release" not in ci().output


class TestNeverOverwritesAnEdit:
    def test_an_edited_file_is_kept_and_the_error_says_what_to_do(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        ci()
        edited = target(repo).read_text().replace("timeout-minutes: 15", "timeout-minutes: 30")
        target(repo).write_text(edited)
        res = ci()
        assert res.exit_code != 0 and "was edited" in res.output and "--dry-run" in res.output
        assert target(repo).read_text() == edited

    def test_a_file_not_written_by_carter_is_kept(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(True)
        target(repo).parent.mkdir(parents=True)
        target(repo).write_text("name: mine\non: push\n")
        assert ci().exit_code != 0 and target(repo).read_text() == "name: mine\non: push\n"

    def test_force_replaces_it(self, repo: Path, human_tty: Callable[[bool], None]) -> None:
        human_tty(True)
        target(repo).parent.mkdir(parents=True)
        target(repo).write_text("name: mine\n")
        assert ci("--force").exit_code == 0 and target(repo).read_text() == template.render()


class TestHumanOnly:
    def test_an_agent_shell_is_refused_and_nothing_is_written(
        self, repo: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        monkeypatch.setenv("AGENT", "1")
        res = ci()
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert not (repo / ".github").exists()

    def test_the_dry_run_is_refused_in_an_agent_shell_too(
        self, repo: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(False)
        monkeypatch.setenv("OPENCODE_SESSION_ID", "ses_1")
        assert ci("--dry-run").exit_code == 1

    def test_without_a_terminal_nothing_is_written(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(False)
        res = ci()
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert not (repo / ".github").exists()

    def test_the_dry_run_prints_the_file_and_writes_nothing_even_without_a_terminal(
        self, repo: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(False)
        res = ci("--dry-run")
        assert res.exit_code == 0 and template.render().splitlines()[1] in res.output
        assert "dry run: nothing written" in res.output and not (repo / ".github").exists()

    def test_the_gate_treats_it_as_a_human_only_carter_verb(self) -> None:
        from carter.gate import check as gate

        for command in ("carter ci install review", "carter ci install review --comment"):
            verdict = gate(command, cwd="/tmp")
            assert verdict.decision == "deny" and verdict.rule == "human-only-carter", command
        assert gate("carter ci review").decision == "allow"  # the workflow's own command


class TestRefusals:
    def test_outside_a_repository(
        self, tmp_path: Path, human_tty: Callable[[bool], None], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        human_tty(True)
        monkeypatch.chdir(tmp_path)
        res = ci()
        assert res.exit_code != 0 and "not inside a git repository" in res.output

    def test_a_symlinked_workflows_directory_is_not_followed(
        self, repo: Path, human_tty: Callable[[bool], None], tmp_path: Path
    ) -> None:
        human_tty(True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (repo / ".github").mkdir()
        os.symlink(elsewhere, repo / ".github" / "workflows")
        res = ci()
        assert res.exit_code != 0 and "symlink" in res.output and not list(elsewhere.iterdir())

    def test_a_symlinked_target_is_not_followed(
        self, repo: Path, human_tty: Callable[[bool], None], tmp_path: Path
    ) -> None:
        human_tty(True)
        (repo / ".github" / "workflows").mkdir(parents=True)
        victim = tmp_path / "victim"
        victim.write_text("keep")
        os.symlink(victim, target(repo))
        assert ci("--force").exit_code != 0 and victim.read_text() == "keep"

    def test_only_review_exists(self, repo: Path) -> None:
        res = CliRunner().invoke(main, ["ci", "install", "deploy"])
        assert res.exit_code == 2
