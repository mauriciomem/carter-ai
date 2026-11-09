# ruff: noqa: E501
"""A local world for the broker's plan/exec tests: a repo whose ``origin`` is an SSH URL, a bare remote
reached through the fake ``ssh``, a fake agent socket, an account home. No network, no real key
or agent. Shared by ``test_push_plan``, ``test_push_exec``, ``test_pr`` and ``test_cli``."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
from pathlib import Path

from aplus.helpers import commit_file, git, make_repo
from broker.fakes import FakeGhBin, FakeSsh, install_fake_gh, install_fake_ssh
from carter.aplus import repocfg
from carter.broker import checks
from carter.broker.env import Tools
from carter.broker.plan import Caller
from carter.identity.schema import Broker, Identity, IdentityConfig, Signing

ORIGIN = "git@github.com:o/r.git"
LLM_EMAIL = "4242+llm-bot@users.noreply.github.com"
DEVOPS = Caller("carter-devops", "ses_child1", "ses_root1")


class World:
    def __init__(self, tmp: Path, *, signing_key: bool = False) -> None:
        self.tmp = tmp
        self.home = tmp / "acct"
        (self.home / ".ssh").mkdir(parents=True)
        self.fake: FakeSsh = install_fake_ssh(tmp / "ssh-bin")
        # the suite's tool guard shadows `ssh-keygen` on PATH; an absolute path is the real one
        real_keygen = next(
            p for p in ("/usr/bin/ssh-keygen", "/bin/ssh-keygen") if os.path.exists(p)
        )
        (self.fake.bindir / "ssh-keygen").symlink_to(real_keygen)
        self.gh: FakeGhBin = install_fake_gh(tmp / "gh-bin")
        self.sockdir = Path(tempfile.mkdtemp(prefix="b-w-", dir="/tmp"))
        self.sock_path = self.sockdir / "agent.sock"
        self._sock = socket.socket(socket.AF_UNIX)
        self._sock.bind(str(self.sock_path))
        self.set_agent_exit(1)
        self.bare = self.fake.bare()
        self.bare.parent.mkdir(parents=True)
        git("init", "-q", "--bare", "-b", "main", str(self.bare))
        self.repo = make_repo(tmp / "ws")
        git("config", "user.name", "Human", cwd=self.repo)
        git("config", "user.email", "human@example.invalid", cwd=self.repo)
        self.base_sha = commit_file(self.repo, "seed.txt")
        git("remote", "add", "origin", ORIGIN, cwd=self.repo)
        git("push", "-q", str(self.bare), "main", cwd=self.repo)
        git("update-ref", "refs/remotes/origin/main", self.base_sha, cwd=self.repo)
        git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main", cwd=self.repo)
        git("checkout", "-q", "-b", "feat/x", cwd=self.repo)
        self.key: tuple[Path, str, str] | None = None
        if signing_key:
            self.key = self._make_key()
        self.carter = tmp / "carterhome"
        self.carter.mkdir()
        self.gitconfig = self.carter / "gitconfig"
        self.gitconfig.write_text("# managed by Carter\n")
        self.cfg = self._config(min_dwell_ms=500)
        self.base_dir: Path | None = None

    # --- setup ---------------------------------------------------------------------------
    def _make_key(self) -> tuple[Path, str, str]:
        priv = self.tmp / "llm-key"
        keygen = str(self.fake.bindir / "ssh-keygen")
        subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(priv)], check=True)
        pub = " ".join(priv.with_suffix(".pub").read_text().split()[:2])
        listing = subprocess.run(
            [keygen, "-l", "-f", str(priv.with_suffix(".pub"))], check=True, capture_output=True, text=True
        ).stdout  # fmt: skip
        return priv, pub, listing.split()[1]

    def _config(self, *, min_dwell_ms: int) -> IdentityConfig:
        signing = Signing(ssh_bin_dir=str(self.fake.bindir))
        identity = Identity()
        if self.key:
            _priv, pub, fpr = self.key
            identity = Identity(login="llm-bot", id=4242, email=LLM_EMAIL)
            signing = Signing(public_key=pub, fingerprint=fpr, ssh_bin_dir=str(self.fake.bindir))
        return IdentityConfig(
            identity=identity,
            signing=signing,
            broker=Broker(min_dwell_ms=min_dwell_ms),
            state="current",
        )

    def set_agent_exit(self, code: int) -> None:
        script = self.fake.bindir / "ssh-add"
        script.write_text(f"#!/bin/sh\nexit {code}\n")
        script.chmod(0o755)

    def close(self) -> None:
        self._sock.close()
        shutil.rmtree(self.sockdir, ignore_errors=True)

    # --- accessors -----------------------------------------------------------------------
    @property
    def tools(self) -> Tools:
        return Tools(git="/usr/bin/git", gh=self.gh.gh, ssh_bin_dir=str(self.fake.bindir))

    @property
    def ctx(self) -> checks.Context:
        owned = repocfg.CarterOwned(
            include=(str(self.gitconfig),),
            fragment_dir=f"{self.gitconfig}.d",
            gitconfig_files=(str(self.gitconfig),),
        )
        return checks.Context(self.cfg, owned, self.tools, self.home, self.base_dir)

    def server_env(self, **extra: str) -> dict[str, str]:
        return {
            "SSH_AUTH_SOCK": str(self.sock_path),
            "OPENCODE_SERVER_PASSWORD": "sentinel-server-password",
            "HOME": str(self.home),
            **extra,
        }

    # --- repo helpers --------------------------------------------------------------------
    def commit(self, name: str, *, llm: bool = False, sign: bool = False) -> str:
        (self.repo / name).write_text(name)
        git("add", name, cwd=self.repo)
        env = {}
        args = ["commit", "-q", "-m", name]
        if llm:
            env = {"GIT_COMMITTER_EMAIL": LLM_EMAIL, "GIT_COMMITTER_NAME": "LLM Bot"}
        if sign:
            assert self.key
            args = [
                "-c", "gpg.format=ssh", "-c", f"gpg.ssh.program={self.fake.bindir}/ssh-keygen",
                "-c", f"user.signingkey={self.key[0]}.pub", "commit", "-q", "-S", "-m", name,
            ]  # fmt: skip
        git(*args, cwd=self.repo, env={**os.environ, **env} if env else None)
        return git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def head(self) -> str:
        return git("rev-parse", "HEAD", cwd=self.repo).stdout.strip()

    def remote_ref(self, branch: str = "feat/x") -> str:
        out = subprocess.run(
            ["git", "-C", str(self.bare), "rev-parse", "-q", "--verify", f"refs/heads/{branch}"],
            capture_output=True, text=True,
        )  # fmt: skip
        return out.stdout.strip() if out.returncode == 0 else ""

    def local_config(self, text: str) -> None:
        with (self.repo / ".git" / "config").open("a") as fh:
            fh.write(text)

    def publish(self) -> str:
        """Pretend the branch was pushed: the origin tracking ref points at HEAD (what a B push
        and `carter push` both leave behind)."""
        sha = self.head()
        git("update-ref", "refs/remotes/origin/feat/x", sha, cwd=self.repo)
        return sha
