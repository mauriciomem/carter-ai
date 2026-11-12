"""Shared fixtures for Carter eval tests."""

from __future__ import annotations

import copy
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
def agents_dir(tmp_path: Path) -> Path:
    """Agents rendered from ``templates/`` exactly as ``carter install`` writes them
    (no suffix)."""
    from carter.config import generate_default_config
    from carter.scaffold import create_env, render_agents

    cfg = generate_default_config()
    cfg["agent_suffix"] = ""
    out = tmp_path / "agents"
    out.mkdir()
    for name, content in render_agents(cfg, create_env()).items():
        (out / name).write_text(content, encoding="utf-8")
    assert any(out.glob("carter-*.md")), "no agents rendered"
    return out


@pytest.fixture
def skills_dir(repo_root: Path) -> Path:
    """Path to skill definitions (never empty, so per-skill loops cannot pass vacuously)."""
    path = repo_root / "skills"
    assert any(path.glob("carter-*/SKILL.md")), f"no skills in {path}"
    return path


@pytest.fixture
def scenarios_dir() -> Path:
    """Path to scenario definitions."""
    return Path(__file__).resolve().parent / "scenarios"


@pytest.fixture
def ops_scenarios_raw(scenarios_dir: Path) -> list[dict]:
    """carter-ops skill scenarios exactly as written in the YAML."""
    return yaml.safe_load((scenarios_dir / "carter_ops.yaml").read_text(encoding="utf-8"))


@pytest.fixture
def ops_scenarios(ops_scenarios_raw: list[dict]) -> list[dict]:
    """carter-ops scenarios with the generated forbidden-command lists filled in.

    A scenario with ``expect.commands_not_contain_g2: true`` gets the list rendered from
    ``g2_rules.json`` followed by its own extra ``commands_not_contain`` entries."""
    from carter.identity.rules import render_forbidden_commands

    resolved = copy.deepcopy(ops_scenarios_raw)
    for scenario in resolved:
        expect = scenario["expect"]
        if expect.pop("commands_not_contain_g2", False):
            expect["commands_not_contain"] = [
                *render_forbidden_commands(),
                *expect.get("commands_not_contain", []),
            ]
    return resolved


@pytest.fixture
def skill_scenarios(scenarios_dir: Path) -> list[dict]:
    """Skill-correctness scenarios."""
    return yaml.safe_load((scenarios_dir / "skills.yaml").read_text(encoding="utf-8"))


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
    path.write_text(json.dumps(summary(), indent=2) + "\n", encoding="utf-8")
