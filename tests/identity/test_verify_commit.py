"""``carter identity verify --commit REV [--quiet]`` (): one exit code the agent can read.

The commit is signed by git itself with a throwaway key; the check runs against Carter's own
``allowed_signers`` so the user's git config never matters.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from identity.test_identity_add import fake as fake  # fixtures
from identity.test_identity_add import home as home  # fixtures
from identity.test_show_verify import LOGIN, add_t2
from ssh_rig import KeyPair, real_ssh


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )


def commit(repo: Path, key: KeyPair | None, home: Path) -> None:
    if not (repo / ".git").exists():
        git(repo, "init", "-q", "-b", "main")
    (repo / "f").write_text(str(len(list(repo.iterdir()))))
    git(repo, "add", "-A")
    config = ["-c", "gpg.format=ssh", "-c", f"user.signingkey={key.path}"] if key else []
    flag = "-S" if key else "--no-gpg-sign"
    done = git(
        repo, "-c", "user.name=T", "-c", "user.email=t@e.invalid", *config,
        "commit", flag, "-q", "-m", "m",
    )  # fmt: skip
    assert done.returncode == 0, done.stderr


def verify(repo: Path, *args: str):  # type: ignore[no-untyped-def]
    import os

    cwd = os.getcwd()
    os.chdir(repo)
    try:
        return CliRunner().invoke(main, ["identity", "verify", *args], catch_exceptions=False)
    finally:
        os.chdir(cwd)


@pytest.fixture
def key(throwaway_key: Callable[..., KeyPair]) -> KeyPair:
    return throwaway_key("ed25519")


@real_ssh
@pytest.mark.usefixtures("real_ssh_keygen")
class TestVerifyCommit:
    def test_a_commit_signed_by_the_llm_key_is_good_and_quiet_prints_nothing(
        self, home: Path, fake, key: KeyPair, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, "/run/pm/agent.sock")
        commit(tmp_path, key, home)
        loud = verify(tmp_path, "--commit", "HEAD")
        assert loud.exit_code == 0 and "signed by the LLM key" in loud.output
        quiet = verify(tmp_path, "--commit", "HEAD", "--quiet")
        assert quiet.exit_code == 0 and quiet.output == ""

    def test_an_unsigned_commit_fails_with_the_reason_or_just_the_exit_code(
        self, home: Path, fake, key: KeyPair, tmp_path: Path
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, "/run/pm/agent.sock")
        commit(tmp_path, None, home)
        loud = verify(tmp_path, "--commit", "HEAD")
        assert loud.exit_code == 1 and "not signed by the LLM key" in loud.output
        assert "allowedSignersFile" not in loud.output  # the user's git config is not involved
        quiet = verify(tmp_path, "--commit", "HEAD", "-q")
        assert quiet.exit_code == 1 and quiet.output == ""

    def test_a_commit_signed_by_another_key_fails(
        self,
        home: Path,
        fake,
        key: KeyPair,
        throwaway_key: Callable[..., KeyPair],
        tmp_path: Path,
    ) -> None:  # type: ignore[no-untyped-def]
        add_t2(fake, key, "/run/pm/agent.sock")
        commit(tmp_path, throwaway_key("ed25519"), home)
        assert verify(tmp_path, "--commit", "HEAD", "-q").exit_code == 1

    def test_no_identity_or_a_bad_revision_fails_without_a_traceback(
        self, home: Path, tmp_path: Path
    ) -> None:
        git(tmp_path, "init", "-q", "-b", "main")
        done = verify(tmp_path, "--commit", "HEAD")
        assert done.exit_code == 1 and LOGIN not in done.output
        assert "no LLM signing key" in done.output
        assert verify(tmp_path, "--commit", "--output=x", "-q").exit_code in (1, 2)
