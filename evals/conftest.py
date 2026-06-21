"""Shared fixtures for Carter eval tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    """Path to the Carter repository root."""
    return Path(__file__).resolve().parent.parent


@pytest.fixture
def agents_dir(repo_root: Path) -> Path:
    """Path to agent definitions."""
    return repo_root / "agents"


@pytest.fixture
def skills_dir(repo_root: Path) -> Path:
    """Path to skill definitions."""
    return repo_root / "skills"


@pytest.fixture
def instructions_dir(repo_root: Path) -> Path:
    """Path to instruction files."""
    return repo_root / "instructions"


@pytest.fixture
def scenarios_dir() -> Path:
    """Path to scenario definitions."""
    return Path(__file__).resolve().parent / "scenarios"
