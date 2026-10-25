"""Tests for native subagent dispatch (ADR-0014 D1 step 5).

Delegation is a flat chain: every agent gets ``subagent * → deny``; only the
primary (carter-maestro) additionally gets ``subagent carter-* → allow`` after it,
so the last match lets it launch Carter specialists and nothing else.
"""

from __future__ import annotations

import yaml

from carter.config import PRIMARY_ROLE, generate_default_config, permission_rules
from carter.scaffold import create_env, render_agents


def _config(suffix: str = "") -> dict:
    cfg = generate_default_config(workspace_name="dispatch", mode="single")
    cfg["agent_suffix"] = suffix
    return cfg


def _subagent_rules(cfg: dict, role: str) -> list[tuple[str, str]]:
    return [
        (r["resource"], r["effect"])
        for r in permission_rules(cfg, role)
        if r["action"] == "subagent"
    ]


def test_primary_is_maestro():
    assert PRIMARY_ROLE == "maestro"


def test_maestro_denies_all_then_allows_carter_agents():
    assert _subagent_rules(_config(), "maestro") == [("*", "deny"), ("carter-*", "allow")]


def test_specialists_deny_all_subagents():
    cfg = _config()
    for role in cfg["agents"]:
        if role != PRIMARY_ROLE:
            assert _subagent_rules(cfg, role) == [("*", "deny")], role


def test_rendered_suffixed_maestro_keeps_glob():
    cfg = _config(suffix="local")
    text = render_agents(cfg, create_env())["carter-maestro-local.md"]
    fm = yaml.safe_load(text.split("---", 2)[1])
    sub = [r for r in fm["permissions"] if r["action"] == "subagent"]
    assert sub == [
        {"action": "subagent", "resource": "*", "effect": "deny"},
        {"action": "subagent", "resource": "carter-*", "effect": "allow"},
    ]


def test_no_runsubagent_fiction_anywhere():
    for content in render_agents(_config(suffix="local"), create_env()).values():
        assert "runSubagent" not in content
