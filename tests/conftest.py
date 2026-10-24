"""Shared test fixtures for Carter installer tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def base_dir(tmp_path: Path) -> Path:
    """Temporary base directory for testing (overrides ~/.copilot etc.)."""
    return tmp_path


@pytest.fixture
def fake_opencode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Put a fake ``opencode`` on an isolated PATH.

    Call it with the ``--version`` output to emit, or ``None`` for "not installed".
    PATH holds only the fake bin dir, so a real ``opencode`` can never leak in.
    """

    def make(version_output: str | None = "opencode v2.1.4") -> Path:
        bindir = tmp_path / "fakebin"
        bindir.mkdir(exist_ok=True)
        script = bindir / "opencode"
        if version_output is None:
            script.unlink(missing_ok=True)
        else:
            script.write_text(f"#!/bin/sh\nprintf '%s\\n' '{version_output}'\n")
            script.chmod(0o755)
        monkeypatch.setenv("PATH", str(bindir))
        return bindir

    return make
