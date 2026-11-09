"""The agent process helpers work on a host with no ``ps`` (a minimal container).

With ``ps`` missing, Linux falls back to ``/proc``; where there is neither, nothing is claimed to
be Carter's agent. Nothing raises.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from carter.identity import agent_proc

SOCK_DIR = "/run/user/1000/carter"


@pytest.fixture
def no_ps(monkeypatch: pytest.MonkeyPatch) -> None:
    def run(argv, **_kw):  # type: ignore[no-untyped-def]
        if argv[0] == "ps":
            raise FileNotFoundError(2, "No such file or directory", "ps")
        raise AssertionError(argv)

    monkeypatch.setattr(subprocess, "run", run)


def fake_proc(root: Path, pid: int, command: list[str], state: str = "S") -> None:
    (root / str(pid)).mkdir(parents=True)
    (root / str(pid) / "cmdline").write_bytes(b"\0".join(c.encode() for c in command) + b"\0")
    (root / str(pid) / "stat").write_text(f"{pid} (ssh agent) {state} 1 1 1 0\n")


class TestWithoutPs:
    def test_the_command_line_comes_from_proc(self, no_ps: None, tmp_path: Path) -> None:
        fake_proc(tmp_path, 4242, ["ssh-agent", "-a", f"{SOCK_DIR}/agent.sock"])
        assert agent_proc.command_of(4242, tmp_path) == f"ssh-agent -a {SOCK_DIR}/agent.sock"
        assert agent_proc.command_of(1, tmp_path) == ""

    def test_my_processes_are_listed_from_proc(self, no_ps: None, tmp_path: Path) -> None:
        fake_proc(tmp_path, 4242, ["ssh-agent", "-a", f"{SOCK_DIR}/agent.sock"])
        assert agent_proc.user_processes(tmp_path) == [
            (4242, f"ssh-agent -a {SOCK_DIR}/agent.sock")
        ]

    def test_a_host_with_neither_ps_nor_proc_lists_nothing(
        self, no_ps: None, tmp_path: Path
    ) -> None:
        assert agent_proc.user_processes(tmp_path / "missing") == []

    def test_a_live_process_is_alive_and_a_zombie_is_not(
        self, no_ps: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        assert agent_proc.alive(os.getpid())
        fake_proc(tmp_path, 4243, ["ssh-agent"], state="Z")
        assert agent_proc._proc_zombie(4243, tmp_path)
        assert not agent_proc._proc_zombie(4244, tmp_path)

    def test_an_agent_is_verified_through_proc(
        self, no_ps: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        sock = tmp_path / "agent.sock"
        pidfile = tmp_path / "agent.pid"
        monkeypatch.setattr(agent_proc, "PROC", tmp_path / "proc")
        monkeypatch.setattr(agent_proc, "command_of", lambda pid, proc=None: f"ssh-agent -a {sock}")
        pidfile.write_text("4242\n")
        assert agent_proc.verified_agent(pidfile, sock) == 4242
        monkeypatch.setattr(agent_proc, "command_of", lambda pid, proc=None: "")
        assert agent_proc.verified_agent(pidfile, sock) is None
