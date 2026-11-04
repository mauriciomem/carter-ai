"""A throwaway OpenSSH rig for the opt-in ``real_ssh_agent`` tests (plan 005, steps 2-3).

Starts real ``ssh-agent`` processes under pytest's temp tree, with ``SSH_AUTH_SOCK`` unset and a
scrubbed environment; the ``rig`` fixture kills what it started and fails the test if an agent
with its socket prefix is left. The developer's agent and ``~/.ssh`` are never named. Opt-in:
``CARTER_REAL_SSH_AGENT=1``. Step 7 turns this into the shared ``real_ssh_agent`` fixture.
"""

from __future__ import annotations

import os
import pty
import re
import select
import signal
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

SSH_BIN = Path("/usr/bin")
PASSPHRASE_PHRASE = "incorrect passphrase supplied to decrypt private key"

_skip = pytest.mark.skipif(
    os.environ.get("CARTER_REAL_SSH_AGENT") != "1" or not (SSH_BIN / "ssh-agent").exists(),
    reason="opt-in: starts real ssh-agent processes (CARTER_REAL_SSH_AGENT=1, OpenSSH in /usr/bin)",
)


def real_ssh(cls: type) -> type:
    """Class decorator: the `real_ssh_agent` marker plus the opt-in skip."""
    return pytest.mark.real_ssh_agent(_skip(cls))


def classify_key(rc: int, stderr: str) -> str:
    """Reference oracle for D54: what ``ssh-keygen -y -P '' -f KEY`` means.

    Exit 0 = usable without a passphrase. Every failure is 255, so the only safe way to say
    "has a passphrase" is the (never localised) phrase; anything else is an unusable file.
    """
    if rc == 0:
        return "no-passphrase"
    if PASSPHRASE_PHRASE in stderr:
        return "passphrase"
    return "unusable"


@dataclass
class Rig:
    root: Path
    env: dict[str, str]
    pids: list[int]

    def keygen(self, name: str, kind: str = "ed25519", passphrase: str = "", *extra: str) -> Path:
        path = self.root / "keys" / name
        argv = [str(SSH_BIN / "ssh-keygen"), "-q", "-t", kind, "-N", passphrase, "-C", "spike"]
        done = subprocess.run(
            [*argv, *extra, "-f", str(path)],
            env=self.env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            check=False,
        )
        assert done.returncode == 0, done.stderr
        return path

    def run(
        self, tool: str, *args: str, sock: Path | None = None, timeout: float = 10, **env: str
    ) -> subprocess.CompletedProcess[str]:
        """Run an OpenSSH tool detached from any terminal (no /dev/tty, so no prompt)."""
        full = dict(self.env, **env)
        if sock is not None:
            full["SSH_AUTH_SOCK"] = str(sock)
        return subprocess.run(
            [str(SSH_BIN / tool), *args],
            env=full,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            timeout=timeout,
            check=False,
        )

    def start_agent(self, name: str = "agent") -> tuple[Path, int]:
        sock = self.root / "run" / f"{name}.sock"
        done = self.run("ssh-agent", "-a", str(sock), "-s")
        assert done.returncode == 0, done.stderr
        match = re.search(r"SSH_AGENT_PID=(\d+);", done.stdout)
        assert match, "ssh-agent -s must print SSH_AGENT_PID=<pid>;"
        pid = int(match.group(1))
        self.pids.append(pid)
        return sock, pid

    def add_on_pty(
        self, key: Path, sock: Path, answers: list[str], **env: str
    ) -> tuple[int | str, str]:
        """Run ``ssh-add -t 8h KEY`` on a fresh PTY, typing ``answers`` at each prompt."""
        full = dict(self.env, SSH_AUTH_SOCK=str(sock), SSH_ASKPASS_REQUIRE="never", **env)
        argv = [str(SSH_BIN / "ssh-add"), "-t", "8h", str(key)]
        pid, fd = pty.fork()
        if pid == 0:  # pragma: no cover - child
            os.execve(argv[0], argv, full)
        seen = b""
        given = 0
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], 0.2)[0]:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                _, status = os.waitpid(pid, 0)
                return os.waitstatus_to_exitcode(status), seen.decode(errors="replace")
            seen += chunk
            last_line = seen.split(b"\n")[-1]
            if re.search(rb"[Pp]assphrase[^\n]*:\s*$", last_line) and given < len(answers):
                os.write(fd, (answers[given] + "\n").encode())
                given += 1
                seen += b"<ANSWER>"
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        return "timeout", seen.decode(errors="replace")


def _alive(pid: int) -> bool:
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


@pytest.fixture
def rig(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Rig]:
    # Short root: AF_UNIX paths are limited to 104 bytes on macOS.
    root = tmp_path_factory.mktemp("ssh").resolve()
    for sub in ("keys", "run", "home"):
        (root / sub).mkdir(mode=0o700)
    env = {
        "HOME": str(root / "home"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TMPDIR": str(root / "home"),
    }
    this = Rig(root=root, env=env, pids=[])
    yield this
    for pid in this.pids:
        if _alive(pid):
            os.kill(pid, signal.SIGKILL)
    time.sleep(0.05)
    left = subprocess.run(
        ["pgrep", "-u", str(os.getuid()), "-af", "ssh-agent"], capture_output=True, text=True
    ).stdout
    assert str(root) not in left, "a test left an ssh-agent running"
