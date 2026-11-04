# ruff: noqa: E501
"""The lab for the B contract (plan 007 step 19): a REAL isolated OpenCode with Carter's own
``carter install`` (plugin, ``isolation.json``, per-agent denies, the Carter agents), the REAL
broker core, a fake ``ssh`` that runs ``receive-pack`` against a local bare remote, a fake ``gh``,
a fake agent socket and a scripted human who answers OpenCode's permission prompt through the API.

What stands in for the world, and only that:

- ``ssh_bin_dir`` (``[identity.signing]``, the one seam of B) holds the fake ``ssh``, a fake
  ``ssh-add`` (exit 1: "agent running, no keys"), and the real ``ssh-keygen``;
- the account home is the rig's HOME (the passwd entry belongs to the developer): the wrapper below
  replaces the resolver ``carter.broker.checks.account_home`` in-process, a seam that exists only
  in this test file (production has no config key, argument or variable for it);
- ``plugin.b_gh`` is the fake ``gh`` and ``plugin.python_path`` a wrapper that runs the same
  ``python -I -m carter.broker_cli`` but may shorten the 120 s approval timeout from a file (the
  launcher below patches the *install-time* lookups, which the shipped CLI keeps fixed);
- the root-ownership check of ``false`` (a user namespace cannot pass it, see ``g2.py``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aplus.helpers import git as _unused  # noqa: F401  (keeps the tests dir on the path)
from broker.fakes import FakeGhBin, FakeSsh, install_fake_gh, install_fake_ssh
from carter.broker import audit, counter
from carter.identity.schema import Identity, IdentityConfig, Signing
from carter.identity.writer import write_config
from e2e.g2 import CARTER_BIN, PYTHON
from e2e.harness import Rig

DEVOPS = "carter-devops"
LOGIN, UID = "llm-bot", 4242
LLM_EMAIL = f"{UID}+{LOGIN}@users.noreply.github.com"
ORIGIN = "git@github.com:o/r.git"
FORCE_PUSH = "FORCE carter_push {}"
FORCE_PR = "FORCE carter_pr {}"
HUMAN_PAUSE = 0.9  # seconds a scripted human "reads" the prompt: above the 500 ms dwell floor
LAUNCHER = (
    "import os, sys;"
    "from carter.identity import isolation as i;"
    "i.resolve_false = lambda *a, **k: '/usr/bin/false';"
    "from carter.guard import plugin as p;"
    "_find = p.find_tool;"
    "p.find_tool = lambda n, dirs=(): os.environ['CARTER_E2E_GH'] if n == 'gh' else _find(n);"
    "_paths = p.find_paths;"
    "p.find_paths = lambda **k: (os.environ['CARTER_E2E_PY'], _paths(**k)[1]);"
    "from carter.cli import main;"
    "sys.argv[0] = 'carter';"
    "main()"
)
WRAPPER = """#!/bin/sh
# python for the plugin: the broker entry may read a shorter approval timeout and resolves the
# account home to the rig's HOME (tests only)
if [ "$3" = "carter.broker_cli" ]; then
  shift 3
  exec {py} -I -c 'import os, sys
import carter.broker.plan as plan, carter.broker.execute as execute
import pathlib, carter.broker.checks as checks
checks.account_home = lambda: pathlib.Path("{home}")
try:
    ms = int(open(os.path.join("{base}", "b-timeout-ms")).read())
except OSError:
    ms = plan.TIMEOUT_MS
plan.TIMEOUT_MS = execute.TIMEOUT_MS = ms
from carter.broker_cli import main
sys.argv = ["broker"] + sys.argv[1:]
sys.exit(main())' "$@"
fi
exec {py} "$@"
"""


def run_git(repo: Path, *args: str, home: Path, check: bool = True) -> str:
    done = subprocess.run(
        ["git", *args],
        cwd=repo,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null",
             "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"},
        capture_output=True,
        text=True,
        check=check,
    )  # fmt: skip
    return done.stdout.strip()


@dataclass
class BLab:
    rig: Rig
    ssh: FakeSsh
    gh: FakeGhBin
    sockdir: Path
    wrapper: Path
    t2: tuple[str, str] | None = None  # (public key, fingerprint) when the LLM identity is set
    sessions: list[str] = field(default_factory=list)

    # --- the world ---------------------------------------------------------------------------
    @property
    def ws(self) -> Path:
        return self.rig.ws

    @property
    def home(self) -> Path:
        return self.rig.home

    @property
    def carter_dir(self) -> Path:
        return self.home / ".carter"

    def git(self, *args: str, check: bool = True) -> str:
        return run_git(self.ws, *args, home=self.home, check=check)

    def commit(self, name: str, *, llm: bool = False) -> str:
        (self.ws / name).write_text(name)
        self.git("add", name)
        if llm:
            done = subprocess.run(
                ["git", "commit", "-q", "-m", name], cwd=self.ws, capture_output=True, text=True,
                env={"HOME": str(self.home), "PATH": "/usr/bin:/bin", "GIT_CONFIG_GLOBAL": "/dev/null",
                     "GIT_COMMITTER_NAME": LOGIN, "GIT_COMMITTER_EMAIL": LLM_EMAIL},
            )  # fmt: skip
            assert done.returncode == 0, done.stderr
        else:
            self.git("commit", "-q", "-m", name)
        return self.head()

    def head(self) -> str:
        return self.git("rev-parse", "HEAD")

    def remote_ref(self, branch: str = "feat/x") -> str:
        done = subprocess.run(
            ["git", "-C", str(self.ssh.bare()), "rev-parse", "-q", "--verify", f"refs/heads/{branch}"],
            capture_output=True, text=True,
        )  # fmt: skip
        return done.stdout.strip() if done.returncode == 0 else ""

    def publish(self) -> str:
        sha = self.head()
        self.git("update-ref", "refs/remotes/origin/feat/x", sha)
        return sha

    def audit(self) -> list[dict[str, Any]]:
        return audit.read_b(self.carter_dir)

    def counted(self, root: str) -> int:
        return counter.count(root, self.carter_dir)

    def set_timeout_ms(self, ms: int | None) -> None:
        target = self.rig.base / "b-timeout-ms"
        if ms is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(str(ms))

    # --- OpenCode ----------------------------------------------------------------------------
    def session(self, agent: str = DEVOPS) -> str:
        sid = str(self.rig.api("POST", "/api/session", {"agent": agent})["data"]["id"])
        self.sessions.append(sid)
        return sid

    def say(self, sid: str, text: str) -> int:
        """Send a prompt; returns the number of tool results the model had seen before."""
        before = len(self.rig.results())
        self.rig.prompt(sid, text)
        return before

    def result(self, before: int, timeout: float = 45.0) -> str:
        return str(self.rig.wait_results(before + 1, timeout)[before]["result"])

    def pending(self) -> list[dict[str, Any]]:
        return list(self.rig.api("GET", "/api/permission/request")["data"])

    def wait_ask(self, timeout: float = 30.0) -> dict[str, Any]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            asks = self.pending()
            if asks:
                return asks[0]
            time.sleep(0.02)
        raise AssertionError("no permission request appeared")

    def reply(self, ask: dict[str, Any], decision: str, *, pause: float = HUMAN_PAUSE) -> None:
        time.sleep(pause)
        self.rig.api(
            "POST",
            f"/api/session/{ask['sessionID']}/permission/{ask['id']}/reply",
            {"decision": decision},
        )

    def wait_for(self, cond: Any, timeout: float = 20.0) -> Any:
        deadline = time.time() + timeout
        while time.time() < deadline:
            got = cond()
            if got:
                return got
            time.sleep(0.1)
        raise AssertionError("condition not met in time")

    def push(
        self, decision: str = "once", *, pause: float = HUMAN_PAUSE, sid: str | None = None
    ) -> tuple[str, dict[str, Any], str]:
        """devops calls ``carter_push``; the scripted human answers. Returns (session, ask, result)."""
        sid = sid or self.session()
        before = self.say(sid, FORCE_PUSH)
        ask = self.wait_ask()
        self.reply(ask, decision, pause=pause)
        return sid, ask, self.result(before) if decision == "once" else ""

    def refused_push(self, tool: str = FORCE_PUSH) -> str:
        """devops calls a tool that must be refused before any prompt; returns the model's text."""
        sid = self.session()
        before = self.say(sid, tool)
        text = self.result(before)
        assert not self.pending(), "a refusal must not ask the human"
        assert self.remote_ref() == "", "nothing may be pushed"
        return text

    def refused_after_commit(self) -> str:
        """devops calls the tool once more, with a fresh commit; returns the model's text."""
        self.commit(f"again-{len(self.audit())}.txt")
        sid = self.session()
        return self.result(self.say(sid, FORCE_PUSH))

    def stray_asks(self) -> list[dict[str, Any]]:
        return self.pending()

    def restart(self, **server_env: str) -> None:
        env = dict(self.rig.server_env_extra)
        env.update(server_env)
        self.rig.server_env_extra = env
        self.rig.restart()


def build_world(rig: Rig, lab: BLab) -> None:
    """The repository: ``origin`` is an SSH URL served by the fake ssh; branch ``feat/x`` is ahead."""
    bare = lab.ssh.bare()
    bare.parent.mkdir(parents=True, exist_ok=True)
    run_git(rig.ws, "init", "-q", "--bare", "-b", "main", str(bare), home=rig.home)
    run_git(rig.ws, "config", "user.name", "E2E Human", home=rig.home)
    run_git(rig.ws, "config", "user.email", "e2e-human@example.invalid", home=rig.home)
    run_git(rig.ws, "branch", "-M", "main", home=rig.home)
    run_git(rig.ws, "remote", "add", "origin", ORIGIN, home=rig.home)
    run_git(rig.ws, "push", "-q", str(bare), "main", home=rig.home)
    base = run_git(rig.ws, "rev-parse", "HEAD", home=rig.home)
    run_git(rig.ws, "update-ref", "refs/remotes/origin/main", base, home=rig.home)
    run_git(
        rig.ws,
        "symbolic-ref",
        "refs/remotes/origin/HEAD",
        "refs/remotes/origin/main",
        home=rig.home,
    )
    run_git(rig.ws, "checkout", "-q", "-b", "feat/x", home=rig.home)


def write_config_toml(lab: BLab, *, key: tuple[str, str] | None = None) -> None:
    identity = Identity(login=LOGIN, id=UID, email=LLM_EMAIL) if key else Identity()
    signing = Signing(ssh_bin_dir=str(lab.ssh.bindir))
    if key:
        signing = Signing(public_key=key[0], fingerprint=key[1], ssh_bin_dir=str(lab.ssh.bindir))
    cfg = IdentityConfig(identity=identity, signing=signing, state="current")
    lab.carter_dir.mkdir(parents=True, exist_ok=True)
    write_config(cfg, lab.carter_dir / "config.toml")
    lab.t2 = key


def make_lab(rig_factory: Any, opencode_bin: Any, plugins: dict[str, str] | None = None) -> BLab:
    sockdir = Path(tempfile.mkdtemp(prefix="b-lab-", dir="/tmp"))
    sock = sockdir / "agent.sock"
    import socket

    listener = socket.socket(socket.AF_UNIX)
    listener.bind(str(sock))
    rig = rig_factory(
        opencode=opencode_bin,
        plugins=plugins or {},
        server_env_extra={"SSH_AUTH_SOCK": str(sock), "GITHUB_TOKEN": "not-a-token"},
    )
    rig._b_listener = listener  # type: ignore[attr-defined]  # closed with the lab
    ssh = install_fake_ssh(rig.base / "ssh-bin")
    for name in ("ssh-keygen",):
        (ssh.bindir / name).symlink_to(
            next(p for p in (f"/usr/bin/{name}", f"/bin/{name}") if os.path.exists(p))
        )
    add = ssh.bindir / "ssh-add"
    add.write_text("#!/bin/sh\nexit 1\n")
    add.chmod(0o755)
    gh = install_fake_gh(rig.base / "gh-bin")
    wrapper = rig.base / "py-wrap"
    wrapper.write_text(WRAPPER.format(py=PYTHON, base=str(rig.base), home=str(rig.home)))
    wrapper.chmod(0o755)
    lab = BLab(rig, ssh, gh, sockdir, wrapper)
    done = rig.run(
        [
            "env",
            f"CARTER_E2E_GH={gh.gh}",
            f"CARTER_E2E_PY={wrapper}",
            PYTHON,
            "-c",
            LAUNCHER,
            "install",
            "--yes",
        ],
        timeout=300,
    )
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-1500:]
    iso = json.loads((rig.home / ".carter" / "isolation.json").read_text())["plugin"]
    assert (
        iso["b_enabled"] is True and iso["b_gh"] == gh.gh and iso["python_path"] == str(wrapper)
    ), iso
    for agent_file in (rig.home / ".config" / "opencode" / "agents").glob("carter-*.md"):
        # a subagent runs on its own model: point the Carter agents at the mock (the rig's HOME)
        text = agent_file.read_text()
        agent_file.write_text(re.sub(r"(?m)^model:.*$", "model: mock/mock-1", text))
    build_world(rig, lab)
    write_config_toml(lab)
    rig.restart()
    return lab


def close_lab(lab: BLab) -> None:
    lab.rig._b_listener.close()  # type: ignore[attr-defined]
    shutil.rmtree(lab.sockdir, ignore_errors=True)


__all__ = ["BLab", "CARTER_BIN", "close_lab", "make_lab", "sys"]
