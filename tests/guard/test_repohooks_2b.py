"""Per-repo fallback for git < 2.54, revision 2: all four events (plan 005 step 19; H15).

Each event is judged on its own: a foreign ``prepare-commit-msg`` does not stop Carter owning the
free ``post-commit``; ``core.hooksPath`` repos are reported per event with the chain snippet that
carries ``CARTER_GUARD_CONFIG`` for the commit events. Old git is simulated as in
``test_repohooks.py``.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import hooks, repohooks
from carter.guard.state import GuardState, load
from carter.install.paths import carter_gitconfig_path, guard_script_path, guard_state_path
from guard.conftest import REAL_GIT
from guard.helpers import install_old_git, verbose

pytestmark = pytest.mark.gitold

EVENTS = hooks.EVENTS


def git(*args: str, cwd: Path | None = None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


@pytest.fixture
def old(stack) -> Path:
    stack.fake()
    bindir = Path(os.environ["PATH"].split(":")[0])
    install_old_git(bindir, REAL_GIT)
    return bindir


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = tmp_path / "work"
    assert git("init", "-q", "-b", "main", str(work)).returncode == 0
    monkeypatch.chdir(work)
    return work


def hook(repo: Path, event: str) -> Path:
    return repo / ".git" / "hooks" / event


class TestFreshRepo:
    def test_all_four_events_are_written_executable_and_owned(self, old, repo: Path) -> None:
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(None))
        assert state.consents["repo_hooks"]["rev"] == 2
        for event in EVENTS:
            path = hook(repo, event)
            assert path.read_text() == hooks.repo_hook_text(guard_script_path(None), event)
            assert stat.S_IMODE(path.stat().st_mode) == 0o755 and state.repo_hook_unchanged(path)

    def test_the_commit_events_name_carters_file_and_pre_push_stays_as_in_rev_1(
        self, old, repo: Path
    ) -> None:
        guard("install", "--yes")
        cfg = str(carter_gitconfig_path(None))
        assert f"CARTER_GUARD_CONFIG={cfg} " in hook(repo, "prepare-commit-msg").read_text()
        assert "CARTER_GUARD_CONFIG" not in hook(repo, "pre-push").read_text()

    def test_the_template_directory_gets_all_four_for_new_clones(self, old, repo: Path) -> None:
        guard("install", "--yes")
        template = repohooks.template_dir(None) / "hooks"
        assert {p.name for p in template.iterdir()} == set(EVENTS)
        clone = repo.parent / "clone"
        assert git("clone", "-q", str(repo), str(clone)).returncode == 0
        assert {e for e in EVENTS if hook(clone, e).exists()} == set(EVENTS)


class TestPerEvent:
    def test_a_foreign_event_is_reported_and_the_free_ones_are_ours(self, old, repo: Path) -> None:
        foreign = hook(repo, "prepare-commit-msg")
        foreign.write_text("#!/bin/sh\nexit 0\n")
        res = guard("install", "--yes")
        assert f"{repo}: unguarded: foreign hook (prepare-commit-msg)" in res.output
        assert foreign.read_text() == "#!/bin/sh\nexit 0\n"
        state = load(guard_state_path(None))
        assert {e for e in EVENTS if state.repo_hook_unchanged(hook(repo, e))} == set(EVENTS) - {
            "prepare-commit-msg"
        }

    def test_the_chain_snippet_for_a_commit_event_carries_the_config_path(
        self, old, repo: Path
    ) -> None:
        hook(repo, "commit-msg").write_text("#!/bin/sh\nexit 0\n")
        found = repohooks.inspect(repo, GuardState(), None, "commit-msg")
        assert found.state == "unguarded" and found.reason == "foreign hook"
        assert "CARTER_GUARD_CONFIG=" in found.snippet and "commit-msg" in found.snippet

    def test_hooks_path_repos_are_reported_for_each_event_and_not_touched(
        self, old, repo: Path
    ) -> None:
        git("config", "core.hooksPath", ".husky/_", cwd=repo)
        res = guard("install", "--yes")
        assert all(f"({e})" in res.output for e in EVENTS), res.output
        assert not any(hook(repo, e).exists() for e in EVENTS)
        assert load(guard_state_path(None)).repo_hooks == []

    def test_a_revision_1_install_keeps_pre_push_only(self, old, repo: Path) -> None:
        statuses = repohooks.scan([repo], GuardState(), None, hooks.events_for_rev(1))
        assert [s.hook.name for s in statuses if s.hook] == ["pre-push"]


class TestRemoval:
    def test_remove_takes_every_owned_event_and_keeps_an_edited_one(self, old, repo: Path) -> None:
        guard("install", "--yes")
        edited = hook(repo, "post-commit")
        edited.write_text(edited.read_text() + "# mine\n")
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert edited.exists() and f"kept {edited}" in res.output
        assert not any(hook(repo, e).exists() for e in EVENTS if e != "post-commit")
