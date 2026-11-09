"""Fixtures for the opt-in e2e suite.

Everything here is skipped unless ``CARTER_E2E=1``. The real ``opencode`` binary is resolved
at import time, before the autouse tool guard puts a refusing stub first on ``PATH``. A second
binary (the warn-band 2.1.2) is selected with ``CARTER_E2E_OPENCODE=<path>``.

``CARTER_E2E_NETNS``: ``1`` forces the ``unshare -rn`` loopback-only wrapper (fails if it is not
available), ``0`` disables it; unset means "use it when it works".
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from e2e.harness import Rig, netns_available

# Resolved before any fixture (the autouse guard_bin shadows `opencode` per test).
_RESOLVED = os.environ.get("CARTER_E2E_OPENCODE") or shutil.which("opencode")
_ALT = os.environ.get("CARTER_E2E_OPENCODE_ALT")  # a second binary (the warn-band 2.1.2)
_BASE_ROOT = Path(os.environ.get("CARTER_E2E_BASE", "/tmp/carter-e2e"))


@dataclass(frozen=True)
class OpencodeBinary:
    path: str
    version: str


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "e2e: starts a real OpenCode in an isolated HOME (CARTER_E2E=1)"
    )


def _version(path: str) -> str:
    out = subprocess.run(
        [path, "--version"],
        capture_output=True,
        text=True,
        timeout=30,
        env={"PATH": "/usr/bin:/bin"},
    )
    return out.stdout.strip().removeprefix("opencode").strip().removeprefix("v")


@pytest.fixture(scope="session")
def real_opencode() -> OpencodeBinary:
    """The real binary, or a skip. Never the user's service: the rig starts its own server."""
    if os.environ.get("CARTER_E2E") != "1":
        pytest.skip("e2e is opt-in: set CARTER_E2E=1")
    if not _RESOLVED:
        pytest.skip("no opencode binary on PATH (or CARTER_E2E_OPENCODE)")
    return OpencodeBinary(_RESOLVED, _version(_RESOLVED))


@pytest.fixture(params=["primary", "alt"])
def opencode_bin(request: pytest.FixtureRequest, real_opencode: OpencodeBinary) -> OpencodeBinary:
    """The primary binary, then ``CARTER_E2E_OPENCODE_ALT`` when set (skipped otherwise)."""
    if request.param == "primary":
        return real_opencode
    if not _ALT:
        pytest.skip("set CARTER_E2E_OPENCODE_ALT=<path> to also run on a second OpenCode version")
    return OpencodeBinary(_ALT, _version(_ALT))


@pytest.fixture
def rig_factory(real_opencode: OpencodeBinary, real_home: Path) -> Iterator[Callable[..., Rig]]:
    """Build and start rigs; every rig is stopped (and its isolated service) at teardown."""
    started: list[Rig] = []
    _BASE_ROOT.mkdir(parents=True, exist_ok=True)

    def make(opencode: OpencodeBinary | None = None, **kwargs: Any) -> Rig:
        mode = os.environ.get("CARTER_E2E_NETNS", "auto")
        use_netns = netns_available() if mode == "auto" else mode == "1"
        base = Path(tempfile.mkdtemp(prefix="r", dir=_BASE_ROOT))
        rig = Rig(
            opencode=(opencode or real_opencode).path,
            base=base,
            real_home=real_home,
            use_netns=use_netns,
            **kwargs,
        )
        started.append(rig)
        rig.start()
        return rig

    yield make
    for rig in reversed(started):
        try:
            rig.stop_service()
        finally:
            rig.stop()
