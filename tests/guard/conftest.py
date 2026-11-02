"""Fixtures for the ``carter guard`` tests (plan 003 steps 11-15)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from guard.helpers import agents_json, all_live_statements, debug_config

BUILTINS = ["build", "plan", "general", "explore"]
REAL_GIT = shutil.which("git") or "/usr/bin/git"


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
