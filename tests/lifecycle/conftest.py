"""Fixtures for the install -> uninstall lifecycle tests.

The suite-wide ``_hermetic_env`` already points HOME and the XDG directories at a temp tree;
``base_dir`` (a separate temp tree) is where Carter writes, exactly as the install tests do.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carter.install import orchestrator


@pytest.fixture
def installed(base_dir: Path, fake_opencode) -> Path:
    """A base dir after one default ``carter install`` (OpenCode faked)."""
    fake_opencode()
    orchestrator.run(base_dir=base_dir, verbosity=1)
    return base_dir
