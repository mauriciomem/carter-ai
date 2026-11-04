"""Helpers for the CI-E tests: fixture path and an optional ``actionlint``."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "workflows"


def find_actionlint() -> str | None:
    """``ACTIONLINT`` or ``actionlint`` on PATH; the structural checker is the floor without it."""
    return os.environ.get("ACTIONLINT") or shutil.which("actionlint")


def run_actionlint(binary: str, path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [binary, "-no-color", str(path)], capture_output=True, text=True, timeout=60, check=False
    )
