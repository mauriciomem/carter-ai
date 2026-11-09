"""Plain helpers for the `carter push` tests (fixtures live in ``conftest.py``)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


def git(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None):
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    assert proc.returncode == 0, (args, proc.stderr)
    return proc


def make_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git("init", "-q", "-b", branch, str(path))
    return path


def commit_file(repo: Path, name: str, text: str = "x\n", message: str | None = None, **env) -> str:
    target = repo / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text)
    git("add", "-f", name, cwd=repo)
    git("commit", "-q", "-m", message or f"add {name}", cwd=repo, env=env or None)
    return git("rev-parse", "HEAD", cwd=repo).stdout.strip()
