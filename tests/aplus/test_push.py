"""``carter push`` (plan 003 step 19; RFC-0007 C.6.6): real git, a local bare ``origin``.

The only thing faked is the terminal (``human_tty``): the click layer asks one place. A call
recorder around ``carter.aplus.run`` proves the order of the git calls and that nothing
touches the network before the local checks.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from aplus.helpers import commit_file, git
from carter.aplus import protection, push, run
from carter.aplus.handoff import OWN_TERMINAL
from carter.cli import main
from carter.identity.errors import E_APLUS_ARGS, E_B_UNSIGNED, E_CONFIG, E_HUMAN_TERMINAL
from sentinels import fine_grained, prefixed

Calls = list[tuple[str, tuple[str, ...]]]


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> Calls:
    """Every ``run.git`` / ``run.network_git`` call, in order, still really executed."""
    seen: Calls = []
    real_git, real_net = run.git, run.network_git

    def git_(args, cwd, **kw):  # type: ignore[no-untyped-def]
        seen.append(("git", tuple(args)))
        return real_git(args, cwd, **kw)

    def net(args, cwd, **kw):  # type: ignore[no-untyped-def]
        seen.append(("net", tuple(args)))
        return real_net(args, cwd, **kw)

    monkeypatch.setattr(run, "git", git_)
    monkeypatch.setattr(run, "network_git", net)
    return seen


@pytest.fixture
def work(with_origin: Path, monkeypatch: pytest.MonkeyPatch, human_tty: Callable[[bool], None]):
    """A feature branch with one commit on top of a pushed ``main``, cwd = the repo."""
    git("checkout", "-q", "-b", "feat/x", cwd=with_origin)
    commit_file(with_origin, "feature.txt", message="feat: add the feature")
    monkeypatch.chdir(with_origin)
    human_tty(True)
    return with_origin


def push_cli(*args: str, input: str | None = None, color: bool = False) -> Result:
    return CliRunner().invoke(main, ["push", *args], input=input, color=color)


def remote_refs(repo: Path) -> str:
    return git("ls-remote", "--heads", "origin", cwd=repo).stdout


def net_calls(calls: Calls) -> list[str]:
    return [args[0] for kind, args in calls if kind == "net"]


class TestRefusals:
    def test_an_agent_shell_is_refused_before_any_git_call(
        self, work: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCODE_SESSION_ID", "s1")
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and f"Error: {E_HUMAN_TERMINAL}" in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    def test_no_tty_is_refused_before_any_git_call_which_also_covers_the_bang_shell(
        self, work: Path, calls: Calls, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(False)  # spike 2: an OpenCode `!` shell has no TTY either
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    def test_the_refusal_says_own_terminal_and_never_suggests_the_bang_shell(
        self, work: Path, human_tty: Callable[[bool], None]
    ) -> None:
        human_tty(False)
        text = push_cli().output
        assert "your own terminal" in text and "!carter" not in text and "! carter" not in text
        assert "own terminal" in OWN_TERMINAL and "!" not in OWN_TERMINAL

    @pytest.mark.parametrize("extra", [["origin"], ["origin", "feat/x"], ["v1.0"], ["--", "-f"]])
    def test_positional_arguments_are_refused_before_any_git_call(
        self, work: Path, calls: Calls, extra: list[str]
    ) -> None:
        res = push_cli(*extra, input="y\n")
        assert res.exit_code == 1 and f"Error: {E_APLUS_ARGS}" in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    @pytest.mark.parametrize(
        "flag", ["--force", "-f", "--force-with-lease", "--tags", "--delete", "--all", "--mirror"]
    )
    def test_there_is_no_option_for_force_tags_or_anything_else(
        self, work: Path, calls: Calls, flag: str
    ) -> None:
        res = push_cli(flag, input="y\n")
        assert res.exit_code == 2 and "No such option" in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    def test_help_lists_only_dry_run_and_set_upstream(self) -> None:
        out = CliRunner().invoke(main, ["push", "--help"]).output
        assert "--dry-run" in out and "--set-upstream" in out
        assert "--force" not in out and "refspec" not in out.lower().replace("no way", "")

    def test_a_detached_head_is_refused(self, work: Path, calls: Calls) -> None:
        git("checkout", "-q", "--detach", cwd=work)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and E_APLUS_ARGS in res.output and "detached HEAD" in res.output
        assert net_calls(calls) == []

    def test_a_repository_without_origin_is_refused(self, work: Path, calls: Calls) -> None:
        git("remote", "rename", "origin", "upstream", cwd=work)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "no remote named origin" in res.output
        assert net_calls(calls) == []

    def test_a_diverged_branch_is_refused_and_nothing_can_force_it(
        self, work: Path, tmp_path: Path, calls: Calls
    ) -> None:
        assert push_cli(input="y\n").exit_code == 0
        other = tmp_path / "other"
        git("clone", "-q", "--branch", "feat/x", f"file://{tmp_path / 'origin.git'}", str(other))
        commit_file(other, "theirs.txt")
        git("push", "-q", "origin", "feat/x", cwd=other)
        git("reset", "-q", "--hard", "HEAD~1", cwd=work)
        commit_file(work, "mine.txt")
        calls.clear()
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "non-fast-forward" in res.output
        assert "never forces" in res.output
        assert not any(a[0] == "push" for _, a in calls)
        assert (
            git("rev-parse", "feat/x", cwd=other).stdout
            == git("rev-parse", "origin/feat/x", cwd=other).stdout
        )

    def test_nothing_to_push_pushes_nothing(self, work: Path, calls: Calls) -> None:
        assert push_cli(input="y\n").exit_code == 0
        calls.clear()
        res = push_cli(input="y\n")
        assert res.exit_code == 0 and "Nothing to push" in res.output
        assert "push" not in net_calls(calls)

    def test_a_new_branch_without_commits_is_nothing_to_push(
        self, with_origin: Path, calls: Calls, monkeypatch, human_tty
    ) -> None:
        git("checkout", "-q", "-b", "feat/empty", cwd=with_origin)
        monkeypatch.chdir(with_origin)
        human_tty(True)
        res = push_cli(input="y\n")
        assert res.exit_code == 0 and "Nothing to push" in res.output
        assert "push" not in net_calls(calls)

    def test_a_broken_carter_config_refuses_before_the_network(
        self, work: Path, calls: Calls, home_dir: Path
    ) -> None:
        cfg = home_dir / ".carter" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("not = [toml")
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and f"Error: {E_CONFIG}" in res.output
        assert net_calls(calls) == [] and "feat/x" not in remote_refs(work)


@pytest.fixture
def home_dir(_hermetic_env: Path) -> Path:
    return _hermetic_env


class TestFlow:
    def test_the_order_is_local_checks_then_fetch_then_range_then_push(
        self, work: Path, calls: Calls
    ) -> None:
        res = push_cli(input="y\n")
        assert res.exit_code == 0, res.output
        kinds = [(kind, args[0]) for kind, args in calls]
        first_net = kinds.index(("net", "fetch"))
        assert ("git", "config") in kinds[:first_net]  # repo-config check before any network
        assert [k for k in kinds[:first_net] if k[0] == "net"] == []
        assert kinds.index(("git", "rev-list")) > first_net  # the range after the fetch
        assert kinds[-1] == ("net", "push") and kinds.count(("net", "push")) == 1
        assert net_calls(calls) == ["fetch", "push"]

    def test_fetch_and_push_arguments_are_exactly_these(self, work: Path, calls: Calls) -> None:
        push_cli(input="y\n")
        nets = [a for kind, a in calls if kind == "net"]
        assert nets[0] == (
            "fetch", "--no-tags", "--no-recurse-submodules", "origin",
            "+refs/heads/feat/x:refs/remotes/origin/feat/x",
        )  # fmt: skip
        assert nets[1] == ("push", "--recurse-submodules=no", "origin", "HEAD:refs/heads/feat/x")

    def test_a_confirmed_push_lands_on_origin(self, work: Path) -> None:
        res = push_cli(input="y\n")
        assert res.exit_code == 0, res.output
        assert "refs/heads/feat/x" in remote_refs(work)
        assert git("rev-parse", "HEAD", cwd=work).stdout.split()[0] in remote_refs(work)
        assert "Pushed feat/x to origin" in res.output and "carter pr" in res.output

    def test_it_shows_the_commits_the_files_and_the_signature_state(self, work: Path) -> None:
        res = push_cli("--dry-run")
        assert "1 commit(s)" in res.output and "feat: add the feature" in res.output
        assert "unsigned" in res.output and "A feature.txt" in res.output
        assert "as of merge-base(origin/HEAD, HEAD)" in res.output

    def test_a_fast_forward_of_an_existing_branch_shows_only_the_new_commits(
        self, work: Path
    ) -> None:
        assert push_cli(input="y\n").exit_code == 0
        commit_file(work, "second.txt", message="fix: second")
        res = push_cli(input="y\n")
        assert res.exit_code == 0, res.output
        assert "1 commit(s)" in res.output and "fix: second" in res.output
        assert "feat: add the feature" not in res.output
        assert "as of origin/feat/x" in res.output

    @pytest.mark.parametrize("answer", ["n\n", "\n", "yes please\n", "", "no\n"])
    def test_anything_but_y_aborts_and_pushes_nothing(
        self, work: Path, calls: Calls, answer: str
    ) -> None:
        res = push_cli(input=answer)
        assert res.exit_code == 1 and "Aborted: nothing was pushed." in res.output
        assert "push" not in net_calls(calls) and "feat/x" not in remote_refs(work)

    def test_an_uppercase_y_is_accepted(self, work: Path) -> None:
        assert push_cli(input="Y\n").exit_code == 0

    def test_dry_run_never_pushes_never_asks_and_prints_what_it_would_ask(
        self, work: Path, calls: Calls
    ) -> None:
        res = push_cli("--dry-run")  # no input at all: a prompt would abort
        assert res.exit_code == 0, res.output
        assert "Dry run: nothing was pushed. It would ask: Push feat/x to origin? [y/N]" in (
            res.output
        )
        assert "push" not in net_calls(calls) and "feat/x" not in remote_refs(work)

    def test_set_upstream_sets_it(self, work: Path) -> None:
        assert push_cli("--set-upstream", input="y\n").exit_code == 0
        assert git("config", "branch.feat/x.remote", cwd=work).stdout.strip() == "origin"
        assert git("config", "branch.feat/x.merge", cwd=work).stdout.strip() == "refs/heads/feat/x"

    def test_short_u_is_the_same_option(self, work: Path, calls: Calls) -> None:
        push_cli("-u", input="y\n")
        assert ("net", ("push", "--recurse-submodules=no", "--set-upstream", "origin",
                        "HEAD:refs/heads/feat/x")) in calls  # fmt: skip

    def test_without_the_option_no_upstream_is_set(self, work: Path) -> None:
        import subprocess

        push_cli(input="y\n")
        probe = subprocess.run(
            ["git", "config", "--get", "branch.feat/x.remote"], cwd=work, capture_output=True
        )
        assert probe.returncode == 1


class TestDefaultBranch:
    @pytest.fixture
    def on_main(self, with_origin: Path, monkeypatch, human_tty) -> Path:
        commit_file(with_origin, "direct.txt", message="fix: straight to main")
        monkeypatch.chdir(with_origin)
        human_tty(True)
        return with_origin

    def test_y_is_not_enough(self, on_main: Path, calls: Calls) -> None:
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "default branch" in res.output
        assert "Aborted: nothing was pushed." in res.output
        assert "push" not in net_calls(calls)

    def test_the_typed_branch_name_pushes(self, on_main: Path) -> None:
        res = push_cli(input="main\n")
        assert res.exit_code == 0, res.output
        remote = git("rev-parse", "main", cwd=on_main).stdout
        assert git("ls-remote", "origin", "refs/heads/main", cwd=on_main).stdout.split()[0] == (
            remote.strip()
        )

    @pytest.mark.parametrize("answer", ["", "\n", "main2\n", "MAIN\n", "origin/main\n"])
    def test_blank_eof_and_near_misses_abort(self, on_main: Path, calls: Calls, answer) -> None:
        res = push_cli(input=answer)
        assert res.exit_code == 1 and "push" not in net_calls(calls)

    def test_dry_run_prints_the_typed_prompt_without_asking(self, on_main: Path) -> None:
        res = push_cli("--dry-run")
        assert res.exit_code == 0 and "Type its name to push to origin" in res.output

    def test_an_unknown_default_branch_also_needs_the_typed_name(
        self, work: Path, calls: Calls
    ) -> None:
        git("remote", "set-head", "origin", "-d", cwd=work)  # origin/HEAD gone: default unknown
        git("branch", "-q", "feat/y", cwd=work)
        # the range needs origin/HEAD for a new branch, so use an existing remote branch
        git("push", "-q", "origin", "feat/x", cwd=work)
        commit_file(work, "more.txt")
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "Type its name" in res.output


class TestFindingsAreShownNotHidden:
    def test_a_local_ssh_command_is_shown_and_declining_stops_before_the_network(
        self, work: Path, calls: Calls
    ) -> None:
        git("config", "core.sshCommand", "sh -c 'touch /tmp/never'", cwd=work)
        res = push_cli(input="n\n")
        assert res.exit_code == 1 and "could run code with your credentials" in res.output
        assert "core.sshcommand" in res.output.lower()
        assert "touch" not in res.output  # the value is never printed
        assert net_calls(calls) == []

    def test_dry_run_with_findings_does_not_fetch(self, work: Path, calls: Calls) -> None:
        git("config", "credential.helper", "!echo hi", cwd=work)
        res = push_cli("--dry-run")
        assert res.exit_code == 0 and "credential.helper" in res.output
        assert "nothing was fetched" in res.output and net_calls(calls) == []

    def test_a_repo_hook_is_shown_and_never_run_by_the_push(
        self, work: Path, tmp_path: Path
    ) -> None:
        marker = tmp_path / "hook-ran"
        hook = work / ".git" / "hooks" / "pre-push"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        res = push_cli(input="y\ny\n")
        assert res.exit_code == 0, res.output
        assert "pre-push" in res.output and not marker.exists()
        assert "feat/x" in remote_refs(work)

    def test_findings_never_make_a_clean_repo_ask_twice(self, work: Path) -> None:
        res = push_cli(input="y\n")
        assert res.exit_code == 0 and "anyway" not in res.output


class TestWhatYouAreShown:
    def test_hook_and_ci_paths_are_listed_and_red_on_a_color_terminal(self, work: Path) -> None:
        commit_file(work, ".husky/pre-commit", "echo hi\n")
        commit_file(work, ".github/workflows/ci.yml", "on: push\n")
        plain = push_cli("--dry-run")
        assert "can run code on someone's machine" in plain.output
        assert ".husky/pre-commit" in plain.output and ".github/workflows/ci.yml" in plain.output
        colored = push_cli("--dry-run", color=True)
        assert "\x1b[" in colored.output
        clean = push_cli("--dry-run")
        assert "\x1b[" not in clean.output

    def test_ordinary_paths_do_not_trigger_the_sensitive_block(self, work: Path) -> None:
        assert "can run code" not in push_cli("--dry-run").output

    def test_control_characters_in_subjects_and_paths_are_defused(self, work: Path) -> None:
        commit_file(work, "evil\x1b[31m.txt", message="boom\x1b]0;pwned\x07 end")
        out = push_cli("--dry-run").output
        assert "\x1b" not in out and "\x07" not in out

    def test_protection_warnings_are_shown_and_do_not_block(
        self, work: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            protection,
            "branch_notes",
            lambda url, branch, base_dir=None: [
                "warning: required_signatures: the branch requires signed commits"
            ],
        )
        res = push_cli(input="y\n")
        assert res.exit_code == 0 and "requires signed commits" in res.output

    def test_an_unreachable_api_is_a_notice_not_a_failure(self, work: Path) -> None:
        res = push_cli("--dry-run")  # origin is a file:// remote: not on github.com
        assert res.exit_code == 0 and "notice: branch protection not checked" in res.output

    def test_nothing_secret_reaches_the_output(
        self, work: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", prefixed("ghp_", "ENVSENTINEL"))
        monkeypatch.setenv("GITHUB_TOKEN", fine_grained("ENVSENTINEL"))
        git("remote", "set-url", "origin", "https://user:URLSECRET@127.0.0.1:9/o/r.git", cwd=work)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "cannot fetch from origin" in res.output
        assert "URLSECRET" not in res.output and "SENTINEL" not in res.output

    def test_a_remote_with_credentials_is_shown_masked(self, work: Path) -> None:
        git("remote", "set-url", "origin", "https://user:URLSECRET@127.0.0.1:9/o/r.git", cwd=work)
        res = push_cli("--dry-run")
        assert "URLSECRET" not in res.output


class TestPushFailures:
    def test_a_rejected_push_reports_git_and_exits_1(self, work: Path, tmp_path: Path) -> None:
        hook = tmp_path / "origin.git" / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\necho 'no thanks' >&2\nexit 1\n")
        hook.chmod(0o755)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and "git push failed" in res.output
        assert "no thanks" in res.output and "feat/x" not in remote_refs(work)

    def test_an_unreachable_origin_is_a_clear_error(self, work: Path) -> None:
        git("remote", "set-url", "origin", f"file://{work}/nope.git", cwd=work)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and E_APLUS_ARGS in res.output


class TestSshHost:
    @pytest.mark.parametrize(
        ("url", "host"),
        [
            ("git@github.com:o/r.git", "github.com"),
            ("ssh://git@example.org:2222/o/r.git", "example.org"),
            ("ssh://example.org/o/r", "example.org"),
            ("git+ssh://git@h.example/o/r", "h.example"),
            ("https://github.com/o/r.git", None),
            ("file:///tmp/x.git", None),
            ("/srv/git/r.git", None),
            ("../r.git", None),
            ("git://example.org/r.git", None),
        ],
    )
    def test_only_ssh_transports_have_a_host(self, url: str, host: str | None) -> None:
        assert push.ssh_host(url) == host


class TestEnvironment:
    def test_the_push_runs_with_the_humans_credentials_in_reach_and_no_author_injection(
        self, work: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        seen: dict[str, dict[str, str]] = {}
        import subprocess

        real = subprocess.run

        def spy(argv, **kw):  # type: ignore[no-untyped-def]
            if "push" in argv:
                seen["env"] = dict(kw["env"])
                seen["argv"] = list(argv)  # type: ignore[assignment]
            return real(argv, **kw)

        monkeypatch.setenv("SSH_AUTH_SOCK", "/tmp/agent.sock")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "evil@example.invalid")
        monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
        monkeypatch.setattr(subprocess, "run", spy)
        assert push_cli(input="y\n").exit_code == 0
        env = seen["env"]
        assert env.get("SSH_AUTH_SOCK") == "/tmp/agent.sock"  # untouched: it is your agent
        assert "GIT_AUTHOR_EMAIL" not in env and "GIT_CONFIG_COUNT" not in env
        assert "core.hooksPath=" in " ".join(seen["argv"])
        assert "push.followTags=false" in seen["argv"]
        assert "credential.helper=" not in seen["argv"]

    def test_hooks_are_off_for_the_fetch_too(self, work: Path, calls: Calls) -> None:
        marker = work.parent / "fetch-hook"
        hook = work / ".git" / "hooks" / "reference-transaction"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(0o755)
        push_cli(input="y\ny\n")
        assert not marker.exists()


def test_the_unsigned_llm_commit_refusal_is_in_its_own_test_module() -> None:
    assert E_B_UNSIGNED  # see tests/aplus/test_push_integration.py (needs real ssh-keygen)
    assert os.name == "posix"
