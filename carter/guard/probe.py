"""``carter check --probe``: is *this* agent shell isolated? (plan 004 step 31; RFC App B §3.)

Runs only inside an agent shell: the human asks the agent to run it, and the answer lands in the
transcript, so every line is ``PASS|FAIL|SKIP <name>`` with, at most, a fixed reason. No
environment value, token (not even a prefix) or path outside ``~/.carter`` is ever printed (S6).
The probes use Carter's own processes (git, ssh, gh), not the agent's gate. There is no GitHub
403 probe (G19): it would make Carter reopen a push route from inside an agent shell.

``run_probes`` is pure over an environment mapping and an injectable runner, so every branch is
tested without a network or a real GitHub.
"""

from __future__ import annotations

import os
import shlex
import shutil
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Runner = Callable[..., "subprocess.CompletedProcess[str]"]
Status = Literal["PASS", "FAIL", "SKIP"]
UNREACHABLE = ("could not resolve", "network is unreachable", "connection refused", "timed out")
GPG_PROGRAMS = ("gpg.program", "gpg.openpgp.program", "gpg.x509.program", "gpg.ssh.program")
GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "probe", "GIT_AUTHOR_EMAIL": "probe@example.invalid",
    "GIT_COMMITTER_NAME": "probe", "GIT_COMMITTER_EMAIL": "probe@example.invalid",
}  # fmt: skip


@dataclass(frozen=True)
class Result:
    status: Status
    name: str
    reason: str = ""

    def line(self) -> str:
        return f"{self.status} {self.name}" + (f" ({self.reason})" if self.reason else "")


def _run(
    runner: Runner, argv: list[str], env: Mapping[str, str], cwd: Path | None, timeout: float
) -> subprocess.CompletedProcess[str]:
    return runner(
        argv,
        env=dict(env),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
    )


def ssh_agent_absent(env: Mapping[str, str]) -> Result:
    present = "SSH_AUTH_SOCK" in env
    return Result("FAIL" if present else "PASS", "ssh_agent_absent")


def ssh_denied(
    env: Mapping[str, str], runner: Runner, which: Callable[[str], str | None]
) -> Result:
    """``ssh -T git@github.com`` under the shell's own ``GIT_SSH_COMMAND`` must not authenticate."""
    command = env.get("GIT_SSH_COMMAND", "")
    if not command:
        return Result("FAIL", "ssh_denied", "GIT_SSH_COMMAND is not set")
    argv = [*shlex.split(command), "-T", "git@github.com"]
    if which(argv[0]) is None:
        return Result("SKIP", "ssh_denied", "ssh not installed")
    try:
        done = _run(runner, argv, env, None, 5)
    except subprocess.TimeoutExpired:
        return Result("SKIP", "ssh_denied", "unreachable")
    except OSError:
        return Result("SKIP", "ssh_denied", "ssh could not run")
    said = (done.stdout + done.stderr).lower()
    if "successfully authenticated" in said:
        return Result("FAIL", "ssh_denied", "ssh authenticated")
    if "permission denied" in said:
        return Result("PASS", "ssh_denied")
    if any(marker in said for marker in UNREACHABLE):
        return Result("SKIP", "ssh_denied", "unreachable")
    return Result("PASS" if done.returncode != 0 else "FAIL", "ssh_denied")


def gh_pat_only(
    env: Mapping[str, str], home: Path, runner: Runner, which: Callable[[str], str | None]
) -> Result:
    """``gh`` must see ``GH_TOKEN`` and Carter's empty config dir, never a keyring or hosts.yml."""
    empty = home / ".carter" / "run" / "gh-empty"
    config = env.get("GH_CONFIG_DIR", "")
    if not config or os.path.realpath(config) != os.path.realpath(empty):
        return Result("FAIL", "gh_pat_only", "GH_CONFIG_DIR is not Carter's empty dir")
    if empty.is_dir() and any(empty.iterdir()):
        return Result("FAIL", "gh_pat_only", "the empty gh dir is not empty")
    if not env.get("GH_TOKEN"):
        return Result("FAIL", "gh_pat_only", "GH_TOKEN is not set")
    if which("gh") is None:
        return Result("SKIP", "gh_pat_only", "gh not installed")
    try:
        done = _run(runner, ["gh", "auth", "status"], env, None, 10)
    except subprocess.TimeoutExpired:
        return Result("SKIP", "gh_pat_only", "unreachable")
    except OSError:
        return Result("SKIP", "gh_pat_only", "gh could not run")
    said = (done.stdout + done.stderr).lower()
    if "(keyring)" in said or "hosts.yml" in said or "oauth_token" in said:
        return Result("FAIL", "gh_pat_only", "gh found another login")
    return Result("PASS", "gh_pat_only")


def push_refused(env: Mapping[str, str], runner: Runner) -> Result:
    """``git push --dry-run`` to a GitHub URL in a scratch repo is refused locally (``no_push``)."""
    scratch = Path(tempfile.mkdtemp(prefix="carter-probe-"))
    full = {**env, **GIT_IDENTITY}
    try:
        steps = [
            ["git", "init", "-q"],
            ["git", "remote", "add", "origin", "git@github.com:carter-probe/none.git"],
            ["git", "commit", "-q", "--allow-empty", "-m", "probe"],
        ]
        for step in steps:
            if _run(runner, step, full, scratch, 20).returncode != 0:
                return Result("FAIL", "push_refused", "the scratch repository failed")
        done = _run(
            runner,
            ["git", "push", "--dry-run", "origin", "HEAD:refs/heads/probe"],
            full,
            scratch,
            20,
        )
    except (subprocess.TimeoutExpired, OSError):
        return Result("FAIL", "push_refused", "git did not answer")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if done.returncode != 0 and "no_push" in done.stderr:
        return Result("PASS", "push_refused")
    return Result("FAIL", "push_refused", "the push was not refused locally")


def _root_owned_false(path: str) -> bool:
    try:
        st = os.stat(path)
    except OSError:
        return False
    return (
        os.path.basename(path) == "false"
        and st.st_uid == 0
        and not st.st_mode & 0o022
        and (stat.S_ISREG(st.st_mode))
    )


def commit_unsigned(env: Mapping[str, str], runner: Runner) -> Result:
    """Effective ``commit.gpgsign=false`` and the four ``gpg.*program`` are the root-owned false."""
    scratch = Path(tempfile.mkdtemp(prefix="carter-probe-"))
    try:
        _run(runner, ["git", "init", "-q"], env, scratch, 20)

        def value(key: str) -> str:
            done = _run(runner, ["git", "config", "--get", key], env, scratch, 20)
            return done.stdout.strip() if done.returncode == 0 else ""

        if value("commit.gpgsign") != "false":
            return Result("FAIL", "commit_unsigned", "commit.gpgsign is not false")
        bad = [k for k in GPG_PROGRAMS if not _root_owned_false(value(k))]
    except (subprocess.TimeoutExpired, OSError):
        return Result("FAIL", "commit_unsigned", "git did not answer")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if bad:
        return Result("FAIL", "commit_unsigned", f"{', '.join(bad)} is not the root-owned false")
    return Result("PASS", "commit_unsigned")


def agent_tagged(env: Mapping[str, str]) -> Result:
    ok = env.get("CARTER_AGENT_SHELL") == "1" and "CARTER_HUMAN_SHELL" not in env
    return Result("PASS" if ok else "FAIL", "agent_tagged")


def run_probes(
    env: Mapping[str, str],
    *,
    home: Path | None = None,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> list[Result]:
    where = home or Path.home()
    return [
        ssh_agent_absent(env),
        ssh_denied(env, runner, which),
        gh_pat_only(env, where, runner, which),
        push_refused(env, runner),
        commit_unsigned(env, runner),
        agent_tagged(env),
    ]


def exit_code(results: list[Result]) -> int:
    return 1 if any(r.status == "FAIL" for r in results) else 0
