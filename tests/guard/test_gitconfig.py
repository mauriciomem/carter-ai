"""Carter's own gitconfig behind one ``include.path`` line .

Built and tested under the sandbox home only: nothing here may touch ``~/.gitconfig``."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from carter.guard import gitconfig as gc
from carter.guard.state import GuardState
from carter.install.paths import carter_gitconfig_path


def git(
    *args: str, cwd: Path | None = None, env: dict | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env=env)


def git_version() -> tuple[int, int]:
    m = re.search(r"(\d+)\.(\d+)", git("--version").stdout)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


needs_hooks = pytest.mark.skipif(
    git_version() < (2, 54), reason="config-based hooks need git >= 2.54"
)
needs_user = pytest.mark.skipif(os.geteuid() == 0, reason="root ignores file permissions")


@pytest.fixture
def global_cfg() -> Path:
    return Path(os.environ["GIT_CONFIG_GLOBAL"])


@pytest.fixture
def value(tmp_path: Path) -> str:
    return str(carter_gitconfig_path(tmp_path))


def includes(path: Path) -> list[str]:
    out = git("config", "--file", str(path), "--get-all", "include.path")
    return out.stdout.splitlines()


def _env(home: Path) -> dict[str, str]:
    """A git environment with no GIT_CONFIG_GLOBAL: git resolves ~/.gitconfig and XDG itself."""
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "PATH": os.environ["PATH"],
    }


class TestResolveGlobalConfig:
    def test_honours_git_config_global(self, global_cfg: Path) -> None:
        assert gc.global_config_path() == global_cfg

    def test_the_origin_git_reports_wins_for_a_non_empty_config(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        (home / ".config" / "git").mkdir(parents=True)
        xdg = home / ".config" / "git" / "config"
        xdg.write_text("[user]\n\tname = X\n")
        env = _env(home)
        assert gc.global_config_path(env) == xdg

    def test_dotfile_wins_over_xdg_when_both_exist(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".config" / "git" / "config").write_text("[user]\n\tname = X\n")
        (home / ".gitconfig").write_text("[user]\n\tname = Y\n")
        env = _env(home)
        assert gc.global_config_path(env) == home / ".gitconfig"

    def test_an_empty_or_absent_config_falls_back_to_git_defaults(self, tmp_path: Path) -> None:
        home = tmp_path / "h"
        home.mkdir()
        env = _env(home)
        assert gc.global_config_path(env) == home / ".gitconfig"
        (home / ".config" / "git").mkdir(parents=True)
        (home / ".config" / "git" / "config").write_text("")
        assert gc.global_config_path(env) == home / ".config" / "git" / "config"


class TestAddAndRemoveInclude:
    def test_adds_exactly_one_absolute_line(self, global_cfg: Path, value: str) -> None:
        res = gc.add_include(global_cfg, value)
        assert res.status == "added"
        assert includes(global_cfg) == [value]
        assert git("config", "--global", "--get", "user.name").stdout.strip() == "Fixture Human"

    def test_a_second_call_is_a_no_op(self, global_cfg: Path, value: str) -> None:
        gc.add_include(global_cfg, value)
        before = global_cfg.read_bytes()
        assert gc.add_include(global_cfg, value).status == "present"
        assert global_cfg.read_bytes() == before

    def test_the_users_other_includes_are_untouched(self, global_cfg: Path, value: str) -> None:
        git("config", "--file", str(global_cfg), "--add", "include.path", "/home/u/work.gitconfig")
        gc.add_include(global_cfg, value)
        git("config", "--file", str(global_cfg), "--add", "include.path", "/home/u/other.gitconfig")
        assert includes(global_cfg) == ["/home/u/work.gitconfig", value, "/home/u/other.gitconfig"]
        assert gc.remove_include(global_cfg, value).status == "removed"
        assert includes(global_cfg) == ["/home/u/work.gitconfig", "/home/u/other.gitconfig"]

    def test_a_relative_or_tilde_value_is_refused(self, global_cfg: Path) -> None:
        for bad in ("carter-gitconfig", "~/.carter/gitconfig", ""):
            with pytest.raises(ValueError, match="absolute"):
                gc.add_include(global_cfg, bad)

    def test_remove_when_the_user_already_removed_it_touches_nothing(
        self, global_cfg: Path, value: str
    ) -> None:
        gc.add_include(global_cfg, value)
        git("config", "--file", str(global_cfg), "--unset-all", "include.path")
        before = global_cfg.read_bytes()
        res = gc.remove_include(global_cfg, value)
        assert res.status == "absent" and "not found" in res.note
        assert global_cfg.read_bytes() == before

    def test_remove_when_the_user_changed_the_value_touches_nothing(
        self, global_cfg: Path, value: str
    ) -> None:
        gc.add_include(global_cfg, value)
        git("config", "--file", str(global_cfg), "include.path", "/somewhere/else")
        res = gc.remove_include(global_cfg, value)
        assert res.status == "absent" and includes(global_cfg) == ["/somewhere/else"]

    def test_duplicates_of_exactly_our_line_are_all_removed(
        self, global_cfg: Path, value: str
    ) -> None:
        git("config", "--file", str(global_cfg), "--add", "include.path", value)
        git("config", "--file", str(global_cfg), "--add", "include.path", value)
        gc.remove_include(global_cfg, value)
        assert includes(global_cfg) == []

    def test_the_value_is_recorded_verbatim_and_unresolved(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        link = tmp_path / "link"
        link.symlink_to(tmp_path)
        value = str(link / "carter" / "gitconfig")
        gc.add_include(global_cfg, value)
        assert includes(global_cfg) == [value]  # not the realpath: --fixed-value --unset must match


class TestMalformedIncludedFile:
    """git treats a malformed *included* file as fatal for every command that loads the global
    config, so the calls that undo the include must not load it."""

    def test_parses_tells_good_from_bad(self, tmp_path: Path) -> None:
        good, bad = tmp_path / "good", tmp_path / "bad"
        good.write_text("[a]\n\tb = c\n")
        bad.write_text("[a\n\tb = ")
        assert gc.parses(good) and not gc.parses(bad)

    def test_the_include_line_can_still_be_removed_while_the_included_file_is_broken(
        self, global_cfg: Path, tmp_path: Path
    ) -> None:
        broken = tmp_path / "broken.gitconfig"
        broken.write_text("[a\n\tb = ")
        gc.add_include(global_cfg, str(broken))
        assert git("status").returncode != 0  # plain git is blocked now
        assert gc.has_include_line(global_cfg, str(broken))
        assert gc.remove_include(global_cfg, str(broken)).status == "removed"
        assert git("config", "--global", "--list").returncode == 0

    def test_file_env_switches_the_global_config_off_and_drops_injected_pairs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setenv("GIT_CONFIG_KEY_0", "user.name")
        env = gc.file_env()
        assert env["GIT_CONFIG_GLOBAL"] == "/dev/null" and env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert "GIT_CONFIG_COUNT" not in env and "GIT_CONFIG_KEY_0" not in env


class TestNotWrittenWhenNotOurs:
    def test_a_symlinked_global_config_gets_the_line_printed_not_written(
        self, tmp_path: Path, global_cfg: Path, value: str
    ) -> None:
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        real.write_text("[user]\n\tname = D\n")
        global_cfg.unlink()
        global_cfg.symlink_to(real)
        res = gc.add_include(global_cfg, value)
        assert res.status == "manual" and "symlink" in res.note
        assert res.line == f"git config --global --add include.path {value}"
        assert real.read_text() == "[user]\n\tname = D\n" and global_cfg.is_symlink()

    def test_remove_prints_the_matching_unset_line(
        self, tmp_path: Path, global_cfg: Path, value: str
    ) -> None:
        real = tmp_path / "dotfiles" / "gitconfig"
        real.parent.mkdir()
        real.write_text(f"[include]\n\tpath = {value}\n")
        global_cfg.unlink()
        global_cfg.symlink_to(real)
        res = gc.remove_include(global_cfg, value)
        assert res.status == "manual"
        assert res.line == f"git config --global --fixed-value --unset-all include.path {value}"
        assert value in real.read_text()

    @needs_user
    def test_a_read_only_file_gets_the_line_printed(self, global_cfg: Path, value: str) -> None:
        global_cfg.chmod(0o444)
        before = global_cfg.read_bytes()
        res = gc.add_include(global_cfg, value)
        assert res.status == "manual" and "not writable" in res.note and res.line
        assert global_cfg.read_bytes() == before

    @needs_user
    def test_a_read_only_directory_gets_the_line_printed(self, tmp_path: Path, value: str) -> None:
        d = tmp_path / "ro"
        d.mkdir()
        (d / "gitconfig").write_text("[user]\n\tname = R\n")
        d.chmod(0o555)
        try:
            res = gc.add_include(d / "gitconfig", value)
        finally:
            d.chmod(0o755)
        assert res.status == "manual"

    def test_manual_results_record_nothing_in_guard_state(
        self, tmp_path: Path, global_cfg: Path, value: str
    ) -> None:
        real = tmp_path / "real"
        real.write_text("")
        global_cfg.unlink()
        global_cfg.symlink_to(real)
        state = GuardState()
        res = gc.add_include(global_cfg, value)
        gc.record_include(state, global_cfg, value, res)
        assert state.gitconfig is None

    def test_an_added_include_is_recorded_once(self, global_cfg: Path, value: str) -> None:
        state = GuardState()
        gc.record_include(state, global_cfg, value, gc.add_include(global_cfg, value))
        assert state.gitconfig == {"file": str(global_cfg), "key": "include.path", "value": value}
        gc.record_include(state, global_cfg, value, gc.add_include(global_cfg, value))  # "present"
        assert state.gitconfig["value"] == value


class TestCartersFile:
    def test_atomic_0600_and_hash_recorded(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        content = gc.render_gitconfig([("carter.tier", "t0")])
        assert gc.install_file(path, content, state) == "created"
        assert path.read_text() == content and stat.S_IMODE(path.stat().st_mode) == 0o600
        assert state.owned_unchanged(path)

    def test_the_rendered_file_is_valid_git_config_with_a_header(self) -> None:
        content = gc.render_gitconfig([("carter.tier", "t0"), ("hook.x.event", "commit-msg")])
        assert content.startswith("# Managed by Carter")
        assert "tier = t0" in content

    def test_the_scaffold_is_comment_only_and_still_valid(self, tmp_path: Path) -> None:
        path = tmp_path / "scaffold"
        path.write_text(gc.render_gitconfig([]))
        assert git("config", "--file", str(path), "--list").returncode == 0
        assert git("config", "--file", str(path), "--list").stdout == ""

    def test_rendering_is_deterministic(self) -> None:
        entries = [("carter.tier", "t0"), ("carter.llmEmail", "a@b.invalid")]
        assert gc.render_gitconfig(entries) == gc.render_gitconfig(entries)

    def test_a_second_install_of_the_same_content_is_a_no_op(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        content = gc.render_gitconfig([])
        gc.install_file(path, content, state)
        os.utime(path, ns=(10**9, 10**9))
        assert gc.install_file(path, content, state) == "unchanged"
        assert path.stat().st_mtime_ns == 10**9

    def test_a_changed_content_updates_an_unedited_file(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        new = gc.render_gitconfig([("carter.tier", "t1")])
        assert gc.install_file(path, new, state) == "updated"
        assert path.read_text() == new and state.owned_unchanged(path)

    def test_a_user_edit_is_detected_and_not_overwritten(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        path.write_text(path.read_text() + "[user]\n\tname = mine\n")
        edited = path.read_bytes()
        new = gc.render_gitconfig([("carter.tier", "t1")])
        assert gc.install_file(path, new, state) == "edited-kept"
        assert path.read_bytes() == edited

    def test_the_explicit_human_install_may_overwrite_after_the_edit_check(
        self, tmp_path: Path
    ) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        path.write_text("edited\n")
        new = gc.render_gitconfig([("carter.tier", "t1")])
        assert gc.install_file(path, new, state, overwrite_edited=True) == "updated"
        assert path.read_text() == new

    def test_an_unrecorded_existing_file_is_treated_as_the_users(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        path.parent.mkdir(parents=True)
        path.write_text("[user]\n\tname = theirs\n")
        assert gc.install_file(path, gc.render_gitconfig([]), state) == "edited-kept"
        assert path.read_text() == "[user]\n\tname = theirs\n"

    def test_failure_mid_write_leaves_the_old_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        before = path.read_bytes()
        monkeypatch.setattr(os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("busy")))
        with pytest.raises(OSError):
            gc.install_file(path, gc.render_gitconfig([("carter.tier", "t1")]), state)
        assert path.read_bytes() == before
        assert [p.name for p in path.parent.iterdir()] == ["gitconfig"]

    def test_remove_deletes_an_unchanged_file_and_forgets_its_hash(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        res = gc.remove_files(tmp_path, state)
        assert res.removed == [str(path)] and not path.exists() and state.files == []

    def test_remove_keeps_an_edited_file_and_says_so(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        path.write_text("edited\n")
        res = gc.remove_files(tmp_path, state)
        assert res.kept == [str(path)] and path.read_text() == "edited\n"
        assert state.files == []  # we no longer claim it

    def test_remove_handles_fragments_by_hash_and_keeps_a_non_empty_directory(
        self, tmp_path: Path
    ) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        frags = path.parent / "gitconfig.d"
        frags.mkdir()
        mine, theirs, edited = frags / "aaa", frags / "bbb", frags / "ccc"
        for f in (mine, edited):
            gc.install_file(f, "# frag\n", state)
        theirs.write_text("# not recorded\n")
        edited.write_text("# user edit\n")
        res = gc.remove_files(tmp_path, state)
        assert not mine.exists() and theirs.exists() and edited.exists() and frags.is_dir()
        assert str(mine) in res.removed and {str(theirs), str(edited)} <= set(res.kept)

    def test_remove_drops_an_empty_fragments_directory(self, tmp_path: Path) -> None:
        path, state = carter_gitconfig_path(tmp_path), GuardState()
        gc.install_file(path, gc.render_gitconfig([]), state)
        frags = path.parent / "gitconfig.d"
        frags.mkdir()
        gc.install_file(frags / "aaa", "# frag\n", state)
        gc.remove_files(tmp_path, state)
        assert not frags.exists()

    def test_remove_with_nothing_there_is_a_no_op(self, tmp_path: Path) -> None:
        res = gc.remove_files(tmp_path, GuardState())
        assert res.removed == [] and res.kept == []


class TestHumanGitNeverBlocked:
    def test_include_line_present_but_carters_file_deleted(
        self, tmp_path: Path, global_cfg: Path, value: str
    ) -> None:
        gc.add_include(global_cfg, value)
        assert not Path(value).exists()
        repo = tmp_path / "repo"
        repo.mkdir()
        assert git("init", "-q", "-b", "main", str(repo)).returncode == 0
        (repo / "a").write_text("a")
        git("add", "a", cwd=repo)
        done = git("commit", "-q", "-m", "mine", cwd=repo)
        assert (done.returncode, done.stderr) == (0, "")
        assert git("log", "--oneline", cwd=repo).stdout.strip().endswith("mine")

    def test_a_corrupt_carter_file_is_only_an_error_for_reading_it(
        self, tmp_path: Path, global_cfg: Path, value: str
    ) -> None:
        # git itself rejects a malformed included file: that is why Carter's file is written
        # atomically and only ever from git's own rendering, never half-written.
        gc.add_include(global_cfg, value)
        Path(value).parent.mkdir(parents=True, exist_ok=True)
        Path(value).write_text(gc.render_gitconfig([("carter.tier", "t0")]))
        repo = tmp_path / "repo"
        git("init", "-q", "-b", "main", str(repo))
        (repo / "a").write_text("a")
        git("add", "a", cwd=repo)
        assert git("commit", "-q", "-m", "ok", cwd=repo).returncode == 0


class TestProbe:
    class Scripted:
        """A fake runner: pops one reply per ``hook list`` call and records every env."""

        def __init__(self, *replies: tuple[int, str, str]) -> None:
            self.replies = list(replies)
            self.calls: list[tuple[list[str], dict]] = []

        def __call__(self, args, *, env=None, cwd=None):
            self.calls.append((list(args), dict(env or {})))
            if args[:2] == ["hook", "list"]:
                rc, out, err = self.replies.pop(0)
                return subprocess.CompletedProcess(args, rc, out, err)
            return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)

    def test_include_when_an_included_hook_is_reported_global(self) -> None:
        run = self.Scripted((0, "global\tcarter-probe\n", ""))
        assert gc.probe_scope(runner=run) == "include"

    def test_direct_when_only_a_direct_hook_is_listed(self) -> None:
        run = self.Scripted((1, "", "warning: no hooks found"), (0, "global\tcarter-probe\n", ""))
        assert gc.probe_scope(runner=run) == "direct"

    def test_direct_when_the_included_hook_has_another_scope(self) -> None:
        run = self.Scripted((0, "local\tcarter-probe\n", ""), (0, "global\tcarter-probe\n", ""))
        assert gc.probe_scope(runner=run) == "direct"

    def test_no_config_hooks_when_git_cannot_list_hooks_at_all(self) -> None:
        run = self.Scripted((129, "", "git: 'hook list' is not a git command"), (129, "", "usage"))
        assert gc.probe_scope(runner=run) == "no-config-hooks"

    def test_no_config_hooks_when_neither_probe_lists_a_hook(self) -> None:
        run = self.Scripted((1, "", "warning: no hooks found"), (1, "", "warning: no hooks found"))
        assert gc.probe_scope(runner=run) == "no-config-hooks"

    def test_the_probe_runs_in_a_scratch_config_never_the_real_one(
        self, global_cfg: Path, tmp_path: Path
    ) -> None:
        run = self.Scripted((0, "global\tcarter-probe\n", ""))
        before = global_cfg.read_bytes()
        gc.probe_scope(runner=run)
        env = next(e for a, e in run.calls if a[:2] == ["hook", "list"])
        assert env["GIT_CONFIG_NOSYSTEM"] == "1"
        assert Path(env["GIT_CONFIG_GLOBAL"]) != global_cfg
        assert Path(env["HOME"]) != Path(os.environ["HOME"])
        assert global_cfg.read_bytes() == before
        assert not any(k.startswith("GIT_CONFIG_KEY") or k == "GIT_CONFIG_PARAMETERS" for k in env)

    def test_the_scratch_area_is_removed_afterwards(self) -> None:
        run = self.Scripted((0, "global\tcarter-probe\n", ""))
        gc.probe_scope(runner=run)
        scratch = Path(next(e for a, e in run.calls if a[:2] == ["hook", "list"])["HOME"])
        assert not scratch.exists()

    @needs_hooks
    def test_real_git_here_reports_include(self) -> None:
        assert gc.probe_scope() == "include"

    def test_git_missing_is_a_typed_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("PATH", "/nonexistent")
        with pytest.raises(gc.GitError, match="not found"):
            gc.probe_scope()


class TestHookScopes:
    @needs_hooks
    def test_parses_scope_and_name_including_disabled(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        git("config", "--file", str(global_cfg), "hook.a.event", "commit-msg")
        git("config", "--file", str(global_cfg), "hook.a.command", "true")
        git("config", "--file", str(global_cfg), "hook.b.event", "commit-msg")
        git("config", "--file", str(global_cfg), "hook.b.command", "true")
        git("config", "--file", str(global_cfg), "hook.b.enabled", "false")
        repo = tmp_path / "r"
        git("init", "-q", str(repo))
        assert gc.hook_scopes(repo) == {"a": "global", "b": "global"}


class TestDirectFallback:
    ENTRIES = [("carter.tier", "t1"), ("hook.carter-guard-commit-msg.event", "commit-msg")]

    def test_writes_the_same_keys_directly_and_records_each_tuple(self, global_cfg: Path) -> None:
        state = GuardState()
        res = gc.write_direct(global_cfg, self.ENTRIES, state)
        assert res.written == [k for k, _ in self.ENTRIES]
        for key, val in self.ENTRIES:
            assert git("config", "--file", str(global_cfg), "--get", key).stdout.strip() == val
        assert state.git_config == [
            {"file": str(global_cfg), "key": k, "value": v, "scope": "global"}
            for k, v in self.ENTRIES
        ]

    def test_idempotent(self, global_cfg: Path) -> None:
        state = GuardState()
        gc.write_direct(global_cfg, self.ENTRIES, state)
        before = global_cfg.read_bytes()
        res = gc.write_direct(global_cfg, self.ENTRIES, state)
        assert (
            res.written == [] and global_cfg.read_bytes() == before and len(state.git_config) == 2
        )

    def test_a_different_user_value_is_kept_and_reported(self, global_cfg: Path) -> None:
        git("config", "--file", str(global_cfg), "carter.tier", "t2")
        state = GuardState()
        res = gc.write_direct(global_cfg, self.ENTRIES, state)
        assert res.conflicts == ["carter.tier"]
        assert (
            git("config", "--file", str(global_cfg), "--get", "carter.tier").stdout.strip() == "t2"
        )
        assert [r["key"] for r in state.git_config] == ["hook.carter-guard-commit-msg.event"]

    def test_removal_deletes_only_unchanged_values(self, global_cfg: Path) -> None:
        state = GuardState()
        gc.write_direct(global_cfg, self.ENTRIES, state)
        git("config", "--file", str(global_cfg), "carter.tier", "t0")  # the user changed it
        res = gc.remove_direct(global_cfg, state)
        assert res.removed == ["hook.carter-guard-commit-msg.event"] and res.kept == ["carter.tier"]
        assert (
            git("config", "--file", str(global_cfg), "--get", "carter.tier").stdout.strip() == "t0"
        )
        assert (
            git(
                "config", "--file", str(global_cfg), "--get", "hook.carter-guard-commit-msg.event"
            ).returncode
            == 1
        )
        assert state.git_config == []

    def test_a_symlinked_global_config_is_not_written_directly_either(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        real = tmp_path / "real"
        real.write_text("")
        global_cfg.unlink()
        global_cfg.symlink_to(real)
        state = GuardState()
        res = gc.write_direct(global_cfg, self.ENTRIES, state)
        assert res.manual and "git config --global carter.tier t1" in res.manual[0]
        assert real.read_text() == "" and state.git_config == []


class TestApplyKeys:
    ENTRIES = [("alias.ai-commit", "!true")]  # not a `carter.*` key: those are the hook tier

    def apply(self, tmp_path: Path, mode: str, entries=None, **kw):
        state = GuardState()
        res = gc.apply_keys(
            self.ENTRIES if entries is None else entries,
            mode=mode,
            base_dir=tmp_path,
            state=state,
            **kw,
        )
        return state, res

    def test_include_mode_writes_the_file_then_the_include_line(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        state, res = self.apply(tmp_path, "include")
        carter = carter_gitconfig_path(tmp_path)
        assert (
            git("config", "--file", str(carter), "--get", "alias.ai-commit").stdout.strip()
            == "!true"
        )
        assert includes(global_cfg) == [str(carter)]
        assert state.gitconfig["value"] == str(carter) and state.owned_unchanged(carter)
        glob = git("config", "--global", "--includes", "--get", "alias.ai-commit")
        assert glob.stdout.strip() == "!true"

    def test_no_entries_means_no_file_and_no_include_line(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        before = global_cfg.read_bytes()
        state, res = self.apply(tmp_path, "include", entries=[])
        assert res.status == "not-needed" and global_cfg.read_bytes() == before
        assert not carter_gitconfig_path(tmp_path).exists() and state.gitconfig is None

    def test_direct_mode_records_tuples_and_writes_no_file(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        state, res = self.apply(tmp_path, "direct")
        assert not carter_gitconfig_path(tmp_path).exists() and includes(global_cfg) == []
        assert state.git_config and state.gitconfig is None

    def test_no_config_hooks_mode_sends_plain_keys_through_the_include_and_hooks_to_the_fallback(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        entries = [("carter.tier", "t1"), ("hook.carter-guard-commit-msg.event", "commit-msg")]
        state, res = self.apply(tmp_path, "no-config-hooks", entries=entries)
        carter = carter_gitconfig_path(tmp_path)
        assert git("config", "--file", str(carter), "--get", "carter.tier").returncode == 0
        assert (
            git(
                "config", "--file", str(carter), "--get", "hook.carter-guard-commit-msg.event"
            ).returncode
            == 1
        )
        assert res.needs_repo_hooks == ["hook.carter-guard-commit-msg.event"]

    def test_a_symlinked_global_config_returns_the_manual_line(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        real = tmp_path / "real"
        real.write_text("")
        global_cfg.unlink()
        global_cfg.symlink_to(real)
        state, res = self.apply(tmp_path, "include")
        assert res.include.status == "manual" and res.include.line
        assert state.gitconfig is None and carter_gitconfig_path(tmp_path).exists()

    def test_remove_all_undoes_include_mode(self, tmp_path: Path, global_cfg: Path) -> None:
        state, _ = self.apply(tmp_path, "include")
        res = gc.remove_all(tmp_path, state)
        assert includes(global_cfg) == [] and not carter_gitconfig_path(tmp_path).exists()
        assert state.gitconfig is None and state.files == []
        assert res.include.status == "removed"

    def test_remove_all_keeps_a_file_the_user_edited_but_still_unsets_the_line(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        state, _ = self.apply(tmp_path, "include")
        carter = carter_gitconfig_path(tmp_path)
        carter.write_text(carter.read_text() + "[user]\n\tname = mine\n")
        res = gc.remove_all(tmp_path, state)
        assert carter.exists() and res.files.kept == [str(carter)]
        assert includes(global_cfg) == []

    def test_remove_all_with_nothing_recorded_is_a_no_op(
        self, tmp_path: Path, global_cfg: Path
    ) -> None:
        before = global_cfg.read_bytes()
        res = gc.remove_all(tmp_path, GuardState())
        assert global_cfg.read_bytes() == before and res.include is None

    def test_remove_all_undoes_direct_mode(self, tmp_path: Path, global_cfg: Path) -> None:
        state, _ = self.apply(tmp_path, "direct")
        gc.remove_all(tmp_path, state)
        assert git("config", "--file", str(global_cfg), "--get", "carter.tier").returncode == 1
        assert state.git_config == []

    def test_the_real_global_config_path_is_never_the_default_in_tests(
        self, global_cfg: Path, real_home: Path
    ) -> None:
        assert not gc.global_config_path().is_relative_to(real_home)


class TestKeys:
    def test_no_key_is_written_without_a_consent(self) -> None:
        assert gc.carter_git_entries() == []
