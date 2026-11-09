"""Throwaway OpenSSH for tests: the shared ``real_ssh_agent`` fixtures .

Real ``ssh-agent``/``ssh-add``/``ssh-keygen`` run only through these fixtures, never against the
developer's agent or ``~/.ssh``:

* every agent lives under a **short** base ``/tmp/c2b-<pid>-<rand>/`` (the AF_UNIX path limit is 104
  bytes on macOS), which is registered with the network guard's unix-socket allow-list;
* the test environment never carries ``SSH_AUTH_SOCK`` of the real session; the child environment is
  built from scratch (``PATH``, ``HOME``, ``LANG``) and only names the test agent;
* the **reaper** records every agent a fixture starts, kills it at teardown (SIGTERM, then SIGKILL,
  then verifies it is gone) and the session fixture ``_ssh_reaper`` fails the run if an agent whose
  command line names this session's ``c2b-<pid>-`` base is left. At session start it also stops
  agents orphaned by a crashed earlier session (their ``c2b-<pid>-`` pid is no longer alive);
* keys are generated with the real ``ssh-keygen`` by absolute path in the base directory; the
  passphrase sentinel is built at runtime (``tests/sentinels.py``).

The tools exist on every platform Carter runs on, so there is no opt-in; the tests skip with a
reason when ``ssh-agent`` is missing. ``CARTER_SSH_TMPROOT`` moves the base (the nested-run test
uses it so it can look for leftovers in a directory of its own).
"""

from __future__ import annotations

import os
import pty
import re
import select
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

import host_guard
from sentinels import passphrase as new_passphrase

SSH_BIN = Path("/usr/bin")
PASSPHRASE_PHRASE = "incorrect passphrase supplied to decrypt private key"
PASSPHRASE_PROMPT = r"[Pp]assphrase[^\n]*:\s*$"
BASE_PREFIX = "c2b-"

_missing = not (SSH_BIN / "ssh-agent").exists()
_skip = pytest.mark.skipif(_missing, reason="OpenSSH (ssh-agent) is not installed in /usr/bin")
_matrix_skip = pytest.mark.skipif(
    _missing or os.environ.get("CARTER_SSH_MATRIX") != "1",
    reason="slow: replays 35 git scenarios with a signing agent (CARTER_SSH_MATRIX=1)",
)


def real_ssh(cls: type) -> type:
    """Class decorator: the ``real_ssh_agent`` marker plus the missing-tools skip."""
    return pytest.mark.real_ssh_agent(_skip(cls))


def signed_matrix(cls: type) -> type:
    """Class decorator for the slow signed hook-matrix replay (opt-in)."""
    return pytest.mark.real_ssh_agent(_matrix_skip(cls))


def classify_key(rc: int, stderr: str) -> str:
    """Spike-A oracle: what ``ssh-keygen -y -P '' -f KEY`` meant on OpenSSH 10.2.

    Exit 0 = no passphrase; every failure is 255 and only the phrase tells a passphrase from an
    unusable file. The product rule is *exit code only*; this stays as the record of why.
    """
    if rc == 0:
        return "no-passphrase"
    if PASSPHRASE_PHRASE in stderr:
        return "passphrase"
    return "unusable"


# --- reaper -----------------------------------------------------------------------------------


def alive(pid: int) -> bool:
    """Is ``pid`` a running (non-zombie) process?"""
    try:
        state = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        try:  # no /proc (macOS): a signal 0 probe, zombies of ours are reaped by init
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return state != "Z"


_alive = alive  # the M1 name


def ssh_agents() -> list[tuple[int, str]]:
    """(pid, command line) of every ``ssh-agent`` of this user whose command line names a ``c2b-``
    base. Listing only: it never connects to anything."""
    out = subprocess.run(
        ["ps", "-u", str(os.getuid()), "-ww", "-o", "pid=,command="],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    found = []
    for line in out.splitlines():
        pid, _, command = line.strip().partition(" ")
        if "ssh-agent" in command and f"/{BASE_PREFIX}" in command and pid.isdigit():
            found.append((int(pid), command.strip()))
    return found


def stop(pid: int, *, wait: float = 3.0) -> str:
    """SIGTERM, wait, then SIGKILL; returns ``"gone"``, ``"term"`` or ``"kill"``. Never raises."""
    if not alive(pid):
        return "gone"
    try:
        os.kill(pid, signal.SIGCONT)  # a stopped agent ignores TERM until continued
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return "gone"
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if not alive(pid):
            return "term"
        time.sleep(0.02)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        return "term"
    deadline = time.monotonic() + 2
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return "kill"


class Reaper:
    """Every agent a fixture started, so teardown can stop it and the session can audit."""

    def __init__(self) -> None:
        self.pids: list[int] = []

    def record(self, pid: int) -> None:
        self.pids.append(pid)

    def stop_all(self) -> list[int]:
        """Stop what is still running; returns the pids that had to be stopped."""
        left = [p for p in self.pids if alive(p)]
        for pid in left:
            stop(pid)
        return left


REAPER = Reaper()


def session_marker() -> str:
    return f"/{BASE_PREFIX}{os.getpid()}-"


def stop_orphans() -> list[int]:
    """Stop ``ssh-agent`` processes of crashed earlier sessions (their owner pid is gone)."""
    killed = []
    for pid, command in ssh_agents():
        match = re.search(rf"/{BASE_PREFIX}(\d+)-", command)
        if match and not alive(int(match.group(1))):
            stop(pid)
            killed.append(pid)
    return killed


@pytest.fixture(scope="session", autouse=True)
def _ssh_reaper() -> Iterator[Reaper]:
    """Start: stop orphans of crashed sessions. End: fail if this session left an agent."""
    stop_orphans()
    yield REAPER
    stray = REAPER.stop_all()
    marker = session_marker()
    left = [(p, c) for p, c in ssh_agents() if marker in c]
    for pid, _ in left:
        stop(pid)
    assert not stray and not left, f"tests left ssh-agent processes behind: {stray or left}"


# --- keys, agent, pty ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeyPair:
    path: Path
    pub_path: Path
    kind: str
    blob: str  # "type base64", no comment
    fingerprint: str  # SHA256:...
    passphrase: str | None = None  # a runtime sentinel, never a literal


@dataclass
class PtyResult:
    rc: int | str  # exit code, or "timeout"
    output: str  # the transcript with typed secrets replaced by <ANSWER>


def pty_run(
    argv: Sequence[str],
    env: dict[str, str],
    script: Sequence[tuple[str, str]],
    *,
    cwd: str | Path | None = None,
    timeout: float = 20,
    scrub: Sequence[str] = (),
) -> PtyResult:
    """Run ``argv`` on a fresh PTY (a controlling terminal) and play ``script``.

    ``script`` is a list of ``(regex, answer)`` pairs consumed in order: when the output since the
    previous answer matches ``regex`` the answer and a newline are typed. The answers never appear
    in the returned transcript (password prompts do not echo; anything else is replaced by
    ``<ANSWER>``), and every string in ``scrub`` is blanked out of it.
    """
    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - child
        if cwd:
            os.chdir(cwd)
        os.execve(argv[0], list(argv), env)
    transcript = b""
    window = b""
    step = 0
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            if not select.select([fd], [], [], 0.1)[0]:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                _, status = os.waitpid(pid, 0)
                return PtyResult(os.waitstatus_to_exitcode(status), _scrub(transcript, scrub))
            transcript += chunk
            window += chunk
            if step < len(script) and re.search(script[step][0], window.decode(errors="replace")):
                os.write(fd, (script[step][1] + "\n").encode())
                transcript += b"<ANSWER>"
                window = b""
                step += 1
        return PtyResult("timeout", _scrub(transcript, scrub))
    finally:
        if alive(pid):  # timeout: the child is still ours to stop
            try:
                os.kill(pid, signal.SIGKILL)
                os.waitpid(pid, 0)
            except (ProcessLookupError, ChildProcessError):
                pass


def _scrub(data: bytes, secrets: Sequence[str]) -> str:
    text = data.decode(errors="replace").replace("\r", "")
    for secret in secrets:
        if secret:
            text = text.replace(secret, "<SECRET>")
    return text


@dataclass
class Rig:
    root: Path
    env: dict[str, str]
    pids: list[int] = field(default_factory=list)

    def keygen(
        self,
        name: str,
        kind: str = "ed25519",
        passphrase: str = "",
        *extra: str,
        comment: str = "spike",
    ) -> Path:
        path = self.root / "keys" / name
        argv = [str(SSH_BIN / "ssh-keygen"), "-q", "-t", kind, "-N", passphrase, "-C", comment]
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
        REAPER.record(pid)
        return sock, pid

    def key(self, name: str, kind: str = "ed25519", pw: str | None = None, *extra: str) -> KeyPair:
        """A generated key with its public blob and fingerprint."""
        path = self.keygen(name, kind, pw or "", *extra)
        pub = Path(f"{path}.pub")
        text_kind, blob = pub.read_text().split()[:2]
        fp = self.run("ssh-keygen", "-lf", str(pub)).stdout.split()[1]
        return KeyPair(path, pub, text_kind, f"{text_kind} {blob}", fp, pw)

    def add_on_pty(
        self, key: Path, sock: Path, answers: list[str], **env: str
    ) -> tuple[int | str, str]:
        """Run ``ssh-add -t 8h KEY`` on a fresh PTY, typing ``answers`` at each prompt."""
        full = dict(self.env, SSH_AUTH_SOCK=str(sock), SSH_ASKPASS_REQUIRE="never", **env)
        script = [(PASSPHRASE_PROMPT, a) for a in answers]
        done = pty_run(
            [str(SSH_BIN / "ssh-add"), "-t", "8h", str(key)], full, script, scrub=answers
        )
        return done.rc, done.output


class AgentHandle:
    """The ``real_ssh_agent`` fixture value: one dedicated test agent and helpers."""

    def __init__(self, rig: Rig, sock: Path, pid: int) -> None:
        self.rig = rig
        self.sock = sock
        self.pid = pid

    @property
    def env(self) -> dict[str, str]:
        """The only environment the test agent is reachable through."""
        return {**self.rig.env, "SSH_AUTH_SOCK": str(self.sock)}

    def add(self, key: KeyPair | Path, answers: Sequence[str] = ()) -> int | str:
        """Load a key (a passphrase key through a PTY). Returns the ssh-add exit code."""
        path = key.path if isinstance(key, KeyPair) else key
        pw = list(answers) or (
            [key.passphrase] if isinstance(key, KeyPair) and key.passphrase else []
        )
        if pw:
            return self.rig.add_on_pty(path, self.sock, pw)[0]
        return self.rig.run(
            "ssh-add", str(path), sock=self.sock, SSH_ASKPASS_REQUIRE="never"
        ).returncode

    def list(self) -> tuple[int, str]:
        """``ssh-add -l``: (exit code, stdout)."""
        done = self.rig.run("ssh-add", "-l", sock=self.sock)
        return done.returncode, done.stdout

    def kill(self, *, hard: bool = False) -> None:
        """Stop the agent; ``hard`` leaves the socket file behind (SIGKILL), like a crash."""
        if hard:
            os.kill(self.pid, signal.SIGKILL)
            for _ in range(100):
                if not alive(self.pid):
                    break
                time.sleep(0.01)
        else:
            stop(self.pid)


@pytest.fixture
def pty_driver() -> Callable[..., PtyResult]:
    """``pty_driver(argv, env, script, cwd=..., timeout=..., scrub=[...]) -> PtyResult``."""
    return pty_run


@pytest.fixture
def ssh_base() -> Iterator[Path]:
    """A short base directory ``/tmp/c2b-<pid>-<rand>`` (0700), allowed for unix sockets."""
    root = Path(os.environ.get("CARTER_SSH_TMPROOT") or "/tmp")
    base = Path(tempfile.mkdtemp(prefix=f"{BASE_PREFIX}{os.getpid()}-", dir=root)).resolve()
    assert len(str(base / "run" / "agent.sock")) < 80, "keep the base short (macOS sun_path)"
    host_guard.allow_unix_root(base)
    try:
        yield base
    finally:
        host_guard.forget_unix_root(base)
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def rig(ssh_base: Path) -> Iterator[Rig]:
    for sub in ("keys", "run", "home"):
        (ssh_base / sub).mkdir(mode=0o700)
    env = {
        "HOME": str(ssh_base / "home"),
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "TMPDIR": str(ssh_base / "home"),
    }
    this = Rig(root=ssh_base, env=env)
    yield this
    this_left = [p for p in this.pids if alive(p)]
    for pid in this_left:
        stop(pid)
    assert not any(alive(p) for p in this.pids), "a test left an ssh-agent running"


@pytest.fixture
def real_ssh_agent(rig: Rig) -> AgentHandle:
    """A dedicated throwaway ``ssh-agent`` (0600 socket, 0700 directory), stopped at teardown."""
    if _missing:
        pytest.skip("OpenSSH (ssh-agent) is not installed in /usr/bin")
    sock, pid = rig.start_agent()
    return AgentHandle(rig, sock, pid)


@pytest.fixture
def throwaway_key(rig: Rig) -> Callable[..., KeyPair]:
    """``throwaway_key(kind="ed25519", passphrase=None)``: a fresh key in the base directory.

    ``passphrase=True`` generates a runtime sentinel; a string is used as given."""
    counter = iter(range(1000))

    def make(kind: str = "ed25519", passphrase: str | bool | None = None) -> KeyPair:
        pw = new_passphrase() if passphrase is True else (passphrase or None)
        extra = ("-b", "2048") if kind == "rsa" else ()
        return rig.key(f"k{next(counter)}-{kind}", kind, pw or None, *extra)

    return make
