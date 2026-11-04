"""Fixtures for the ``carter guard`` tests (plan 003 steps 11-15)."""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from guard.helpers import agents_json, all_live_statements, debug_config

BUILTINS = ["build", "plan", "general", "explore"]
REAL_GIT = shutil.which("git") or "/usr/bin/git"
DEV_REPO_HOOK = Path(__file__).resolve().parents[2] / ".git" / "hooks" / "pre-push"


@pytest.fixture(autouse=True)
def _guard_tests_never_write_the_dev_repo(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """`carter guard install` offers a repo hook for the current directory's repository (git <
    2.54 path), so a test must never run with this repository as its cwd. Found the hard way:
    a simulated old git once wrote ``.git/hooks/pre-push`` here."""
    existed = DEV_REPO_HOOK.exists()
    monkeypatch.chdir(home)
    yield
    assert DEV_REPO_HOOK.exists() == existed, "a guard test wrote a hook into the dev repository"


@pytest.fixture
def home(_hermetic_env: Path) -> Path:
    return _hermetic_env


@pytest.fixture
def stack(home: Path, fake_opencode):
    """A fake OpenCode that lists the built-ins and a Carter agent, and loads everything."""

    class Stack:
        def __init__(self) -> None:
            self.home = home
            self.live = all_live_statements(str(home))

        def fake(self, *, after=None, before=None, **kw) -> None:
            bindir = fake_opencode(
                agents_output=agents_json(*BUILTINS, "carter-engineer"),
                config_sequence=[
                    before or debug_config(),
                    after if after is not None else debug_config(self.live),
                ],
                **kw,
            )
            # fake_opencode leaves only its own bin dir on PATH; the git step needs real git.
            if not (bindir / "git").exists():
                (bindir / "git").symlink_to(REAL_GIT)

    return Stack()
