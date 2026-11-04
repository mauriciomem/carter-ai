"""Per-repo ``pre-push`` fallback for git < 2.54 (plan 004 step 25; RFC-0007 C.6.5).

Old git is simulated with a PATH wrapper whose ``git hook ...`` exits 129 (spike E 6), the way
003 did; a CI container axis with a real old git comes in step 33. Hooks are written into temp
repositories only: the autouse fixture in ``conftest.py`` fails a test that touches this repo.
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
from carter.guard import hooks, repohooks
from carter.guard.state import GuardState, load
from carter.identity.errors import E_GIT_OLD, registry
from carter.install.paths import carter_gitconfig_path, guard_script_path, guard_state_path
from guard.conftest import REAL_GIT
from guard.helpers import debug_config, install_old_git

CHAIN = '"$@" || exit 1'


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    return subprocess.run(
        ["git", *args], cwd=cwd, env={**os.environ, **(env or {})}, capture_output=True, text=True
    )


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False, **kw)


def make_repo(root: Path, name: str = "work") -> Path:
    repo = root / name
    assert git("init", "-q", "-b", "main", str(repo)).returncode == 0
    return repo


@pytest.fixture
def old(stack) -> Path:
    """OpenCode and an old git on PATH; returns the bin dir."""
    stack.fake()
    bindir = Path(os.environ["PATH"].split(":")[0])
    install_old_git(bindir, REAL_GIT)
    return bindir


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    work = make_repo(tmp_path)
    monkeypatch.chdir(work)
    return work


def installed_state(tmp_path: Path) -> GuardState:
    state = GuardState()
    hooks.install_script(None, state)
    return state


class TestInspect:
    def test_absent_is_installable(self, repo: Path) -> None:
        found = repohooks.inspect(repo, GuardState(), None)
        assert (found.state, found.reason) == ("installable", "not installed")

    def test_installing_writes_an_owned_executable_hook(self, repo: Path, tmp_path: Path) -> None:
        state = installed_state(tmp_path)
        found = repohooks.install(repo, state, None)
        hook = repo / ".git" / "hooks" / "pre-push"
        assert found.state == "guarded" and found.hook == hook
        assert stat.S_IMODE(hook.stat().st_mode) == 0o755
        assert hook.read_text() == hooks.repo_hook_text(guard_script_path(None))
        assert hook.read_text().startswith("#!/bin/sh\n# Managed by Carter")
        assert state.repo_hook_unchanged(hook)
        assert repohooks.inspect(repo, state, None).state == "guarded"

    def test_a_foreign_hook_is_never_touched_and_gets_a_chain_snippet(self, repo: Path) -> None:
        hook = repo / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\necho mine\n")
        hook.chmod(0o755)
        state = GuardState()
        found = repohooks.install(repo, state, None)
        assert (found.state, found.reason) == ("unguarded", "foreign hook")
        assert hook.read_text() == "#!/bin/sh\necho mine\n" and state.repo_hooks == []
        assert "carter-guard" in found.snippet and CHAIN in found.snippet
        assert found.line().endswith("unguarded: foreign hook")

    def test_an_owned_hook_the_user_edited_is_kept_and_reported(
        self, repo: Path, tmp_path: Path
    ) -> None:
        state = installed_state(tmp_path)
        repohooks.install(repo, state, None)
        hook = repo / ".git" / "hooks" / "pre-push"
        hook.write_text(hook.read_text() + "# mine\n")
        again = repohooks.install(repo, state, None)
        assert (again.state, again.reason) == ("unguarded", "edited hook")
        assert hook.read_text().endswith("# mine\n")

    def test_core_hookspath_is_unguarded_and_husky_and_pre_commit_are_never_edited(
        self, repo: Path
    ) -> None:
        husky = repo / ".husky"
        (husky / "_").mkdir(parents=True)
        (husky / "pre-push").write_text("#!/bin/sh\nnpm test\n")
        config = repo / ".pre-commit-config.yaml"
        config.write_text("repos: []\n")
        git("config", "core.hooksPath", ".husky/_", cwd=repo)
        before = {p: p.read_bytes() for p in (husky / "pre-push", config)}
        state = GuardState()
        found = repohooks.install(repo, state, None)
        assert (found.state, found.reason) == ("unguarded", "hooksPath")
        assert "core.hooksPath is .husky/_" in found.snippet
        assert {p: p.read_bytes() for p in before} == before
        assert (
            sorted(
                p.name
                for p in (repo / ".git" / "hooks").iterdir()
                if not p.name.endswith(".sample")
            )
            == []
        )
        assert sorted(p.name for p in husky.iterdir()) == ["_", "pre-push"]

    def test_a_global_hookspath_counts_too(self, repo: Path, tmp_path: Path) -> None:
        git("config", "--global", "core.hooksPath", str(tmp_path / "global-hooks"))
        assert repohooks.inspect(repo, GuardState(), None).reason == "hooksPath"

    def test_not_a_repository(self, tmp_path: Path) -> None:
        plain = tmp_path / "plain"
        plain.mkdir()
        assert repohooks.toplevel(plain) is None
        assert repohooks.repos_in_scope(plain, [str(tmp_path / "nowhere")]) == []

    def test_scope_is_the_cwd_repo_and_the_workspace_repos_without_duplicates(
        self, repo: Path, tmp_path: Path
    ) -> None:
        other = make_repo(tmp_path, "other")
        found = repohooks.repos_in_scope(repo, [str(other), str(repo), str(tmp_path)])
        assert [p.resolve() for p in found] == [repo.resolve(), other.resolve()]

    def test_a_worktree_shares_the_hooks_of_its_main_repo(self, repo: Path, tmp_path: Path) -> None:
        (repo / "f").write_text("x")
        git("add", "f", cwd=repo)
        git("commit", "-qm", "x", cwd=repo)
        tree = tmp_path / "tree"
        assert git("worktree", "add", "-q", str(tree), cwd=repo).returncode == 0
        state = installed_state(tmp_path)
        repohooks.install(repo, state, None)
        assert repohooks.inspect(tree, state, None).state == "guarded"


class TestVerdict:
    def statuses(self, *states: str) -> list[repohooks.RepoStatus]:
        return [
            repohooks.RepoStatus(Path(f"/r{i}"), s, "foreign hook") for i, s in enumerate(states)
        ]  # type: ignore[arg-type]

    def test_ok_warn_and_fail_while_t2_is_set(self) -> None:
        assert repohooks.verdict(self.statuses("guarded"), "t2") == "ok"
        assert repohooks.verdict(self.statuses("guarded", "unguarded"), "t0") == "warn"
        assert repohooks.verdict(self.statuses("installable"), "t1") == "warn"
        assert repohooks.verdict(self.statuses("guarded", "unguarded"), "t2") == "fail"

    def test_scan_marks_an_uninstalled_repo_unguarded(self, repo: Path) -> None:
        assert repohooks.verdict(repohooks.scan([repo], GuardState(), None), "t2") == "fail"


class TestTemplateDir:
    def test_set_only_when_the_user_has_none(self, tmp_path: Path) -> None:
        cfg = Path(os.environ["GIT_CONFIG_GLOBAL"])
        assert repohooks.plan_template(cfg, None).status == "set"
        git("config", "--global", "init.templateDir", "/theirs")
        plan = repohooks.plan_template(cfg, None)
        assert plan.status == "kept-user-value" and "/theirs" in plan.snippet
        assert "New clones are NOT guarded" in plan.snippet
        git("config", "--global", "init.templateDir", str(repohooks.template_dir(None)))
        assert repohooks.plan_template(cfg, None).status == "ours"

    def test_a_template_value_from_an_include_counts(self, tmp_path: Path) -> None:
        other = tmp_path / "other.gitconfig"
        other.write_text("[init]\n\ttemplateDir = /theirs\n")
        git("config", "--global", "--add", "include.path", str(other))
        assert (
            repohooks.plan_template(Path(os.environ["GIT_CONFIG_GLOBAL"]), None).status
            == "kept-user-value"
        )

    def test_new_repos_get_the_hook_through_the_template(self, tmp_path: Path) -> None:
        state = installed_state(tmp_path)
        assert repohooks.install_template(None, state) == "created"
        path = repohooks.template_dir(None) / "hooks" / "pre-push"
        assert stat.S_IMODE(path.stat().st_mode) == 0o755 and state.owned_unchanged(path)
        git("config", "--global", "init.templateDir", str(repohooks.template_dir(None)))
        fresh = tmp_path / "fresh"
        assert git("init", "-q", str(fresh)).returncode == 0
        assert (fresh / ".git" / "hooks" / "pre-push").read_text() == path.read_text()


class TestRemovalAndMigration:
    def test_only_owned_unchanged_hooks_are_removed(self, tmp_path: Path) -> None:
        a, b, c = (make_repo(tmp_path, n) for n in "abc")
        state = installed_state(tmp_path)
        for r in (a, b):
            repohooks.install(r, state, None)
        foreign = c / ".git" / "hooks" / "pre-push"
        foreign.write_text("#!/bin/sh\nexit 0\n")
        edited = b / ".git" / "hooks" / "pre-push"
        edited.write_text(edited.read_text() + "# mine\n")
        rem = repohooks.remove_owned(state)
        assert rem.removed == [str(a / ".git" / "hooks" / "pre-push")]
        assert rem.kept == [str(edited)] and edited.exists() and foreign.exists()
        assert state.repo_hooks == []  # forgotten either way

    def test_other_old_gits_lists_only_old_binaries(self, tmp_path: Path) -> None:
        bins = tmp_path / "bins"
        for name, version in (("old", "2.39.5"), ("new", "2.56.0")):
            d = bins / name
            d.mkdir(parents=True)
            exe = d / "git"
            exe.write_text(f'#!/bin/sh\necho "git version {version}"\n')
            exe.chmod(0o755)
        found = repohooks.other_old_gits({"PATH": f"{bins / 'new'}:{bins / 'old'}"})
        assert found == [(str(bins / "old" / "git"), "2.39")]


class TestInstallOnOldGit:
    def test_yes_installs_the_script_the_cwd_hook_and_the_template(
        self, old: Path, repo: Path
    ) -> None:
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert registry()[E_GIT_OLD].message in res.output
        hook = repo / ".git" / "hooks" / "pre-push"
        state = load(guard_state_path(None))
        assert (
            "hooks" not in state.consents and state.consents["repo_hooks"]["decision"] == "accepted"
        )
        assert state.repo_hook_unchanged(hook) and state.owned_unchanged(guard_script_path(None))
        cfg = carter_gitconfig_path(None)
        assert git("config", "--file", str(cfg), "--get", "init.templateDir").stdout.strip() == str(
            repohooks.template_dir(None)
        )
        assert git("config", "--global", "--get", "include.path").stdout.strip() == str(cfg)
        assert state.owned_unchanged(repohooks.template_dir(None) / "hooks" / "pre-push")
        assert (
            "hook.carter-guard-pre-push.command" not in cfg.read_text()
        )  # no config hook on old git

    def test_a_non_tty_run_without_yes_installs_none(
        self, old: Path, repo: Path, human_tty
    ) -> None:
        human_tty(False)
        res = guard("install")
        assert res.exit_code == 0 and "NOT installed" in res.output
        assert (
            not (repo / ".git" / "hooks" / "pre-push").exists()
            and not guard_state_path(None).exists()
        )

    def test_the_tty_offer_defaults_to_yes(self, old: Path, repo: Path, human_tty) -> None:
        human_tty(True)
        res = guard(
            "install", input="y\ny\ny\ny\n\n"
        )  # g2, sudo, read-edit, config-edit, repo_hooks=Enter
        assert res.exit_code == 0, res.output
        assert "repo_hooks: git older than 2.54 only" in res.output
        assert load(guard_state_path(None)).consents["repo_hooks"]["decision"] == "accepted"
        assert (repo / ".git" / "hooks" / "pre-push").exists()

    def test_a_no_installs_nothing_for_the_group(self, old: Path, repo: Path, human_tty) -> None:
        human_tty(True)
        guard("install", input="y\ny\ny\ny\nn\n")
        assert not (repo / ".git" / "hooks" / "pre-push").exists()
        assert not guard_script_path(None).exists()

    def test_workspace_repos_get_the_hook_too(
        self, old: Path, repo: Path, tmp_path: Path, home: Path
    ) -> None:
        ws = make_repo(tmp_path, "ws")
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[workspaces."{ws}"]\nmax_tier = "t1"\n'
        )
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        for r in (repo, ws):
            assert (r / ".git" / "hooks" / "pre-push").exists(), r

    def test_a_foreign_hook_and_a_hookspath_repo_are_reported_not_touched(
        self, old: Path, repo: Path, tmp_path: Path, home: Path
    ) -> None:
        hook = repo / ".git" / "hooks" / "pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        husky = make_repo(tmp_path, "husky")
        git("config", "core.hooksPath", ".husky/_", cwd=husky)
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[workspaces."{husky}"]\nmax_tier = "t1"\n'
        )
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert f"{repo}: unguarded: foreign hook" in res.output
        assert f"{husky}: unguarded: hooksPath" in res.output
        assert hook.read_text() == "#!/bin/sh\nexit 0\n"
        assert load(guard_state_path(None)).repo_hooks == []

    def test_a_user_template_dir_is_kept_and_new_clones_are_reported_unguarded(
        self, old: Path, repo: Path
    ) -> None:
        git("config", "--global", "init.templateDir", "/theirs")
        before = Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert "unguarded: templateDir" in res.output and "/theirs" in res.output
        assert (
            Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes() == before
        )  # no include line either
        assert not carter_gitconfig_path(None).exists()
        assert (repo / ".git" / "hooks" / "pre-push").exists()  # the cwd repo is still guarded

    def test_dry_run_inspects_and_writes_nothing(self, old: Path, repo: Path) -> None:
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        assert "would install a repo hook" in res.output
        assert (
            not (repo / ".git" / "hooks" / "pre-push").exists()
            and not guard_script_path(None).exists()
        )

    def test_a_second_run_changes_nothing(self, old: Path, repo: Path, stack) -> None:
        guard("install", "--yes")
        before = (guard_state_path(None).read_bytes(), carter_gitconfig_path(None).read_bytes())
        res = guard("install", "--yes")
        assert res.exit_code == 0 and "repo hook present" in res.output
        assert before == (
            guard_state_path(None).read_bytes(),
            carter_gitconfig_path(None).read_bytes(),
        )

    def test_remove_takes_back_only_what_is_owned_and_unchanged(
        self, old: Path, repo: Path, tmp_path: Path, home: Path
    ) -> None:
        other = make_repo(tmp_path, "other")
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(
            f'schema = 2\n[workspaces."{other}"]\nmax_tier = "t1"\n'
        )
        before = Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes()
        guard("install", "--yes")
        edited = other / ".git" / "hooks" / "pre-push"
        edited.write_text(edited.read_text() + "# mine\n")
        old.joinpath("opencode")  # the fake is still there
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        assert not (repo / ".git" / "hooks" / "pre-push").exists()
        assert edited.exists() and f"kept {edited}" in res.output
        assert (
            not guard_script_path(None).exists()
            and not repohooks.template_dir(None).joinpath("hooks", "pre-push").exists()
        )
        assert Path(os.environ["GIT_CONFIG_GLOBAL"]).read_bytes() == before

    def test_the_user_tool_dirs_are_untouched(self, old: Path, repo: Path) -> None:
        (repo / ".husky").mkdir()
        (repo / ".husky" / "pre-push").write_text("npm test\n")
        (repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        guard("install", "--yes")
        assert (repo / ".husky" / "pre-push").read_text() == "npm test\n"
        assert (repo / ".pre-commit-config.yaml").read_text() == "repos: []\n"


class TestMigration:
    def test_a_git_upgrade_replaces_the_owned_repo_hooks_with_the_config_hook(
        self, stack, old: Path, repo: Path, tmp_path: Path
    ) -> None:
        guard("install", "--yes")
        hook = repo / ".git" / "hooks" / "pre-push"
        assert hook.exists()
        install_old_git_removed = old / "git"
        install_old_git_removed.unlink()
        install_old_git_removed.symlink_to(REAL_GIT)  # git is upgraded
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "hooks")
        assert res.exit_code == 0, res.output
        assert "removing the per-repo hooks Carter wrote earlier" in res.output
        assert not hook.exists() and load(guard_state_path(None)).repo_hooks == []
        done = git("hook", "list", "--show-scope", "pre-push", cwd=repo)
        assert done.stdout.split() == ["global", "carter-guard-pre-push"]

    def test_a_changed_repo_hook_survives_the_migration(self, stack, old: Path, repo: Path) -> None:
        guard("install", "--yes")
        hook = repo / ".git" / "hooks" / "pre-push"
        hook.write_text(hook.read_text() + "# mine\n")
        (old / "git").unlink()
        (old / "git").symlink_to(REAL_GIT)
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "hooks")
        assert hook.exists() and f"kept {hook}" in res.output

    def test_it_warns_when_an_older_git_is_still_around(
        self, stack, old: Path, repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        guard("install", "--yes")
        older = tmp_path / "older"
        older.mkdir()
        (older / "git").write_text('#!/bin/sh\necho "git version 2.39.5"\n')
        (older / "git").chmod(0o755)
        (old / "git").unlink()
        (old / "git").symlink_to(REAL_GIT)
        stack.fake(before=debug_config(stack.live))
        monkeypatch.setenv("PATH", f"{os.environ['PATH']}:{older}")
        res = guard("install", "--yes", "--only", "hooks")
        assert "an older git is also installed" in res.output and "2.39" in res.output


class TestStep23MatrixOnARepoLocalInstall:
    """The pre-push matrix of step 23, with the per-repo wrapper instead of the config hook."""

    @pytest.fixture
    def rig(self, repo: Path, tmp_path: Path):
        remote = tmp_path / "remote.git"
        assert git("init", "-q", "--bare", "-b", "main", str(remote)).returncode == 0
        git("remote", "add", "origin", f"file://{remote}", cwd=repo)
        (repo / "f").write_text("x")
        git("add", "f", cwd=repo)
        assert git("commit", "-qm", "x", cwd=repo).returncode == 0
        state = installed_state(tmp_path)
        repohooks.install(repo, state, None)

        def push(env: dict[str, str] | None = None, *flags: str, pre: tuple[str, ...] = ()):
            return git(*pre, "push", *flags, "origin", "main", cwd=repo, env=env)

        def remote_head() -> str:
            return git("rev-parse", "--verify", "-q", "refs/heads/main", cwd=remote).stdout.strip()

        return push, remote_head

    @pytest.mark.parametrize(
        "env", [{"AGENT": "1"}, {"OPENCODE_SESSION_ID": "s"}, {"CARTER_AGENT_SHELL": "1"}]
    )
    def test_agents_are_blocked_humans_pass(self, rig, env: dict[str, str]) -> None:
        push, remote_head = rig
        done = push(env)
        assert done.returncode != 0 and "carter push" in done.stderr and remote_head() == ""
        assert push().returncode == 0 and remote_head() != ""

    def test_a_deleted_script_blocks_only_the_agent(self, rig) -> None:
        push, remote_head = rig
        guard_script_path(None).unlink()
        assert push({"AGENT": "1"}).returncode != 0 and remote_head() == ""
        assert push().returncode == 0

    def test_no_verify_and_hookspath_skip_the_repo_hook_documented_limits(self, rig) -> None:
        """Weaker than the config hook, which survives ``-c core.hooksPath``: the gate's rules on
        ``--no-verify`` and ``-c core.hooksPath`` are what hold here (C.4.1)."""
        push, remote_head = rig
        assert push({"AGENT": "1"}, pre=("-c", "core.hooksPath=/dev/null")).returncode == 0
        assert remote_head() != ""

    def test_no_verify_skips_it(self, rig) -> None:
        push, remote_head = rig
        assert push({"AGENT": "1"}, "--no-verify").returncode == 0 and remote_head() != ""


def test_the_probe_reports_old_git_for_the_wrapper(old: Path) -> None:
    assert gc.probe_scope() == "no-config-hooks"
