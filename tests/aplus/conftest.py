"""Helpers for the A+ building blocks: throwaway repos under tmp, sandbox git config."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from aplus.helpers import commit_file, git, make_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = make_repo(tmp_path / "repo")
    commit_file(r, "seed.txt")
    return r


@pytest.fixture
def with_origin(tmp_path: Path, repo: Path) -> Path:
    """``repo`` pushed to a local bare ``origin`` (file://), with ``origin/HEAD`` set."""
    remote = tmp_path / "origin.git"
    git("init", "-q", "--bare", "-b", "main", str(remote))
    git("remote", "add", "origin", f"file://{remote}", cwd=repo)
    git("push", "-q", "origin", "main", cwd=repo)
    git("remote", "set-head", "origin", "main", cwd=repo)
    return repo


@pytest.fixture
def ssh_keygen_dir(real_ssh_keygen: None) -> str:
    """Directory of the real ``ssh-keygen`` (opt-in per the architect's conditions: keys are
    generated in tmp only and ``SSH_AUTH_SOCK`` stays cleared)."""
    found = shutil.which("ssh-keygen")
    if found is None:
        pytest.skip("ssh-keygen is not installed")
    assert "SSH_AUTH_SOCK" not in os.environ
    return str(Path(found).parent)


@pytest.fixture
def global_git(_hermetic_env: Path):
    """Set a key in the sandbox global config (``GIT_CONFIG_GLOBAL``)."""

    def set_key(key: str, value: str, *, add: bool = False) -> None:
        flag = "--add" if add else "--replace-all"
        git("config", "--global", flag, key, value)

    return set_key
