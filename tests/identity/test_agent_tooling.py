"""What OpenSSH does that the dedicated signing agent relies on.

Observed on OpenSSH 10.2p1 / Linux. These tests are the
regression record for section 4.4 and report 22: they pin the exit codes and the
few stable phrases Carter's agent code is allowed to depend on.

They start real ``ssh-agent`` processes (``-m real_ssh_agent``; skipped when OpenSSH is missing)
through the shared fixtures of ``tests/ssh_rig.py``: a short ``/tmp/c2b-<pid>-*`` base, a
scrubbed environment, a reaper that fails the run if an agent is left. The developer's agent and
``~/.ssh`` are never named.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

import pytest

from ssh_rig import Rig, _alive, classify_key, real_ssh


@real_ssh
class TestPassphraseDetection:
    """Question 1: needs a safe "has a passphrase" test."""

    @pytest.mark.parametrize(
        ("kind", "extra"),
        [
            ("ed25519", ()),
            ("ecdsa", ()),
            ("rsa", ("-b", "2048")),
            ("rsa", ("-b", "2048", "-m", "PEM")),
        ],
        ids=["ed25519", "ecdsa", "rsa-openssh", "rsa-pem"],
    )
    def test_with_and_without_passphrase(self, rig: Rig, kind: str, extra: tuple[str, ...]) -> None:
        bare = rig.keygen("bare", kind, "", *extra)
        locked = rig.keygen("locked", kind, "pw-" + os.urandom(4).hex(), *extra)
        ok = rig.run("ssh-keygen", "-y", "-P", "", "-f", str(bare))
        no = rig.run("ssh-keygen", "-y", "-P", "", "-f", str(locked))
        assert (ok.returncode, classify_key(ok.returncode, ok.stderr)) == (0, "no-passphrase")
        assert ok.stdout.startswith(("ssh-", "ecdsa-"))
        assert no.returncode == 255  # every failure is 255: the exit code alone is not enough
        assert classify_key(no.returncode, no.stderr) == "passphrase"
        assert no.stdout == ""

    def test_unusable_files_are_not_mistaken_for_a_passphrase(self, rig: Rig) -> None:
        keys = rig.root / "keys"
        garbage = keys / "garbage"
        garbage.write_text("not a key\n")
        garbage.chmod(0o600)
        empty = keys / "empty"
        empty.write_text("")
        empty.chmod(0o600)
        loose = rig.keygen("loose")
        loose.chmod(0o644)
        unreadable = rig.keygen("unreadable")
        unreadable.chmod(0)
        cases = {
            "missing": keys / "nope",
            "garbage": garbage,
            "empty": empty,
            "too-open": loose,
            "directory": keys,
        }
        if os.geteuid() != 0:  # root reads mode-0 files
            cases["unreadable"] = unreadable
        try:
            for name, path in cases.items():
                done = rig.run("ssh-keygen", "-y", "-P", "", "-f", str(path))
                assert done.returncode == 255, name
                assert classify_key(done.returncode, done.stderr) == "unusable", name
        finally:
            unreadable.chmod(0o600)


@real_ssh
class TestProbe:
    """Question 2: what ``ssh-add -l`` says about the dedicated socket."""

    def test_no_socket(self, rig: Rig) -> None:
        done = rig.run("ssh-add", "-l", sock=rig.root / "run" / "none.sock")
        assert done.returncode == 2
        assert "No such file or directory" in done.stderr

    def test_live_empty_then_with_key_then_other_key(self, rig: Rig) -> None:
        sock, _ = rig.start_agent()
        empty = rig.run("ssh-add", "-l", sock=sock)
        assert (empty.returncode, empty.stdout.strip()) == (1, "The agent has no identities.")

        pw = "pw-" + os.urandom(4).hex()
        llm = rig.keygen("llm", passphrase=pw)
        other = rig.keygen("other")
        rc, out = rig.add_on_pty(llm, sock, [pw])
        assert rc == 0, out
        assert "Lifetime set to 08:00:00" in out  # -t applied; wording varies in older OpenSSH
        assert pw not in out  # the typed passphrase is never echoed

        listed = rig.run("ssh-add", "-l", sock=sock)
        fingerprints = rig.run("ssh-keygen", "-lf", f"{llm}.pub").stdout.split()[1]
        other_fp = rig.run("ssh-keygen", "-lf", f"{other}.pub").stdout.split()[1]
        assert listed.returncode == 0
        assert fingerprints in listed.stdout
        assert other_fp not in listed.stdout  # "agent up, wrong key" is told by comparing

    def test_stale_socket_after_kill(self, rig: Rig) -> None:
        sock, pid = rig.start_agent()
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.1)
        assert sock.exists()  # SIGKILL leaves the file behind
        probe = rig.run("ssh-add", "-l", sock=sock)
        assert probe.returncode == 2
        assert "Connection refused" in probe.stderr
        again = rig.run("ssh-agent", "-a", str(sock), "-s")  # cannot rebind on a stale path
        assert again.returncode == 1
        assert "Address already in use" in again.stderr

    def test_stopped_agent_hangs_the_probe_and_needs_sigkill(self, rig: Rig) -> None:
        sock, pid = rig.start_agent()
        os.kill(pid, signal.SIGSTOP)
        with pytest.raises(subprocess.TimeoutExpired):
            rig.run("ssh-add", "-l", sock=sock, timeout=1.5)  # report 22 open item 5
        os.kill(pid, signal.SIGTERM)
        time.sleep(0.3)
        assert _alive(pid)  # a stopped process keeps the pending TERM: escalate to KILL
        os.kill(pid, signal.SIGKILL)
        time.sleep(0.2)
        assert not _alive(pid)


@real_ssh
class TestAgentLifecycle:
    """Question 3: the report-22 start, lock and stop steps."""

    def test_agent_creates_a_private_socket_and_removes_it_on_term(self, rig: Rig) -> None:
        sock, pid = rig.start_agent()
        assert (sock.stat().st_mode & 0o777) == 0o600
        command = subprocess.run(
            ["ps", "-ww", "-p", str(pid), "-o", "command="], capture_output=True, text=True
        ).stdout
        assert "ssh-agent" in command
        assert str(sock) in command  # the verified-pid test
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while _alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not _alive(pid)
        assert not sock.exists()  # the agent cleans up its own socket

    def test_lock_removes_only_the_named_key_from_a_bare_blob_file(self, rig: Rig) -> None:
        sock, _ = rig.start_agent()
        keys = [rig.keygen("one"), rig.keygen("two")]
        for key in keys:
            assert rig.add_on_pty(key, sock, [])[0] == 0
        blob = rig.root / "keys" / "one.blob"
        kind, data = (rig.root / "keys" / "one.pub").read_text().split()[:2]
        blob.write_text(f"{kind} {data}\n")  # no comment, no private key needed
        removed = rig.run("ssh-add", "-d", str(blob), sock=sock)
        assert removed.returncode == 0
        again = rig.run("ssh-add", "-d", str(blob), sock=sock)
        assert again.returncode == 1  # already absent: treated as success by `lock`
        assert "agent refused operation" in again.stderr
        left = rig.run("ssh-add", "-l", sock=sock)
        assert left.returncode == 0
        two_fp = rig.run("ssh-keygen", "-lf", f"{keys[1]}.pub").stdout.split()[1]
        assert two_fp in left.stdout


@real_ssh
class TestPassphrasePrompt:
    """Questions 4 and 6: the passphrase goes between ssh-add and the terminal only."""

    def _askpass(self, rig: Rig) -> tuple[Path, Path]:
        marker = rig.root / "askpass-called"
        script = rig.root / "askpass.sh"
        script.write_text(f"#!/bin/sh\necho called >> {marker}\nexit 1\n")
        script.chmod(0o755)
        return script, marker

    def test_wrong_then_right_on_a_tty_never_uses_askpass(self, rig: Rig) -> None:
        sock, _ = rig.start_agent()
        pw = "pw-" + os.urandom(4).hex()
        key = rig.keygen("llm", passphrase=pw)
        script, marker = self._askpass(rig)
        rc, out = rig.add_on_pty(
            key, sock, ["bad-" + os.urandom(3).hex(), pw], SSH_ASKPASS=str(script), DISPLAY=":99"
        )
        assert rc == 0, out
        assert "Bad passphrase, try again" in out  # ssh-add re-prompts by itself
        assert not marker.exists()  # SSH_ASKPASS_REQUIRE=never pins the TTY path
        assert rig.run("ssh-add", "-l", sock=sock).returncode == 0

    def test_ssh_add_retries_until_an_empty_answer(self, rig: Rig) -> None:
        sock, _ = rig.start_agent()
        key = rig.keygen("llm", passphrase="pw-" + os.urandom(4).hex())
        rc, out = rig.add_on_pty(key, sock, ["w1", "w2", "w3", "w4", ""])
        assert rc == 1, out  # no retry cap: Carter must pass the terminal through, not loop
        assert out.count("Bad passphrase") == 4
        assert rig.run("ssh-add", "-l", sock=sock).returncode == 1

    def test_without_a_tty_it_prints_the_prompt_and_exits_1(self, rig: Rig) -> None:
        sock, _ = rig.start_agent()
        key = rig.keygen("llm", passphrase="pw-" + os.urandom(4).hex())
        script, marker = self._askpass(rig)
        done = rig.run(
            "ssh-add", "-t", "8h", str(key), sock=sock,
            SSH_ASKPASS_REQUIRE="never", SSH_ASKPASS=str(script), DISPLAY=":99",
        )  # fmt: skip
        assert done.returncode == 1
        assert "Enter passphrase" in done.stderr
        assert not marker.exists()

    def test_unset_require_with_display_would_call_askpass(self, rig: Rig) -> None:
        """Why ``SSH_ASKPASS_REQUIRE=never`` is mandatory, not hygiene."""
        sock, _ = rig.start_agent()
        key = rig.keygen("llm", passphrase="pw-" + os.urandom(4).hex())
        script, marker = self._askpass(rig)
        rig.run("ssh-add", str(key), sock=sock, SSH_ASKPASS=str(script), DISPLAY=":99")
        assert marker.exists()


class TestSocketPathBudget:
    """Question 5: AF_UNIX ``sun_path`` is 104 bytes on macOS; always checked, no agent needed."""

    # Real shape: /var/folders/<2 chars>/<30 chars>/T/ (with the trailing slash $TMPDIR has).
    MAC_TMPDIR = "/var/folders/ab/" + "x" * 30 + "/T/"

    def test_typical_macos_tmpdir_is_49_bytes_and_fits(self) -> None:
        assert len(self.MAC_TMPDIR) == 49
        path = f"{self.MAC_TMPDIR}carter-501/agent.sock"
        assert len(path) == 70 < 104

    @pytest.mark.parametrize(
        "path",
        [
            "/run/user/1000/carter/agent.sock",
            "/home/someone/.carter/run/agent.sock",
            "/Users/" + "u" * 20 + "/.carter/run/agent.sock",
        ],
    )
    def test_fallback_locations_fit(self, path: str) -> None:
        assert len(path.encode()) < 104


class TestOnlyARealSshAgentIsEverKilled:
    """Found by the step-29 review: a command line that merely mentions `ssh-agent` and the socket
    directory (an editor opening a file there) must not be recognised as the agent."""

    def test_the_program_must_be_ssh_agent(self) -> None:
        from carter.identity.agent_proc import is_ssh_agent

        assert is_ssh_agent("ssh-agent -a /home/u/.carter/run/agent.sock -s")
        assert is_ssh_agent("/usr/bin/ssh-agent -a /run/user/1000/carter/agent.sock -s")
        assert is_ssh_agent("/opt/my dir/bin/ssh-agent -a /x/agent.sock -s")  # spaces in the path
        assert not is_ssh_agent("vim /home/u/.carter/run/ssh-agent.notes")
        assert not is_ssh_agent("tail -f /home/u/.carter/run/ssh-agent.log")
        assert not is_ssh_agent("sh -c ssh-agent /home/u/.carter/run/x")
        assert not is_ssh_agent("/usr/bin/ssh-add -l")
        assert not is_ssh_agent("")
