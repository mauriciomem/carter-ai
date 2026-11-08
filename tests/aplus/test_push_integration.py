"""``carter push`` end to end: real git, a ``file://`` bare remote, a sandbox HOME, a real
``ssh-keygen`` for the LLM-signature rule and a real pseudo-terminal for the typed confirmation
(plan 003 step 19, App A §5 1G integration column)."""

from __future__ import annotations

import os
import pty
import select
import subprocess
import sys
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from aplus.helpers import commit_file, git
from carter.cli import main
from carter.identity.errors import E_B_UNSIGNED
from carter.identity.schema import Identity, IdentityConfig, Signing
from carter.identity.writer import write_config
from carter.install.paths import carter_config_path

LLM_EMAIL = "4242+llm-bot@users.noreply.github.com"


@pytest.fixture
def llm_keys(tmp_path: Path, ssh_keygen_dir: str) -> tuple[Path, str, str]:
    """A throwaway ed25519 key: (private path, ``type blob``, fingerprint)."""
    priv = tmp_path / "llm-key"
    subprocess.run(
        [f"{ssh_keygen_dir}/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(priv)],
        check=True,
        capture_output=True,
    )
    pub = " ".join(priv.with_suffix(".pub").read_text().split()[:2])
    listing = subprocess.run(
        [f"{ssh_keygen_dir}/ssh-keygen", "-l", "-f", str(priv.with_suffix(".pub"))],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return priv, pub, listing.split()[1]


@pytest.fixture
def t2(llm_keys: tuple[Path, str, str], ssh_keygen_dir: str) -> None:
    """A schema-2 config at T2 in the sandbox home, with the throwaway key."""
    _priv, pub, fingerprint = llm_keys
    cfg = IdentityConfig(
        identity=Identity(login="llm-bot", id=4242, email=LLM_EMAIL),
        signing=Signing(public_key=pub, fingerprint=fingerprint, ssh_bin_dir=ssh_keygen_dir),
        state="current",
    )
    write_config(cfg, carter_config_path(None))


def llm_commit(repo: Path, name: str, *, key: Path | None, bindir: str) -> str:
    (repo / name).write_text(name)
    git("add", name, cwd=repo)
    env = {"GIT_COMMITTER_EMAIL": LLM_EMAIL, "GIT_COMMITTER_NAME": "LLM Bot"}
    sign = (
        ["-c", "gpg.format=ssh", "-c", f"gpg.ssh.program={bindir}/ssh-keygen"]
        + ["-c", f"user.signingkey={key}", "commit", "-q", "-S", "-m", name]
        if key
        else ["commit", "-q", "-m", name]
    )
    git(*sign, cwd=repo, env=env)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()


@pytest.fixture
def branch(with_origin: Path, monkeypatch: pytest.MonkeyPatch, human_tty) -> Path:
    git("checkout", "-q", "-b", "feat/llm", cwd=with_origin)
    monkeypatch.chdir(with_origin)
    human_tty(True)
    return with_origin


def push_cli(*args: str, input: str | None = None):
    return CliRunner().invoke(main, ["push", *args], input=input)


def remote_has(repo: Path, branch: str) -> bool:
    return f"refs/heads/{branch}" in git("ls-remote", "--heads", "origin", cwd=repo).stdout


class TestLlmSignatures:
    def test_an_unsigned_llm_commit_is_refused_and_listed(
        self, branch: Path, t2: None, ssh_keygen_dir: str
    ) -> None:
        sha = llm_commit(branch, "a.txt", key=None, bindir=ssh_keygen_dir)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and E_B_UNSIGNED in res.output
        assert sha[:12] in res.output and "not signed" in res.output
        assert not remote_has(branch, "feat/llm")

    def test_a_dry_run_reports_the_same_refusal(
        self, branch: Path, t2: None, ssh_keygen_dir: str
    ) -> None:
        llm_commit(branch, "a.txt", key=None, bindir=ssh_keygen_dir)
        res = push_cli("--dry-run")
        assert res.exit_code == 1 and E_B_UNSIGNED in res.output

    def test_a_commit_signed_with_the_stored_key_goes_through(
        self, branch: Path, t2: None, llm_keys, ssh_keygen_dir: str
    ) -> None:
        llm_commit(branch, "a.txt", key=llm_keys[0], bindir=ssh_keygen_dir)
        res = push_cli(input="y\n")
        assert res.exit_code == 0, res.output
        assert remote_has(branch, "feat/llm")

    def test_a_commit_signed_with_some_other_key_is_refused(
        self, branch: Path, t2: None, tmp_path: Path, ssh_keygen_dir: str
    ) -> None:
        other = tmp_path / "other-key"
        subprocess.run(
            [f"{ssh_keygen_dir}/ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)],
            check=True,
            capture_output=True,
        )
        llm_commit(branch, "a.txt", key=other, bindir=ssh_keygen_dir)
        res = push_cli(input="y\n")
        assert res.exit_code == 1 and E_B_UNSIGNED in res.output
        assert not remote_has(branch, "feat/llm")

    def test_human_unsigned_commits_are_not_looked_at(
        self, branch: Path, t2: None, llm_keys, ssh_keygen_dir: str
    ) -> None:
        commit_file(branch, "human.txt", message="human work, unsigned")
        llm_commit(branch, "a.txt", key=llm_keys[0], bindir=ssh_keygen_dir)
        res = push_cli(input="y\n")
        assert res.exit_code == 0, res.output

    def test_without_an_llm_signing_key_there_is_nothing_to_check(self, branch: Path) -> None:
        git(
            "-c",
            "user.email=x@example.invalid",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "e",
            cwd=branch,
        )
        assert push_cli(input="y\n").exit_code == 0


def drive(repo: Path, answers: list[str], *args: str, timeout: float = 30.0) -> tuple[int, str]:
    """Run ``carter push`` on a real pseudo-terminal (stdin, stdout and stderr are the tty)."""
    master, slave = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", "carter.cli", "push", *args],
        cwd=repo,
        stdin=slave,
        stdout=slave,
        stderr=slave,
        env=dict(os.environ),
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    out, pending, deadline = b"", list(answers), time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.2)
            if ready:
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out += chunk
                if pending and (out.rstrip().endswith((b"[y/N]", b"to origin:"))):
                    os.write(master, pending.pop(0).encode())
            elif proc.poll() is not None:
                break
        return proc.wait(timeout=5), out.decode(errors="replace")
    finally:
        proc.kill()
        os.close(master)


class TestRealTerminal:
    def test_a_real_tty_pushes_a_feature_branch_without_asking(self, branch: Path) -> None:
        commit_file(branch, "f.txt", message="feat: real tty")
        code, out = drive(branch, [])  # nothing is typed: nothing is asked
        assert code == 0, out
        assert remote_has(branch, "feat/llm") and "feat/llm → origin" in out

    def test_the_default_branch_is_pushed_without_a_typed_name(
        self, with_origin: Path, monkeypatch
    ) -> None:
        commit_file(with_origin, "g.txt", message="fix: on main")
        code, out = drive(with_origin, [])
        assert code == 0, out
        remote = git("ls-remote", "origin", "refs/heads/main", cwd=with_origin).stdout.split()[0]
        assert remote == git("rev-parse", "main", cwd=with_origin).stdout.strip()

    def test_a_pipe_for_stdin_works_on_the_real_process(self, branch: Path) -> None:
        commit_file(branch, "p.txt", message="feat: piped")  # D68 g: no TTY is needed
        proc = subprocess.run(
            [sys.executable, "-m", "carter.cli", "push"],
            cwd=branch,
            input="",
            capture_output=True,
            text=True,
            env=dict(os.environ),
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert remote_has(branch, "feat/llm")

    def test_an_agent_shell_is_refused_on_the_real_process(self, branch: Path) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "carter.cli", "push"],
            cwd=branch,
            input="",
            capture_output=True,
            text=True,
            env={**os.environ, "CARTER_AGENT_SHELL": "1"},
        )
        assert proc.returncode == 1 and "E-HUMAN-TERMINAL" in proc.stdout + proc.stderr
        assert not remote_has(branch, "feat/llm")
