"""Fixtures for the CI-E tests."""

from __future__ import annotations

import pytest

from carter.ci import template


@pytest.fixture(params=[False, True], ids=["plain", "comment"])
def rendered(request: pytest.FixtureRequest) -> str:
    return template.render(comment=request.param)
