"""Offline routing eval — validates agent file structure supports correct dispatch.

These tests verify:
1. Routing table in carter-maestro covers all expected triggers
2. Every agent has the ops: one-liner
3. Trigger keywords in scenarios actually appear in routing table
4. No routing ambiguity (one trigger doesn't match multiple agents)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def routing_scenarios(scenarios_dir: Path) -> list[dict]:
    return yaml.safe_load((scenarios_dir / "routing.yaml").read_text())


@pytest.fixture
def maestro_content(agents_dir: Path) -> str:
    return (agents_dir / "carter-maestro.md").read_text()


@pytest.fixture
def routing_table(maestro_content: str) -> dict[str, list[str]]:
    """Parse the maestro routing table into {agent: [triggers]}."""
    table: dict[str, list[str]] = {}
    # Match table rows: | Domain | @agent | triggers |
    for match in re.finditer(
        r"\|\s*[^|]+\|\s*@(carter-\w+)\s*\|\s*([^|]+)\|", maestro_content
    ):
        agent = match.group(1)
        triggers = [t.strip() for t in match.group(2).split(",")]
        table[agent] = triggers
    return table


class TestRoutingTableCompleteness:
    """Verify the routing table in carter-maestro.md is complete and correct."""

    def test_all_agents_have_routes(self, routing_table: dict, agents_dir: Path) -> None:
        """Every agent file should have a corresponding route in maestro."""
        agent_files = {f.stem for f in agents_dir.glob("carter-*.md")}
        # Maestro doesn't route to itself
        agent_files.discard("carter-maestro")
        routed_agents = set(routing_table.keys())
        missing = agent_files - routed_agents
        assert not missing, f"Agents without routes: {missing}"

    def test_no_empty_triggers(self, routing_table: dict) -> None:
        """Every agent route must have at least one trigger keyword."""
        for agent, triggers in routing_table.items():
            assert triggers, f"{agent} has no trigger keywords"
            assert all(t for t in triggers), f"{agent} has empty trigger keywords"

    def test_no_duplicate_triggers(self, routing_table: dict) -> None:
        """No trigger keyword should appear for multiple agents (ambiguity)."""
        seen: dict[str, str] = {}
        duplicates: list[str] = []
        for agent, triggers in routing_table.items():
            for trigger in triggers:
                normalized = trigger.lower().strip()
                if normalized in seen:
                    duplicates.append(
                        f"'{normalized}' in both {seen[normalized]} and {agent}"
                    )
                seen[normalized] = agent
        assert not duplicates, f"Ambiguous triggers: {duplicates}"


class TestRoutingScenarios:
    """Verify each routing scenario maps to a trigger in the routing table."""

    def test_scenarios_match_routing_table(
        self, routing_scenarios: list[dict], routing_table: dict
    ) -> None:
        """Scenario triggers should exist in the maestro routing table."""
        all_triggers = {}
        for agent, triggers in routing_table.items():
            for t in triggers:
                all_triggers[t.lower()] = agent

        failures = []
        for scenario in routing_scenarios:
            expected = scenario.get("expect", {})
            agent = expected.get("agent")
            triggers = expected.get("triggers", [])

            if not agent or not triggers:
                continue  # Skip non-agent scenarios (direct_answer, clarify, skill)

            for trigger in triggers:
                normalized = trigger.lower()
                if normalized not in all_triggers:
                    failures.append(
                        f"Scenario '{scenario['name']}': trigger '{trigger}' "
                        f"not found in maestro routing table"
                    )
                elif all_triggers[normalized] != agent:
                    failures.append(
                        f"Scenario '{scenario['name']}': trigger '{trigger}' "
                        f"routes to {all_triggers[normalized]}, expected {agent}"
                    )

        assert not failures, "\n".join(failures)

    def test_ops_prefix_is_skill_not_agent(
        self, routing_scenarios: list[dict], maestro_content: str
    ) -> None:
        """The ops: prefix should trigger a skill load, not agent delegation."""
        ops_scenarios = [
            s for s in routing_scenarios if s["expect"].get("skill") == "carter-ops"
        ]
        assert ops_scenarios, "No ops: scenarios defined"

        # Maestro must have the ops: one-liner
        assert "ops:" in maestro_content
        assert "carter-ops" in maestro_content


class TestOpsOneLiner:
    """Every agent must have the ops: trigger one-liner."""

    def test_all_agents_have_ops_trigger(self, agents_dir: Path) -> None:
        """All agent files must contain the ops: skill trigger."""
        missing = []
        for agent_file in sorted(agents_dir.glob("carter-*.md")):
            content = agent_file.read_text()
            if "ops:" not in content or "carter-ops" not in content:
                missing.append(agent_file.name)
        assert not missing, f"Agents missing ops: trigger: {missing}"


class TestDispatchRules:
    """Verify maestro has proper dispatch rules documented."""

    def test_has_direct_answer_rule(self, maestro_content: str) -> None:
        assert "direct answer" in maestro_content.lower() or "Direct answer" in maestro_content

    def test_has_multi_agent_chaining(self, maestro_content: str) -> None:
        assert "multi-agent" in maestro_content.lower() or "chaining" in maestro_content.lower()

    def test_has_ambiguity_handling(self, maestro_content: str) -> None:
        assert "ambiguous" in maestro_content.lower()
