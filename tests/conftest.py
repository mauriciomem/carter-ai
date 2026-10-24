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
