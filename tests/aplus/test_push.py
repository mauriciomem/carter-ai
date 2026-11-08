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
from carter.aplus import push, run
from carter.aplus.push import OWN_TERMINAL
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


def push_cli(*args: str, env: dict[str, str] | None = None) -> Result:
    return CliRunner().invoke(main, ["push", *args], env=env)


def remote_refs(repo: Path) -> str:
    return git("ls-remote", "--heads", "origin", cwd=repo).stdout


def net_calls(calls: Calls) -> list[str]:
    return [args[0] for kind, args in calls if kind == "net"]


class TestRefusals:
    def test_an_agent_shell_is_refused_before_any_git_call(
        self, work: Path, calls: Calls, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCODE_SESSION_ID", "s1")
        res = push_cli()
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    def test_no_terminal_is_needed(self, work: Path, human_tty: Callable[[bool], None]) -> None:
        human_tty(False)  # D68 g: OpenCode's `!` shell has no TTY, and it may run this
        res = push_cli()
        assert res.exit_code == 0, res.output
        assert "refs/heads/feat/x" in remote_refs(work)

    def test_the_human_tagged_bang_shell_may_push_but_an_agent_never(
        self, work: Path, calls: Calls
    ) -> None:
        bang = {"OPENCODE_SESSION_ID": "s1", "CARTER_HUMAN_SHELL": "1"}  # tagged by the plugin
        assert push_cli("--dry-run", env=bang).exit_code == 0
        both = {**bang, "CARTER_AGENT_SHELL": "1"}  # the strong marker wins over everything
        calls.clear()
        res = push_cli(env=both)
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output and calls == []
        assert "feat/x" not in remote_refs(work)

    def test_the_refusal_names_where_a_human_can_run_it(
        self, work: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("OPENCODE_SESSION_ID", "s1")
        text = push_cli().output
        assert "E-HUMAN-TERMINAL" in text and "agent shell" in text
        assert "!carter push" in OWN_TERMINAL and "not through an agent" in OWN_TERMINAL

    @pytest.mark.parametrize("extra", [["origin"], ["origin", "feat/x"], ["v1.0"], ["--", "-f"]])
    def test_positional_arguments_are_refused_before_any_git_call(
        self, work: Path, calls: Calls, extra: list[str]
    ) -> None:
        res = push_cli(*extra)
        assert res.exit_code == 1 and E_APLUS_ARGS in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    @pytest.mark.parametrize(
        "flag", ["--force", "-f", "--force-with-lease", "--tags", "--delete", "--all", "--mirror"]
    )
    def test_there_is_no_option_for_force_tags_or_anything_else(
        self, work: Path, calls: Calls, flag: str
    ) -> None:
        res = push_cli(flag)
        assert res.exit_code == 2 and "No such option" in res.output
        assert calls == [] and "feat/x" not in remote_refs(work)

    def test_help_lists_only_dry_run_and_set_upstream(self) -> None:
        out = CliRunner().invoke(main, ["push", "--help"]).output
        assert "--dry-run" in out and "--set-upstream" in out
        assert "--force" not in out and "refspec" not in out.lower().replace("no way", "")

    def test_a_detached_head_is_refused(self, work: Path, calls: Calls) -> None:
        git("checkout", "-q", "--detach", cwd=work)
        res = push_cli()
        assert res.exit_code == 1 and E_APLUS_ARGS in res.output and "detached HEAD" in res.output
        assert net_calls(calls) == []

    def test_a_repository_without_origin_is_refused(self, work: Path, calls: Calls) -> None:
        git("remote", "rename", "origin", "upstream", cwd=work)
        res = push_cli()
        assert res.exit_code == 1 and "no remote named origin" in res.output
        assert net_calls(calls) == []

    def test_a_diverged_branch_is_refused_and_nothing_can_force_it(
        self, work: Path, tmp_path: Path, calls: Calls
    ) -> None:
        assert push_cli().exit_code == 0
        other = tmp_path / "other"
        git("clone", "-q", "--branch", "feat/x", f"file://{tmp_path / 'origin.git'}", str(other))
        commit_file(other, "theirs.txt")
        git("push", "-q", "origin", "feat/x", cwd=other)
        git("reset", "-q", "--hard", "HEAD~1", cwd=work)
        commit_file(work, "mine.txt")
        calls.clear()
        res = push_cli()
        assert res.exit_code == 1 and "non-fast-forward" in res.output
        assert "never forces" in res.output
        assert not any(a[0] == "push" for _, a in calls)
        assert (
            git("rev-parse", "feat/x", cwd=other).stdout
            == git("rev-parse", "origin/feat/x", cwd=other).stdout
        )

    def test_nothing_to_push_pushes_nothing(self, work: Path, calls: Calls) -> None:
        assert push_cli().exit_code == 0
        calls.clear()
        res = push_cli()
        assert res.exit_code == 0 and "up to date" in res.output
        assert "push" not in net_calls(calls)

    def test_a_new_branch_without_commits_is_nothing_to_push(
        self, with_origin: Path, calls: Calls, monkeypatch, human_tty
    ) -> None:
        git("checkout", "-q", "-b", "feat/empty", cwd=with_origin)
        monkeypatch.chdir(with_origin)
        human_tty(True)
        res = push_cli()
        assert res.exit_code == 0 and "up to date" in res.output
        assert "push" not in net_calls(calls)

    def test_a_broken_carter_config_refuses_before_the_network(
        self, work: Path, calls: Calls, home_dir: Path
    ) -> None:
        cfg = home_dir / ".carter" / "config.toml"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text("not = [toml")
        res = push_cli()
        assert res.exit_code == 1 and E_CONFIG in res.output
        assert net_calls(calls) == [] and "feat/x" not in remote_refs(work)


@pytest.fixture
def home_dir(_hermetic_env: Path) -> Path:
    return _hermetic_env


class TestFlow:
    def test_the_order_is_local_checks_then_fetch_then_range_then_push(
        self, work: Path, calls: Calls
    ) -> None:
        res = push_cli()
        assert res.exit_code == 0, res.output
        kinds = [(kind, args[0]) for kind, args in calls]
        first_net = kinds.index(("net", "fetch"))
        assert ("git", "config") in kinds[:first_net]  # repo-config check before any network
        assert [k for k in kinds[:first_net] if k[0] == "net"] == []
        assert kinds.index(("git", "rev-list")) > first_net  # the range after the fetch
        assert kinds[-1] == ("net", "push") and kinds.count(("net", "push")) == 1
        assert net_calls(calls) == ["fetch", "push"]

    def test_fetch_and_push_arguments_are_exactly_these(self, work: Path, calls: Calls) -> None:
        push_cli()
        nets = [a for kind, a in calls if kind == "net"]
        assert nets[0] == (
            "fetch", "--no-tags", "--no-recurse-submodules", "origin",
            "+refs/heads/feat/x:refs/remotes/origin/feat/x",
        )  # fmt: skip
        assert nets[1] == ("push", "--recurse-submodules=no", "origin", "HEAD:refs/heads/feat/x")

    def test_it_pushes_without_asking(self, work: Path) -> None:
        res = push_cli()
        assert res.exit_code == 0, res.output
        assert "refs/heads/feat/x" in remote_refs(work)
        assert git("rev-parse", "HEAD", cwd=work).stdout.split()[0] in remote_refs(work)
        assert res.output == "✓ feat/x → origin · 1 commit (unsigned)\n"  # one line, nothing asked

    def test_it_shows_the_commits_the_files_and_the_signature_state(self, work: Path) -> None:
        assert "feat: add the feature" not in push_cli("--dry-run").output  # -v only
        res = push_cli("--dry-run", "-v")
        assert "1 commit" in res.output and "feat: add the feature" in res.output
        assert "unsigned" in res.output and "A feature.txt" in res.output
        assert "as of merge-base(origin/HEAD, HEAD)" in res.output

    def test_a_fast_forward_of_an_existing_branch_shows_only_the_new_commits(
        self, work: Path
    ) -> None:
        assert push_cli().exit_code == 0
        commit_file(work, "second.txt", message="fix: second")
        res = push_cli("-v")
        assert res.exit_code == 0, res.output
        assert "1 commit" in res.output and "fix: second" in res.output
        assert "feat: add the feature" not in res.output
        assert "as of origin/feat/x" in res.output

    def test_dry_run_never_pushes(self, work: Path, calls: Calls) -> None:
        res = push_cli("--dry-run")  # no input at all: a prompt would abort
        assert res.exit_code == 0, res.output
        assert "dry run: nothing pushed" in res.output
        assert "push" not in net_calls(calls) and "feat/x" not in remote_refs(work)

    def test_set_upstream_sets_it(self, work: Path) -> None:
        assert push_cli("--set-upstream").exit_code == 0
        assert git("config", "branch.feat/x.remote", cwd=work).stdout.strip() == "origin"
        assert git("config", "branch.feat/x.merge", cwd=work).stdout.strip() == "refs/heads/feat/x"

    def test_short_u_is_the_same_option(self, work: Path, calls: Calls) -> None:
        push_cli("-u")
        assert ("net", ("push", "--recurse-submodules=no", "--set-upstream", "origin",
                        "HEAD:refs/heads/feat/x")) in calls  # fmt: skip

    def test_without_the_option_no_upstream_is_set(self, work: Path) -> None:
        import subprocess

        push_cli()
        probe = subprocess.run(
            ["git", "config", "--get", "branch.feat/x.remote"], cwd=work, capture_output=True
        )
        assert probe.returncode == 1


class TestDefaultBranch:
    """D68 f reverses D63: the default branch is pushed like any other, with no typed name."""

    def test_it_is_pushed_without_asking(self, with_origin: Path, monkeypatch, human_tty) -> None:
        commit_file(with_origin, "direct.txt", message="fix: straight to main")
        monkeypatch.chdir(with_origin)
        human_tty(True)
        res = push_cli()
        assert res.exit_code == 0, res.output
        remote = git("rev-parse", "main", cwd=with_origin).stdout
        out = git("ls-remote", "origin", "refs/heads/main", cwd=with_origin).stdout
        assert out.split()[0] == remote.strip()
        assert "default branch" not in res.output


class TestFindingsAreOneWarning:
    def test_a_local_ssh_command_is_one_warning_line_and_the_push_goes_on(
        self, work: Path, calls: Calls
    ) -> None:
        git("config", "core.sshCommand", "sh -c 'touch /tmp/never'", cwd=work)
        res = push_cli()
        assert res.exit_code == 0, res.output  # D68 f: a warning, not a question
        warning = [ln for ln in res.output.splitlines() if "could run code" in ln]
        assert len(warning) == 1 and "core.sshcommand" in warning[0].lower()
        assert "touch" not in res.output  # the value is never printed
        assert net_calls(calls) == ["fetch", "push"]

    def test_dry_run_with_findings_does_not_fetch(self, work: Path, calls: Calls) -> None:
        git("config", "credential.helper", "!echo hi", cwd=work)
        res = push_cli("--dry-run")
        assert res.exit_code == 0 and "credential.helper" in res.output
        assert "nothing was fetched" in res.output and net_calls(calls) == []

    def test_a_repo_hook_is_named_and_never_run_by_the_push(
        self, work: Path, tmp_path: Path
    ) -> None:
        marker = tmp_path / "hook-ran"
        hook = work / ".git" / "hooks" / "pre-push"
        hook.write_text(f"#!/bin/sh\ntouch {marker}\n")
        hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
        res = push_cli()
        assert res.exit_code == 0, res.output
        assert "pre-push" in res.output and not marker.exists()
        assert "feat/x" in remote_refs(work)

    def test_a_clean_repo_prints_one_line_and_no_warning(self, work: Path) -> None:
        res = push_cli()
        assert res.exit_code == 0 and len(res.output.splitlines()) == 1
        assert "could run code" not in res.output


class TestWhatYouAreShown:
    def test_hook_and_ci_paths_are_one_warning_line(self, work: Path) -> None:
        commit_file(work, ".husky/pre-commit", "echo hi\n")
        commit_file(work, ".github/workflows/ci.yml", "on: push\n")
        plain = push_cli("--dry-run")
        warning = [ln for ln in plain.output.splitlines() if "can run code on someone's" in ln]
        assert len(warning) == 1
        assert ".husky/pre-commit" in warning[0] and ".github/workflows/ci.yml" in warning[0]
        assert "\x1b[" not in plain.output  # piped output is plain text

    def test_ordinary_paths_do_not_trigger_the_sensitive_block(self, work: Path) -> None:
        assert "can run code" not in push_cli("--dry-run").output

    def test_control_characters_in_subjects_and_paths_are_defused(self, work: Path) -> None:
        commit_file(work, "evil\x1b[31m.txt", message="boom\x1b]0;pwned\x07 end")
        out = push_cli("--dry-run").output
        assert "\x1b" not in out and "\x07" not in out

    def test_no_branch_protection_call_or_notice(self, work: Path, calls: Calls) -> None:
        res = push_cli()
        assert res.exit_code == 0 and "protection" not in res.output  # D68 f

    def test_nothing_secret_reaches_the_output(
        self, work: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("GH_TOKEN", prefixed("ghp_", "ENVSENTINEL"))
        monkeypatch.setenv("GITHUB_TOKEN", fine_grained("ENVSENTINEL"))
        git("remote", "set-url", "origin", "https://user:URLSECRET@127.0.0.1:9/o/r.git", cwd=work)
        res = push_cli()
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
        res = push_cli()
        assert res.exit_code == 1 and "git push failed" in res.output
        assert "no thanks" in res.output and "feat/x" not in remote_refs(work)

    def test_an_unreachable_origin_is_a_clear_error(self, work: Path) -> None:
        git("remote", "set-url", "origin", f"file://{work}/nope.git", cwd=work)
        res = push_cli()
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
        assert push_cli().exit_code == 0
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
        push_cli()
        assert not marker.exists()


def test_the_unsigned_llm_commit_refusal_is_in_its_own_test_module() -> None:
    assert E_B_UNSIGNED  # see tests/aplus/test_push_integration.py (needs real ssh-keygen)
    assert os.name == "posix"
