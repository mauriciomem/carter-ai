"""Shared fixtures for Carter eval tests."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml


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
def scenarios_dir() -> Path:
    """Path to scenario definitions."""
    return Path(__file__).resolve().parent / "scenarios"


@pytest.fixture
def ops_scenarios(scenarios_dir: Path) -> list[dict]:
    """carter-ops skill scenarios."""
    return yaml.safe_load((scenarios_dir / "carter_ops.yaml").read_text())


@pytest.fixture
def skill_scenarios(scenarios_dir: Path) -> list[dict]:
    """Skill-correctness scenarios."""
    return yaml.safe_load((scenarios_dir / "skills.yaml").read_text())


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Persist the live-eval metrics summary for CI artifact upload.

    The run-level token/latency/cost summary lives in ``evals.metrics._RECORDED``,
    which dies with the pytest process — so the weekly live-eval cron cannot read it
    after pytest exits. When ``EVAL_METRICS_OUT`` points at a path, write
    ``evals.metrics.summary()`` there as JSON for ``actions/upload-artifact``.

    Inert (writes nothing) unless the env var is set, so the key-free offline PR gate
    is completely unaffected.
    """
    out = os.environ.get("EVAL_METRICS_OUT")
    if not out:
        return
    from evals.metrics import summary

    path = Path(out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary(), indent=2) + "\n")
