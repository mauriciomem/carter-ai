"""``pytest tests/snapshots --update-golden`` rewrites the golden files (read the diff after)."""

from __future__ import annotations

import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--update-golden", action="store_true", help="rewrite the golden files")


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    # Registered only when this directory is on the command line; elsewhere it is simply off.
    return bool(request.config.getoption("--update-golden", default=False))
