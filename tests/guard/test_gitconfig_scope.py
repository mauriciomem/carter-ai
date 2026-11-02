"""D61 prerequisite (RFC-0007 §4.4, §9): git reports a hook defined in a file pulled in by
``include.path`` from the *global* config as scope ``global``.

This pins what the plan-003 step-2 spike found on git 2.56, so step 13 (Carter's own
``~/.carter/gitconfig`` behind one include line) can rely on it. Everything runs in the
hermetic fixture home: ``GIT_CONFIG_GLOBAL`` points at a scratch file, never the real one.

``hook_scopes`` is the behavioural detection; since plan 003 step 13 it lives in
``carter.guard.gitconfig`` (the production probe) and this file imports it: do not parse
versions, ask git where it read the hook from.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from carter.guard.gitconfig import hook_scopes

HOOK = "carter-guard-commit-msg"


def _git_version() -> tuple[int, ...]:
    out = subprocess.run(["git", "--version"], capture_output=True, text=True, check=True).stdout
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


pytestmark = pytest.mark.skipif(
    _git_version() < (2, 54),
    reason="git hook list --show-scope and config-based hooks need git >= 2.54",
)


def git(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def fragment(marker: Path, *, enabled: bool = True, tier: str = "from-include") -> str:
    text = (
        f'[hook "{HOOK}"]\n\tevent = commit-msg\n\tcommand = echo ran >> {marker}\n'
        f"[carter]\n\ttier = {tier}\n"
    )
    if not enabled:
        text += f'[hook "{HOOK}"]\n\tenabled = false\n'
    return text


def set_global(include_lines: str) -> Path:
    """Rewrite the fixture's global config (keeps the fixture identity)."""
    path = Path(os.environ["GIT_CONFIG_GLOBAL"])
    path.write_text(
        "[user]\n\tname = Fixture Human\n\temail = fixture-human@example.invalid\n" + include_lines
    )
    return path


def include(path: Path | str) -> str:
    return f"[include]\n\tpath = {path}\n"


@pytest.fixture
def carter_gitconfig(_hermetic_env: Path) -> Path:
    return _hermetic_env / "carter-gitconfig"


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "hook-ran"


def make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    assert git("init", "-q", "-b", "main", str(path)).returncode == 0
    return path


def commit(repo: Path, name: str, message: str) -> subprocess.CompletedProcess[str]:
    (repo / name).write_text(name)
    git("add", name, cwd=repo)
    return git("commit", "-q", "-m", message, cwd=repo)


class TestIncludedHookIsGlobal:
    def test_scope_is_global_for_an_absolute_include(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        assert hook_scopes(repo) == {HOOK: "global"}

    def test_origin_is_the_included_file_and_scope_global(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        out = git(
            "config", "--show-scope", "--show-origin", "--get", f"hook.{HOOK}.event", cwd=repo
        ).stdout
        assert out.split("\t")[0] == "global"
        assert out.split("\t")[1] == f"file:{carter_gitconfig}"

    def test_the_hook_really_runs_on_commit(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        assert commit(repo, "a.txt", "first").returncode == 0
        assert marker.exists()

    def test_tilde_include_is_global_too(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include("~/carter-gitconfig"))
        repo = make_repo(tmp_path / "repo")
        assert hook_scopes(repo) == {HOOK: "global"}

    def test_relative_include_resolves_next_to_the_global_file(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include("carter-gitconfig"))
        repo = make_repo(tmp_path / "repo")
        assert hook_scopes(repo) == {HOOK: "global"}


class TestGuardReadForm:
    """``git config --global --includes --get`` is the form the guard reads (RFC §4.4)."""

    def read(self, repo: Path, *pre: str) -> str:
        return git(
            *pre, "config", "--global", "--includes", "--get", "carter.tier", cwd=repo
        ).stdout.strip()

    def test_reads_the_included_value(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        assert self.read(make_repo(tmp_path / "repo")) == "from-include"

    def test_minus_c_and_local_config_are_ignored(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        git("config", "--local", "carter.tier", "local", cwd=repo)
        assert self.read(repo, "-c", "carter.tier=evil") == "from-include"
        # contrast: the merged read form is the one an attacker can steer
        assert git("config", "--get", "carter.tier", cwd=repo).stdout.strip() == "local"
        merged = git("-c", "carter.tier=evil", "config", "--get", "carter.tier", cwd=repo)
        assert merged.stdout.strip() == "evil"

    def test_without_includes_the_value_is_invisible(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        # Guard code must pass --includes; the plain --global read does not follow include.path.
        carter_gitconfig.write_text(fragment(marker))
        set_global(include(carter_gitconfig))
        proc = git("config", "--global", "--get", "carter.tier", cwd=make_repo(tmp_path / "repo"))
        assert proc.returncode == 1


class TestMissingInclude:
    def test_git_stays_silent_and_the_human_can_commit(
        self, tmp_path: Path, _hermetic_env: Path
    ) -> None:
        set_global(include(_hermetic_env / "does-not-exist"))
        repo = make_repo(tmp_path / "repo")
        status = git("status", "--short", cwd=repo)
        assert (status.returncode, status.stderr) == (0, "")
        done = commit(repo, "a.txt", "human commit")
        assert (done.returncode, done.stderr) == (0, "")

    def test_no_hook_is_reported(self, tmp_path: Path, _hermetic_env: Path) -> None:
        set_global(include(_hermetic_env / "does-not-exist"))
        assert hook_scopes(make_repo(tmp_path / "repo")) == {}


class TestDisabledFromInclude:
    def test_enabled_false_in_the_include_disables_the_hook(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker, enabled=False))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        listing = git("hook", "list", "--show-scope", "commit-msg", cwd=repo).stdout
        assert f"global\tdisabled\t{HOOK}" in listing
        assert commit(repo, "a.txt", "first").returncode == 0
        assert not marker.exists()

    def test_a_local_enable_overrides_it_so_disable_is_not_a_boundary(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker, enabled=False))
        set_global(include(carter_gitconfig))
        repo = make_repo(tmp_path / "repo")
        git("config", "--local", f"hook.{HOOK}.enabled", "true", cwd=repo)
        assert commit(repo, "a.txt", "first").returncode == 0
        assert marker.exists()


class TestIncludeIfGitdir:
    @pytest.fixture
    def tree(self, tmp_path: Path, carter_gitconfig: Path, marker: Path) -> Path:
        carter_gitconfig.write_text(fragment(marker))
        work = tmp_path / "work"
        work.mkdir()
        set_global(f'[includeIf "gitdir:{work}/"]\n\tpath = {carter_gitconfig}\n')
        return work

    def test_matches_the_repo_root_and_a_subdirectory(self, tree: Path) -> None:
        repo = make_repo(tree / "proj")
        sub = repo / "a" / "b"
        sub.mkdir(parents=True)
        assert hook_scopes(repo) == {HOOK: "global"}
        assert hook_scopes(sub) == {HOOK: "global"}

    def test_matches_through_a_symlinked_path(self, tree: Path, tmp_path: Path) -> None:
        repo = make_repo(tree / "proj")
        link = tmp_path / "link"
        link.symlink_to(repo)
        assert hook_scopes(link) == {HOOK: "global"}

    def test_a_repo_outside_the_tree_does_not_match(self, tree: Path, tmp_path: Path) -> None:
        assert hook_scopes(make_repo(tmp_path / "elsewhere" / "other")) == {}

    def test_pattern_without_trailing_slash_matches_nothing(
        self, tmp_path: Path, carter_gitconfig: Path, marker: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        work = tmp_path / "work"
        set_global(f'[includeIf "gitdir:{work}"]\n\tpath = {carter_gitconfig}\n')
        assert hook_scopes(make_repo(work / "proj")) == {}

    def test_a_worktree_follows_the_location_of_its_main_repo(
        self, tree: Path, tmp_path: Path
    ) -> None:
        # includeIf compares the git dir (<main>/.git/worktrees/<name>), not the checkout path.
        inside = make_repo(tree / "proj")
        commit(inside, "f.txt", "init")
        outside = make_repo(tmp_path / "elsewhere" / "other")
        commit(outside, "f.txt", "init")
        wt_of_inside = tmp_path / "elsewhere" / "wt-of-proj"
        wt_in_tree = tree / "wt-of-other"
        assert (
            git("worktree", "add", "-q", str(wt_of_inside), "-b", "w1", cwd=inside).returncode == 0
        )
        assert (
            git("worktree", "add", "-q", str(wt_in_tree), "-b", "w2", cwd=outside).returncode == 0
        )
        assert hook_scopes(wt_of_inside) == {HOOK: "global"}
        assert hook_scopes(wt_in_tree) == {}


class TestSymlinkedGlobalConfig:
    def test_absolute_include_through_a_symlinked_global_is_global(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        carter_gitconfig.write_text(fragment(marker))
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        real.write_text(include(carter_gitconfig))
        link = set_global("")
        link.unlink()
        link.symlink_to(real)
        assert hook_scopes(make_repo(tmp_path / "repo")) == {HOOK: "global"}

    def test_relative_include_resolves_from_the_symlink_not_its_target(
        self, carter_gitconfig: Path, marker: Path, tmp_path: Path
    ) -> None:
        # Why the installer must write an absolute path: a human's ~/.gitconfig is often a symlink.
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        (real.parent / "carter-gitconfig").write_text(fragment(marker))
        real.write_text(include("carter-gitconfig"))
        link = set_global("")
        link.unlink()
        link.symlink_to(real)
        assert hook_scopes(make_repo(tmp_path / "repo")) == {}

    def test_git_config_add_and_unset_keep_the_symlink(
        self, carter_gitconfig: Path, tmp_path: Path
    ) -> None:
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        real.write_text("[user]\n\tname = Human\n")
        link = set_global("")
        link.unlink()
        link.symlink_to(real)
        assert (
            git("config", "--global", "--add", "include.path", str(carter_gitconfig)).returncode
            == 0
        )
        assert link.is_symlink()
        assert str(carter_gitconfig) in real.read_text()
        assert git("config", "--global", "--unset", "include.path").returncode == 0
        assert link.is_symlink()
        assert real.read_text() == "[user]\n\tname = Human\n"


class TestBehaviouralDetection:
    """Where a hook came from decides whether it counts as Carter's global one."""

    def test_a_command_line_hook_is_not_global(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path / "repo")
        proc = git(
            "-c", "hook.x.event=commit-msg", "-c", "hook.x.command=true",
            "hook", "list", "--show-scope", "commit-msg", cwd=repo,
        )  # fmt: skip
        assert proc.stdout.split("\t")[0] == "command"

    def test_a_local_hook_is_not_global(self, tmp_path: Path) -> None:
        repo = make_repo(tmp_path / "repo")
        git("config", "--local", "hook.loc.event", "commit-msg", cwd=repo)
        git("config", "--local", "hook.loc.command", "true", cwd=repo)
        assert hook_scopes(repo) == {"loc": "local"}

    def test_a_repo_without_hooks_reports_none(self, tmp_path: Path) -> None:
        assert hook_scopes(make_repo(tmp_path / "repo")) == {}
