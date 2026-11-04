"""The ``real_ssh_agent`` fixtures are safe to use (plan 005, step 7).

Throwaway keys, one dedicated agent under a short base directory, a PTY driver that scrubs what
it types, a reaper that cannot be cheated, and a proof that the real ``$SSH_AUTH_SOCK`` and
``~/.ssh`` are out of reach. Nothing here touches the developer's agent: the real socket is only
ever named (never opened) and only ``lstat``-ed.
"""

from __future__ import annotations

import builtins
import os
import socket
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

import host_guard
from sentinels import passphrase
from ssh_rig import (
    BASE_PREFIX,
    PASSPHRASE_PROMPT,
    SSH_BIN,
    AgentHandle,
    KeyPair,
    Rig,
    alive,
    pty_run,
    real_ssh,
    ssh_agents,
    stop,
    stop_orphans,
)

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parent


@real_ssh
class TestThrowawayKeys:
    @pytest.mark.parametrize("kind", ["ed25519", "ecdsa", "rsa"])
    def test_a_key_comes_with_its_blob_and_fingerprint(self, throwaway_key: Any, kind: str) -> None:
        key: KeyPair = throwaway_key(kind)
        assert key.path.exists() and key.pub_path.exists()
        assert key.blob.split()[0].startswith(("ssh-", "ecdsa-")) and len(key.blob.split()) == 2
        assert key.fingerprint.startswith("SHA256:")
        assert key.passphrase is None
        done = subprocess.run(
            [str(SSH_BIN / "ssh-keygen"), "-y", "-P", "", "-f", str(key.path)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert done.returncode == 0  # D54: exit 0 means no passphrase

    def test_a_passphrase_key_uses_a_runtime_sentinel(self, throwaway_key: Any) -> None:
        key: KeyPair = throwaway_key("ed25519", True)
        assert key.passphrase and key.passphrase.startswith("pw-SENTINEL-")
        done = subprocess.run(
            [str(SSH_BIN / "ssh-keygen"), "-y", "-P", "", "-f", str(key.path)],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        assert done.returncode != 0  # every failure is 255: only "rc 0" means no passphrase

    def test_the_sentinel_is_not_a_literal_of_the_source(self) -> None:
        assert passphrase() != passphrase()
        assert "pw-SENTINEL-" not in Path(__file__).read_text().replace('pw-SENTINEL-"', "")


@real_ssh
class TestRealSshAgent:
    def test_the_socket_is_private_and_short(self, real_ssh_agent: AgentHandle) -> None:
        sock = real_ssh_agent.sock
        assert str(sock).startswith("/tmp/") and f"/{BASE_PREFIX}{os.getpid()}-" in str(sock)
        assert len(str(sock)) < 60  # macOS sun_path is 104; leave room for the base
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700
        assert stat.S_ISSOCK(sock.stat().st_mode)

    def test_the_environment_names_only_the_test_agent(
        self, real_ssh_agent: AgentHandle, real_ssh_auth_sock: str | None
    ) -> None:
        env = real_ssh_agent.env
        assert env["SSH_AUTH_SOCK"] == str(real_ssh_agent.sock)
        assert env["SSH_AUTH_SOCK"] != real_ssh_auth_sock
        assert not {"SSH_AGENT_PID", "SSH_ASKPASS", "DISPLAY"} & set(env)
        assert "SSH_AUTH_SOCK" not in os.environ  # the hermetic fixture cleared the real one

    def test_add_list_and_kill(self, real_ssh_agent: AgentHandle, throwaway_key: Any) -> None:
        assert real_ssh_agent.list()[0] == 1  # no identities yet
        plain: KeyPair = throwaway_key("ed25519")
        locked: KeyPair = throwaway_key("ed25519", True)
        assert real_ssh_agent.add(plain) == 0
        assert real_ssh_agent.add(locked) == 0  # through a PTY with its sentinel
        rc, out = real_ssh_agent.list()
        assert rc == 0 and plain.fingerprint in out and locked.fingerprint in out
        real_ssh_agent.kill()
        assert not alive(real_ssh_agent.pid)
        assert not real_ssh_agent.sock.exists()  # a TERM'd agent removes its own socket

    def test_a_hard_kill_leaves_a_stale_socket_like_a_crash(
        self, real_ssh_agent: AgentHandle
    ) -> None:
        real_ssh_agent.kill(hard=True)
        assert real_ssh_agent.sock.exists()
        assert real_ssh_agent.list()[0] == 2


@real_ssh
class TestPtyDriver:
    def test_it_answers_a_passphrase_prompt_and_scrubs_the_secret(
        self, real_ssh_agent: AgentHandle, throwaway_key: Any
    ) -> None:
        key: KeyPair = throwaway_key("ed25519", True)
        assert key.passphrase
        env = {**real_ssh_agent.env, "SSH_ASKPASS_REQUIRE": "never"}
        done = pty_run(
            [str(SSH_BIN / "ssh-add"), str(key.path)],
            env,
            [(PASSPHRASE_PROMPT, key.passphrase)],
            scrub=[key.passphrase],
        )
        assert done.rc == 0
        assert "Identity added" in done.output
        assert key.passphrase not in done.output and "<ANSWER>" in done.output

    def test_a_wrong_answer_is_a_retry_and_an_empty_one_ends_it(
        self, real_ssh_agent: AgentHandle, throwaway_key: Any
    ) -> None:
        key: KeyPair = throwaway_key("ed25519", True)
        env = {**real_ssh_agent.env, "SSH_ASKPASS_REQUIRE": "never"}
        done = pty_run(
            [str(SSH_BIN / "ssh-add"), str(key.path)],
            env,
            [(PASSPHRASE_PROMPT, "wrong"), (PASSPHRASE_PROMPT, "")],
        )
        assert done.rc == 1 and "Bad passphrase" in done.output

    def test_the_child_has_a_controlling_terminal_and_the_given_env(self) -> None:
        done = pty_run(
            ["/bin/sh", "-c", 'test -t 0 && test -t 2 && echo "tty:$FOO"'],
            {"PATH": "/usr/bin:/bin", "FOO": "bar"},
            [],
        )
        assert done.rc == 0 and "tty:bar" in done.output

    def test_a_script_that_never_matches_times_out_and_stops_the_child(self) -> None:
        done = pty_run(["/bin/sh", "-c", "sleep 30"], {"PATH": "/usr/bin:/bin"}, [], timeout=0.5)
        assert done.rc == "timeout"


class TestGuardProof:
    def test_the_real_agent_socket_cannot_be_connected_to(
        self, real_ssh_auth_sock: str | None, blocked_connections: list[str]
    ) -> None:
        if not real_ssh_auth_sock:
            pytest.skip("no SSH_AUTH_SOCK in the session that runs the tests")
        client = socket.socket(socket.AF_UNIX)
        try:
            with pytest.raises(host_guard.NetworkBlockedError):
                client.connect(real_ssh_auth_sock)
        finally:
            client.close()
        assert len(blocked_connections) == 1
        blocked_connections.clear()  # the block was the point of this test

    @real_ssh
    def test_the_test_agent_socket_is_allowed(self, real_ssh_agent: AgentHandle) -> None:
        client = socket.socket(socket.AF_UNIX)
        try:
            client.settimeout(5)
            client.connect(str(real_ssh_agent.sock))  # inside the registered base
            client.sendall(bytes([0, 0, 0, 1, 11]))  # SSH2_AGENTC_REQUEST_IDENTITIES
            assert client.recv(4)  # some answer
        finally:
            client.close()

    def test_the_allow_list_is_forgotten_with_the_base(self, tmp_path: Path) -> None:
        base = tmp_path / "c2b-test"
        base.mkdir()
        host_guard.allow_unix_root(base)
        assert host_guard.is_allowed_connect(str(base / "a.sock"), socket.AF_UNIX, tmp_path / "x")
        host_guard.forget_unix_root(base)
        assert not host_guard.is_allowed_connect(
            str(base / "a.sock"), socket.AF_UNIX, tmp_path / "x"
        )

    def test_the_ssh_surface_is_only_lstat_ed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".ssh").mkdir(mode=0o700)
        (tmp_path / ".ssh" / "id_ed25519").write_text("not-a-key")
        sock = tmp_path / "agent.sock"
        sock.write_text("")

        def refuse(*_a: object, **_k: object) -> None:
            raise AssertionError("the ssh surface must never be opened")

        with monkeypatch.context() as patch:
            patch.setattr(builtins, "open", refuse)
            patch.setattr(Path, "open", refuse)
            patch.setattr(Path, "read_bytes", refuse)
            patch.setattr(Path, "read_text", refuse)
            patch.setattr(Path, "iterdir", refuse)
            before = host_guard.ssh_surface(tmp_path, str(sock))
        assert before["~/.ssh"].startswith("mode:") and before["$SSH_AUTH_SOCK"].startswith("mode:")
        assert "not-a-key" not in repr(before)
        time.sleep(0.01)
        (tmp_path / ".ssh" / "known_hosts").write_text("x")  # a normal ssh session: no change
        assert host_guard.ssh_surface(tmp_path, str(sock)) == before
        (tmp_path / ".ssh").chmod(0o755)  # a real change
        assert host_guard.ssh_surface(tmp_path, str(sock)) != before

    def test_absent_and_unset_are_reported_not_raised(self, tmp_path: Path) -> None:
        assert host_guard.ssh_surface(tmp_path, None) == {
            "~/.ssh": "absent",
            "$SSH_AUTH_SOCK": "unset",
        }

    def test_the_session_baseline_of_the_real_surface_was_taken(
        self, real_home: Path, real_ssh_auth_sock: str | None, real_ssh_surface: dict[str, str]
    ) -> None:
        assert host_guard.ssh_surface(real_home, real_ssh_auth_sock) == real_ssh_surface


@real_ssh
class TestReaper:
    def test_stop_ends_a_running_agent_and_a_stopped_one(self, rig: Rig) -> None:
        _, pid = rig.start_agent("a")
        assert alive(pid) and stop(pid) in ("term", "kill")
        assert not alive(pid)
        _, stopped = rig.start_agent("b")
        os.kill(stopped, 19)  # SIGSTOP: TERM alone would leave it pending
        assert stop(stopped, wait=0.5) in ("term", "kill") and not alive(stopped)
        assert stop(stopped) == "gone"

    def test_the_fixture_teardown_stops_what_a_test_left(self, rig: Rig) -> None:
        _, pid = rig.start_agent("leftover")
        assert pid in rig.pids  # recorded: the teardown of this very fixture will stop it

    def test_orphans_of_a_crashed_session_are_stopped(self, ssh_base: Path) -> None:
        dead = subprocess.Popen(["/bin/true"])
        dead.wait()
        gone = dead.pid
        assert not alive(gone)
        orphan_dir = Path(os.environ.get("CARTER_SSH_TMPROOT") or "/tmp") / f"{BASE_PREFIX}{gone}-o"
        orphan_dir.mkdir(mode=0o700)
        sock = orphan_dir / "a.sock"
        try:
            out = subprocess.run(
                [str(SSH_BIN / "ssh-agent"), "-a", str(sock), "-s"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                env={"PATH": "/usr/bin:/bin"},
                check=True,
            ).stdout
            pid = int(out.split("SSH_AGENT_PID=")[1].split(";")[0])
            assert alive(pid) and pid in {p for p, _ in ssh_agents()}
            assert pid in stop_orphans()
            assert not alive(pid)
        finally:
            for p, c in ssh_agents():
                if str(orphan_dir) in c:
                    stop(p)
            sock.unlink(missing_ok=True)
            orphan_dir.rmdir()


NESTED_CONFTEST = """
import sys
sys.path.insert(0, {tests!r})
from ssh_rig import _ssh_reaper, pty_driver, real_ssh_agent, rig, ssh_base, throwaway_key  # noqa
"""

NESTED_CLEAN = """
def test_agent_and_keys(real_ssh_agent, throwaway_key):
    key = throwaway_key("ed25519", True)
    assert real_ssh_agent.add(key) == 0
    assert real_ssh_agent.list()[0] == 0

def test_a_failing_test_still_cleans_up(real_ssh_agent):
    assert False, "fails on purpose"
"""

NESTED_LEAK = """
import subprocess, os

def test_starts_an_agent_outside_the_fixtures(ssh_base):
    out = subprocess.run(["/usr/bin/ssh-agent", "-a", str(ssh_base / "leak.sock"), "-s"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL,
                         env={{"PATH": "/usr/bin:/bin"}}, check=True).stdout
    assert "SSH_AGENT_PID" in out
"""


def nested(tmp_path: Path, body: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    work = tmp_path / "nested"
    work.mkdir()
    (work / "conftest.py").write_text(NESTED_CONFTEST.format(tests=str(TESTS)))
    (work / "test_nested.py").write_text(textwrap.dedent(body).format())
    root = (
        Path(os.environ.get("CARTER_SSH_TMPROOT") or "/tmp") / f"{BASE_PREFIX}nested-{os.getpid()}"
    )
    root.mkdir(mode=0o700, exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path),
        "CARTER_SSH_TMPROOT": str(root),
        "PYTHONPATH": str(TESTS),
    }
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-c", "/dev/null",
         "--rootdir", str(work), str(work)],
        cwd=work,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )  # fmt: skip
    return done, root


@real_ssh
class TestNestedRun:
    def test_fixtures_leave_nothing_behind_even_when_a_test_fails(self, tmp_path: Path) -> None:
        done, root = nested(tmp_path, NESTED_CLEAN)
        try:
            assert "1 failed, 1 passed" in done.stdout, done.stdout[-800:] + done.stderr[-400:]
            assert (
                " error" not in done.stdout.split("\n")[-2]
            )  # the summary line: no teardown error
            assert not [c for _, c in ssh_agents() if str(root) in c]
            assert list(root.iterdir()) == []  # every base directory was removed
        finally:
            for p, c in ssh_agents():
                if str(root) in c:
                    stop(p)
            if root.exists():
                for left in root.iterdir():
                    left.rmdir()
                root.rmdir()

    def test_the_session_audit_fails_the_run_and_stops_an_agent_started_outside(
        self, tmp_path: Path
    ) -> None:
        done, root = nested(tmp_path, NESTED_LEAK)
        try:
            assert done.returncode != 0, done.stdout[-800:]
            assert "tests left ssh-agent processes behind" in done.stdout + done.stderr
            assert not [c for _, c in ssh_agents() if str(root) in c]  # stopped by the audit
        finally:
            for p, c in ssh_agents():
                if str(root) in c:
                    stop(p)
            for left in root.glob("*"):
                for f in left.glob("*"):
                    f.unlink()
                left.rmdir()
            root.rmdir()
