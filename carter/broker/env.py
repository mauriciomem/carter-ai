"""B's tools and per-verb child environment (RFC-0007 App C.5, freeze B1, B11, B12).

The git/gh child gets an environment **built from scratch**: nothing is copied from the server
environment except the few names below, and nothing is scrubbed. The server environment can hold
the OpenCode server password, tokens and (if OpenCode was started from an agent shell) agent
signals; the last case is refused (``E-B-POLLUTED``), never repaired.

Allow-list, by verb (all values fixed or taken from a checked source):

- both: ``PATH`` (``/usr/bin:/bin`` plus the directory of ``git``, and of ``gh`` for ``pr``),
  ``HOME`` / ``USER`` / ``LOGNAME`` (the system account entry), ``LC_ALL=C``,
  ``TMPDIR`` and ``XDG_RUNTIME_DIR`` (the server's value, only if it is an absolute path);
- ``push``: ``SSH_AUTH_SOCK`` (the server's, only a socket of ours that answers ``ssh-add -l``
  with 0 or 1) and ``PUSH_FIXED``;
- ``pr``: ``DBUS_SESSION_BUS_ADDRESS``, ``GH_CONFIG_DIR``, ``GH_HOST`` (the server's, if set) and
  ``PR_FIXED``; never ``SSH_AUTH_SOCK``.

Never: any other ``GIT_*``, ``OPENCODE_*``, ``CARTER_*``, ``GH_TOKEN``, ``GITHUB_TOKEN``,
``EDITOR``, ``VISUAL``, ``BROWSER``, ``GIT_SSH*``. ``git``, ``gh`` and ``ssh`` are absolute paths
fixed at ``carter guard install`` (and ``[identity.signing] ssh_bin_dir``); ``PATH`` is never used
to find them. No marker the guard honours is set.
"""

from __future__ import annotations

import os
import pwd
import stat
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from carter.broker import refusal
from carter.identity.errors import E_B_ARGS, E_B_NOAGENT, E_B_POLLUTED, IdentityError
from carter.identity.pollution import pollution

BASE_PATH = ("/usr/bin", "/bin")
PUSH_FIXED = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_CONFIG_NOSYSTEM": "1",
    "SSH_ASKPASS_REQUIRE": "never",
    "GIT_PAGER": "cat",
    "LC_ALL": "C",
}
PR_FIXED = {
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
    "GH_PAGER": "",
    "PAGER": "",
    "NO_COLOR": "1",
    "LC_ALL": "C",
}
FROM_SERVER_ABSOLUTE = ("TMPDIR", "XDG_RUNTIME_DIR")
PR_FROM_SERVER = ("DBUS_SESSION_BUS_ADDRESS", "GH_CONFIG_DIR", "GH_HOST")
AGENT_CHECK_TIMEOUT = 10.0


@dataclass(frozen=True)
class Tools:
    """Absolute paths, fixed at install: ``git``, ``gh`` (may be empty) and the ssh directory."""

    git: str
    gh: str
    ssh_bin_dir: str

    @property
    def ssh(self) -> str:
        return str(Path(self.ssh_bin_dir) / "ssh")

    @property
    def ssh_add(self) -> str:
        return str(Path(self.ssh_bin_dir) / "ssh-add")


def _executable(path: str) -> bool:
    return os.path.isabs(path) and os.path.isfile(path) and os.access(path, os.X_OK)


def check_tools(tools: Tools, *, need_gh: bool = False) -> None:
    """Refuse (``E-B-ARGS``) unless git, ssh (and gh) are absolute, existing executables."""
    if not _executable(tools.git):
        raise refusal(
            E_B_ARGS, "git is not an absolute executable path (run `carter guard install`)"
        )
    if not os.path.isabs(tools.ssh_bin_dir) or not _executable(tools.ssh):
        raise refusal(E_B_ARGS, "ssh_bin_dir does not hold an executable `ssh`")
    if need_gh and not _executable(tools.gh):
        raise refusal(E_B_ARGS, "gh is not installed where `carter guard install` found it")


def account_home() -> Path:
    """The home B uses for its child and for the ``~/.ssh/config`` scan: the system account entry.

    OpenSSH reads ``<passwd home>/.ssh/config`` and ignores ``$HOME`` (spike C3). There is no
    config key, argument or environment variable that changes this: user config is one more
    place to plant a hostile ssh config. Tests replace this function itself (monkeypatch)."""
    return Path(pwd.getpwuid(os.geteuid()).pw_dir)


def polluted_names(server: Mapping[str, str], home: str) -> list[str]:
    """Names (never values) that show the server environment came from an agent shell or already
    carries Carter's isolation. ``SSH_AUTH_SOCK``, D-Bus and an ordinary ``GH_CONFIG_DIR`` are
    normal; ``GH_TOKEN``/``GITHUB_TOKEN`` are not passed and only a ``check --host`` warning."""
    return pollution(server, home)


def refuse_polluted(server: Mapping[str, str], home: str) -> None:
    names = polluted_names(server, home)
    if names:
        raise refusal(E_B_POLLUTED, "names: " + ", ".join(names), names=", ".join(names))


def agent_socket(server: Mapping[str, str], tools: Tools) -> str:
    """The server's ``SSH_AUTH_SOCK`` if it is a socket owned by us that answers ``ssh-add -l``
    with 0 or 1; otherwise ``E-B-NOAGENT`` (a stale or foreign socket, or no agent)."""
    sock = server.get("SSH_AUTH_SOCK", "")
    if not sock or not os.path.isabs(sock):
        raise refusal(E_B_NOAGENT, "SSH_AUTH_SOCK is not set to an absolute path")
    try:
        st = os.stat(sock)
    except OSError as exc:
        raise refusal(E_B_NOAGENT, "SSH_AUTH_SOCK does not exist") from exc
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid != os.geteuid():
        raise refusal(E_B_NOAGENT, "SSH_AUTH_SOCK is not a socket of yours")
    try:
        done = subprocess.run(
            [tools.ssh_add, "-l"],
            env={"SSH_AUTH_SOCK": sock, "PATH": ":".join(BASE_PATH)},
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=AGENT_CHECK_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise refusal(E_B_NOAGENT, "ssh-add could not ask the agent") from exc
    if done.returncode not in (0, 1):
        raise refusal(E_B_NOAGENT, f"the agent did not answer (ssh-add exit {done.returncode})")
    return sock


def _path_value(tools: Tools, verb: str) -> str:
    dirs = [*BASE_PATH, str(Path(tools.git).parent)]
    if verb == "pr" and tools.gh:
        dirs.append(str(Path(tools.gh).parent))
    return ":".join(dict.fromkeys(dirs))


def child_env(
    verb: str,
    server: Mapping[str, str],
    tools: Tools,
    home: Path,
    *,
    ssh_auth_sock: str | None = None,
) -> dict[str, str]:
    """The environment of the git (push) or gh (pr) child, from scratch.

    ``ssh_auth_sock`` must come from ``agent_socket`` and is used for ``push`` only."""
    if verb not in ("push", "pr"):
        raise IdentityError(E_B_ARGS, detail="unknown verb")
    account = pwd.getpwuid(os.geteuid()).pw_name
    env = {"PATH": _path_value(tools, verb), "HOME": str(home), "USER": account, "LOGNAME": account}
    for name in FROM_SERVER_ABSOLUTE:
        value = server.get(name, "")
        if value and os.path.isabs(value):
            env[name] = value
    if verb == "push":
        env.update(PUSH_FIXED)
        if ssh_auth_sock:
            env["SSH_AUTH_SOCK"] = ssh_auth_sock
    else:
        env.update(PR_FIXED)
        env.update({n: server[n] for n in PR_FROM_SERVER if server.get(n)})
    return env
