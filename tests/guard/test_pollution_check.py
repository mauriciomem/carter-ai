"""``check --host``: the OpenCode server's environment, by name only.

Fake ``environ`` bytes and fake ``ps`` output; no real process is read (an autouse fixture in
``tests/conftest.py`` blocks discovery). The macOS permission model is a step-38 item.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from carter import hostcheck_g2 as g2
from carter import serverenv
from carter.identity.isolation import GIT_SSH_COMMAND

HOME = "/home/fixture"
SENTINEL = "SECRET-VALUE-DO-NOT-PRINT-91827"


def proc_tree(tmp_path: Path, pid: int, env: dict[str, str]) -> Path:
    folder = tmp_path / "proc" / str(pid)
    folder.mkdir(parents=True)
    (folder / "environ").write_bytes(
        b"\0".join(f"{k}={v}".encode() for k, v in env.items()) + b"\0"
    )
    return tmp_path / "proc"


def check(envs: dict[int, dict[str, str] | None]):
    return g2.pollution_items(lambda: envs, HOME)


class TestPollution:
    def test_a_clean_server_is_ok_and_desktop_state_is_not_pollution(self) -> None:
        env = {
            "SSH_AUTH_SOCK": f"/run/user/1000/{SENTINEL}",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
            "GH_CONFIG_DIR": f"{HOME}/.config/gh",
            "HOME": HOME,
        }
        (item,) = check({10: env})
        assert item.level == "ok" and "its environment is clean" in item.text

    @pytest.mark.parametrize(
        "name",
        [
            "AGENT",
            "AI_AGENT",
            "OPENCODE",
            "OPENCODE_SESSION_ID",
            "CARTER_AGENT_SHELL",
            "CARTER_HUMAN_SHELL",
        ],
    )
    def test_agent_and_human_signals_are_pollution_by_name(self, name: str) -> None:
        (item,) = check({10: {name: SENTINEL}})
        assert item.level == "warn" and name in item.text and SENTINEL not in item.render()

    def test_isolation_markers_count_only_with_carters_exact_value(self) -> None:
        marker = {"GIT_SSH_COMMAND": GIT_SSH_COMMAND}
        (hit,) = check({10: marker})
        assert hit.level == "warn" and "GIT_SSH_COMMAND" in hit.text
        (other,) = check({10: {"GIT_SSH_COMMAND": "ssh -i ~/.ssh/mine"}})
        assert other.level == "ok"

    def test_a_token_in_the_server_environment_is_a_warn_by_name(self) -> None:
        items = check({10: {"GH_TOKEN": SENTINEL, "GITHUB_TOKEN": SENTINEL}})
        text = " ".join(i.render() for i in items)
        assert "GH_TOKEN, GITHUB_TOKEN" in text and SENTINEL not in text

    def test_an_unreadable_server_is_info_never_red(self) -> None:
        (item,) = check({10: None})
        assert item.level == "info" and "cannot read the environment of server 10" in item.text

    def test_no_server_running_is_info(self) -> None:
        (item,) = check({})
        assert item.level == "info" and "no running OpenCode server" in item.text

    def test_several_servers_are_reported_separately(self) -> None:
        items = check({10: {"HOME": HOME}, 11: {"AGENT": "1"}})
        assert [i.level for i in items] == ["ok", "warn"]

    def test_no_value_in_any_output_or_error(self) -> None:
        env = dict.fromkeys(("AGENT", "GH_TOKEN", "OPENCODE_SESSION_ID", "SSH_AUTH_SOCK"), SENTINEL)
        assert SENTINEL not in " ".join(i.render() + i.fix for i in check({10: env}))


class TestReadingTheServer:
    def test_linux_environ_is_read_from_proc(self, tmp_path: Path) -> None:
        proc = proc_tree(tmp_path, 42, {"AGENT": "1", "HOME": HOME, "EMPTY": ""})
        assert serverenv.read_environ(42, proc=proc) == {"AGENT": "1", "HOME": HOME, "EMPTY": ""}

    def test_macos_falls_back_to_ps_eww(self, tmp_path: Path) -> None:
        def ps(argv, **_kw):
            assert argv[:3] == ["ps", "eww", "-o"] and argv[-1] == "42"
            out = "/opt/hb/opencode serve --port 4096 AGENT=1 HOME=/Users/x PATH=/usr/bin:/bin"
            return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

        env = serverenv.read_environ(42, proc=tmp_path / "nope", runner=ps)
        assert env is not None and env["AGENT"] == "1" and env["HOME"] == "/Users/x"

    def test_an_unreadable_pid_is_none(self, tmp_path: Path) -> None:
        def ps(argv, **_kw):
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="denied")

        assert serverenv.read_environ(42, proc=tmp_path / "nope", runner=ps) is None

    def test_server_pids_come_from_ps(self) -> None:
        listing = (
            "  1 /sbin/init\n"
            "205990 /home/u/.opencode/bin/opencode serve --service\n"
            "300 /home/u/.opencode/bin/opencode serve --port 4000 --print-logs\n"
            "400 /home/u/.opencode/bin/opencode run hello\n"
            "500 vim opencode serve\n"
        )

        def ps(argv, **_kw):
            return subprocess.CompletedProcess(argv, 0, stdout=listing, stderr="")

        assert serverenv.pids_from_ps(runner=ps) == [205990, 300]

    def test_a_missing_ps_is_an_empty_list(self) -> None:
        def ps(argv, **_kw):
            raise FileNotFoundError

        assert serverenv.pids_from_ps(runner=ps) == []
