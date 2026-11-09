# ruff: noqa: E501
"""The child environment of B, built from scratch."""

from __future__ import annotations

import os
import socket
import stat
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from carter.broker import env
from carter.identity.errors import E_B_NOAGENT, E_B_POLLUTED, IdentityError

SENTINEL = "SENTINEL-{}-do-not-leak"
FORBIDDEN = [
    "OPENCODE_SERVER_PASSWORD", "OPENCODE_SESSION_ID", "OPENCODE", "AGENT", "AI_AGENT",
    "CARTER_AGENT_SHELL", "CARTER_BROKER", "CARTER_IDENTITY", "GH_TOKEN", "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN", "EDITOR", "VISUAL", "BROWSER", "GH_BROWSER", "GIT_SSH_COMMAND",
    "GIT_SSH", "GIT_ASKPASS", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0",
    "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE", "GIT_EXEC_PATH", "GIT_AUTHOR_NAME",
    "GIT_COMMITTER_EMAIL", "PYTHONPATH", "LD_PRELOAD", "SSH_ASKPASS", "http_proxy", "NODE_OPTIONS",
    "DISPLAY", "PAGER", "XDG_CONFIG_HOME", "GIT_TRACE",
]  # fmt: skip


@pytest.fixture
def tools(tmp_path: Path) -> env.Tools:
    ssh_dir = tmp_path / "ssh-bin"
    ssh_dir.mkdir()
    for name in ("ssh", "ssh-add"):
        (ssh_dir / name).write_text("#!/bin/sh\nexit 0\n")
        (ssh_dir / name).chmod(0o755)
    git = tmp_path / "gitbin" / "git"
    gh = tmp_path / "ghbin" / "gh"
    for tool in (git, gh):
        tool.parent.mkdir()
        tool.write_text("#!/bin/sh\n")
        tool.chmod(0o755)
    return env.Tools(git=str(git), gh=str(gh), ssh_bin_dir=str(ssh_dir))


def server_with_sentinels() -> dict[str, str]:
    base = {n: SENTINEL.format(n) for n in FORBIDDEN}
    base.update(HOME="/real/home", PATH="/evil/bin:/usr/bin", LANG="en_US.UTF-8", LC_ALL="fr_FR")
    return base


@pytest.mark.parametrize("verb", ["push", "pr"])
class TestSentinels:
    def test_no_forbidden_name_and_no_sentinel_value_reaches_the_child(
        self, verb: str, tools: env.Tools, tmp_path: Path
    ) -> None:
        child = env.child_env(verb, server_with_sentinels(), tools, tmp_path, ssh_auth_sock="/s")
        assert not set(FORBIDDEN) & set(child) - {"PAGER"}
        blob = "\n".join(f"{k}={v}" for k, v in child.items())
        assert "SENTINEL" not in blob and "do-not-leak" not in blob and "/evil" not in blob

    def test_the_names_are_exactly_the_allow_list(
        self, verb: str, tools: env.Tools, tmp_path: Path
    ) -> None:
        server = {"TMPDIR": "/tmp", "XDG_RUNTIME_DIR": "/run/user/1", "GH_HOST": "h.example",
                  "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/bus", "GH_CONFIG_DIR": "/cfg"}  # fmt: skip
        child = env.child_env(verb, server, tools, tmp_path, ssh_auth_sock="/s")
        common = {"PATH", "HOME", "USER", "LOGNAME", "LC_ALL", "TMPDIR", "XDG_RUNTIME_DIR"}
        if verb == "push":
            assert set(child) == common | set(env.PUSH_FIXED) | {"SSH_AUTH_SOCK"}
        else:
            assert set(child) == common | set(env.PR_FIXED) | {
                "DBUS_SESSION_BUS_ADDRESS", "GH_CONFIG_DIR", "GH_HOST",
            }  # fmt: skip

    def test_path_is_fixed_plus_the_resolved_tool_dirs(
        self, verb: str, tools: env.Tools, tmp_path: Path
    ) -> None:
        child = env.child_env(verb, server_with_sentinels(), tools, tmp_path)
        parts = child["PATH"].split(":")
        assert parts[:2] == ["/usr/bin", "/bin"] and str(Path(tools.git).parent) in parts
        assert (str(Path(tools.gh).parent) in parts) is (verb == "pr")
        assert "/evil/bin" not in parts

    def test_home_is_the_given_account_home_not_the_server_home(
        self, verb: str, tools: env.Tools, tmp_path: Path
    ) -> None:
        assert env.child_env(verb, {"HOME": "/real/home"}, tools, tmp_path)["HOME"] == str(tmp_path)


def test_the_fixed_values_are_those_of_the_rfc(tools: env.Tools, tmp_path: Path) -> None:
    push = env.child_env("push", {}, tools, tmp_path)
    assert (push["GIT_TERMINAL_PROMPT"], push["GIT_CONFIG_NOSYSTEM"]) == ("0", "1")
    assert (push["SSH_ASKPASS_REQUIRE"], push["GIT_PAGER"], push["LC_ALL"]) == ("never", "cat", "C")
    pr = env.child_env("pr", {}, tools, tmp_path)
    assert pr["GH_PROMPT_DISABLED"] == "1" and pr["GH_NO_UPDATE_NOTIFIER"] == "1"
    assert pr["GH_PAGER"] == "" and pr["PAGER"] == ""


def test_ssh_auth_sock_is_for_push_only(tools: env.Tools, tmp_path: Path) -> None:
    assert "SSH_AUTH_SOCK" in env.child_env("push", {}, tools, tmp_path, ssh_auth_sock="/s")
    assert "SSH_AUTH_SOCK" not in env.child_env("pr", {}, tools, tmp_path, ssh_auth_sock="/s")
    assert "SSH_AUTH_SOCK" not in env.child_env("push", {"SSH_AUTH_SOCK": "/x"}, tools, tmp_path)


def test_dbus_and_gh_vars_are_for_pr_only(tools: env.Tools, tmp_path: Path) -> None:
    server = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/b", "GH_HOST": "h", "GH_CONFIG_DIR": "/c"}
    assert not {"DBUS_SESSION_BUS_ADDRESS", "GH_HOST", "GH_CONFIG_DIR"} & set(
        env.child_env("push", server, tools, tmp_path)
    )


def test_a_relative_tmpdir_is_dropped(tools: env.Tools, tmp_path: Path) -> None:
    assert "TMPDIR" not in env.child_env("push", {"TMPDIR": "tmp"}, tools, tmp_path)


class TestPollution:
    def test_agent_signals_and_isolation_values_are_refused_by_name(self) -> None:
        with pytest.raises(IdentityError) as exc:
            env.refuse_polluted({"AGENT": "1", "OPENCODE_SESSION_ID": "ses_1", "HOME": "/h"}, "/h")
        assert exc.value.code == E_B_POLLUTED
        assert "AGENT" in str(exc.value) and "ses_1" not in str(exc.value) + exc.value.detail

    def test_ordinary_desktop_values_are_not_pollution(self) -> None:
        env.refuse_polluted(
            {"SSH_AUTH_SOCK": "/run/user/1/agent", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/b",
             "GH_CONFIG_DIR": "/home/u/.config/gh", "GH_TOKEN": "x", "OPENCODE_SERVER_PASSWORD": "p"},
            "/home/u",
        )  # fmt: skip


@pytest.fixture
def agent_sock() -> Iterator[str]:
    with tempfile.TemporaryDirectory(prefix="b-env-", dir="/tmp") as directory:
        path = os.path.join(directory, "agent.sock")
        server = socket.socket(socket.AF_UNIX)
        server.bind(path)
        yield path
        server.close()


def fake_ssh_add(tools: env.Tools, code: int) -> None:
    script = Path(tools.ssh_add)
    script.write_text(f"#!/bin/sh\nexit {code}\n")
    script.chmod(0o755)


class TestAgentSocket:
    @pytest.mark.parametrize("code", [0, 1])
    def test_a_socket_of_ours_that_answers_zero_or_one_is_accepted(
        self, tools: env.Tools, agent_sock: str, code: int
    ) -> None:
        fake_ssh_add(tools, code)
        assert env.agent_socket({"SSH_AUTH_SOCK": agent_sock}, tools) == agent_sock

    def test_ssh_add_runs_with_only_the_socket_in_its_environment(
        self, tools: env.Tools, agent_sock: str, tmp_path: Path
    ) -> None:
        Path(tools.ssh_add).write_text(f"#!/bin/sh\nenv > {tmp_path}/seen\nexit 0\n")
        env.agent_socket({"SSH_AUTH_SOCK": agent_sock, "OPENCODE_SERVER_PASSWORD": "pw"}, tools)
        seen = (tmp_path / "seen").read_text()
        assert "pw" not in seen and f"SSH_AUTH_SOCK={agent_sock}" in seen

    def test_exit_two_means_the_agent_did_not_answer(
        self, tools: env.Tools, agent_sock: str
    ) -> None:
        fake_ssh_add(tools, 2)
        with pytest.raises(IdentityError) as exc:
            env.agent_socket({"SSH_AUTH_SOCK": agent_sock}, tools)
        assert exc.value.code == E_B_NOAGENT

    @pytest.mark.parametrize("how", ["unset", "relative", "missing", "regular-file"])
    def test_a_bad_socket_is_noagent(self, tools: env.Tools, tmp_path: Path, how: str) -> None:
        fake_ssh_add(tools, 0)
        regular = tmp_path / "not-a-socket"
        regular.write_text("")
        value = {"unset": None, "relative": "agent", "missing": str(tmp_path / "gone"),
                 "regular-file": str(regular)}[how]  # fmt: skip
        server = {} if value is None else {"SSH_AUTH_SOCK": value}
        with pytest.raises(IdentityError) as exc:
            env.agent_socket(server, tools)
        assert exc.value.code == E_B_NOAGENT

    def test_a_socket_owned_by_someone_else_is_refused(
        self, tools: env.Tools, agent_sock: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ssh_add(tools, 0)
        real = os.stat

        def foreign(path: str, *a: object, **k: object) -> os.stat_result:
            st = real(path, *a, **k)  # type: ignore[arg-type]
            return os.stat_result((st.st_mode, *st[1:4], st.st_uid + 1, *st[5:]))

        monkeypatch.setattr(env.os, "stat", foreign)
        with pytest.raises(IdentityError) as exc:
            env.agent_socket({"SSH_AUTH_SOCK": agent_sock}, tools)
        assert exc.value.code == E_B_NOAGENT
        assert stat.S_ISSOCK(real(agent_sock).st_mode)


class TestTools:
    def test_missing_or_relative_tools_are_refused(self, tools: env.Tools, tmp_path: Path) -> None:
        env.check_tools(tools, need_gh=True)
        for bad in (
            env.Tools("git", tools.gh, tools.ssh_bin_dir),
            env.Tools(tools.git, tools.gh, "relative"),
            env.Tools(tools.git, tools.gh, str(tmp_path / "no-ssh-here")),
        ):
            with pytest.raises(IdentityError):
                env.check_tools(bad)
        with pytest.raises(IdentityError):
            env.check_tools(env.Tools(tools.git, "", tools.ssh_bin_dir), need_gh=True)

    def test_account_home_is_the_passwd_entry_and_nothing_can_redirect_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import inspect
        import pwd

        expected = Path(pwd.getpwuid(os.geteuid()).pw_dir)
        monkeypatch.setenv("HOME", str(tmp_path))  # $HOME is what an agent could set: ignored
        assert env.account_home() == expected
        assert not inspect.signature(env.account_home).parameters  # no argument either
