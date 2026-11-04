"""The wheel carries everything G2 needs at run time (plan 004 step 26, C25).

Built once per session with ``uv build --wheel``; skipped when ``uv`` is not available.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    "carter/plugin/core.ts",
    "carter/plugin/index.ts",
    "carter/guard/templates/carter-guard.sh",
    "carter/identity/g2_rules.json",
    "carter/identity/errors.json",
    "carter/gate/__init__.py",
    "carter/gate/__main__.py",
    "carter/gate/rules.py",
    "carter/guard/plugin.py",
    "carter/guard/hooks.py",
)


@pytest.fixture(scope="session")
def wheel_names(tmp_path_factory: pytest.TempPathFactory) -> set[str]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is not installed")
    out = tmp_path_factory.mktemp("wheel")
    env = {**os.environ, "SETUPTOOLS_SCM_PRETEND_VERSION": "0.0.1"}
    done = subprocess.run(
        [uv, "build", "--wheel", "-o", str(out)],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=300,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-500:]
    (wheel,) = out.glob("*.whl")
    with zipfile.ZipFile(wheel) as z:
        return set(z.namelist())


@pytest.mark.parametrize("name", REQUIRED)
def test_the_wheel_contains(name: str, wheel_names: set[str]) -> None:
    assert name in wheel_names


def test_the_plugin_sources_still_hold_the_placeholders(wheel_names: set[str]) -> None:
    """The shipped index.ts is unrendered: it refuses to create agent shells by construction."""
    text = (ROOT / "carter/plugin/index.ts").read_text()
    assert "__CARTER_ISOLATION_SHA256__" in text and "__CARTER_VERSION__" in text
    assert "carter/plugin/index.ts" in wheel_names
