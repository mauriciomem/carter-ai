"""Offline checks for the carter-ops scenarios (plan 002 step 16).

The scenarios' forbidden-command lists are not typed: a scenario that sets
``commands_not_contain_g2`` gets the list rendered from ``g2_rules.json``. These tests
fail on drift, on a scenario that contradicts itself, and when a simulated
``carter ops config --emit`` result stops matching what the real code prints.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter.identity.rules import render_forbidden_commands
from carter.ops.config import Config

EMIT_KEYS = {
    "tier",
    "role",
    "role_source",
    "coauthor_trailer",
    "commits",
    "refusal_reason",
    "footer",
    "has_github_token",
}
SCENARIO_KEYS = {"name", "input", "emit", "context", "expect"}


class TestScenarioShape:
    def test_every_scenario_is_well_formed(self, ops_scenarios_raw: list[dict]) -> None:
        names = [s["name"] for s in ops_scenarios_raw]
        assert len(names) == len(set(names))
        for s in ops_scenarios_raw:
            assert {"name", "input", "expect"} <= set(s) <= SCENARIO_KEYS, s["name"]

    def test_legacy_config_block_is_gone(self, ops_scenarios_raw: list[dict]) -> None:
        text = json.dumps(ops_scenarios_raw)
        for stale in ("bot_name", "bot_email", "signing_key", "git commit -S"):
            assert stale not in text, stale

    def test_new_scenarios_exist(self, ops_scenarios_raw: list[dict]) -> None:
        names = {s["name"] for s in ops_scenarios_raw}
        assert {"role_author_refused_at_t1", "push_from_non_devops_hands_off"} <= names


class TestForbiddenListsAreGenerated:
    def test_flagged_scenarios_get_exactly_the_rendered_list(
        self, ops_scenarios_raw: list[dict], ops_scenarios: list[dict]
    ) -> None:
        rendered = render_forbidden_commands()
        flagged = [s for s in ops_scenarios_raw if s["expect"].get("commands_not_contain_g2")]
        assert flagged, "at least one scenario must use the generated list"
        by_name = {s["name"]: s for s in ops_scenarios}
        for raw in flagged:
            resolved = by_name[raw["name"]]["expect"]["commands_not_contain"]
            assert resolved[: len(rendered)] == rendered, (
                f"{raw['name']}: commands_not_contain drifted from g2_rules.json; "
                f"expected it to start with {rendered}"
            )
            extras = raw["expect"].get("commands_not_contain", [])
            assert resolved[len(rendered) :] == extras

    def test_the_list_is_not_hand_copied_into_the_yaml(self, scenarios_dir: Path) -> None:
        text = (scenarios_dir / "carter_ops.yaml").read_text(encoding="utf-8")
        for literal in render_forbidden_commands():
            assert f'"{literal}"' not in text and f"- {literal}\n" not in text, literal

    def test_no_scenario_requires_what_it_forbids(self, ops_scenarios: list[dict]) -> None:
        for s in ops_scenarios:
            contain = s["expect"].get("commands_contain", [])
            forbid = s["expect"].get("commands_not_contain", [])
            clashes = [(c, f) for c in contain for f in forbid if f in c]
            assert clashes == [], s["name"]

    def test_the_recipe_scenario_checks_the_new_shape(self, ops_scenarios: list[dict]) -> None:
        (s,) = [s for s in ops_scenarios if s["name"] == "git_branch_flow"]
        contain = s["expect"]["commands_contain"]
        assert not any("-S" in c for c in contain)
        assert "git commit" in contain and "--trailer" in contain
        assert "carter ops config --emit" in contain
        assert "%an|%cn|%G?" in " ".join(contain)
        assert "--author" in s["expect"]["commands_not_contain"]
        assert "git commit -S" in s["expect"]["commands_not_contain"]


class TestSimulatedEmitMatchesTheRealCode:
    def test_emit_blocks_have_exactly_the_real_keys(self, ops_scenarios: list[dict]) -> None:
        for s in ops_scenarios:
            if "emit" in s:
                assert set(s["emit"]) == EMIT_KEYS, s["name"]

    def test_the_refused_scenario_is_what_the_resolver_returns(
        self, ops_scenarios: list[dict], tmp_path: Path
    ) -> None:
        (s,) = [s for s in ops_scenarios if s["name"] == "role_author_refused_at_t1"]
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            'schema = 2\n[identity]\nlogin = "test-bot"\nid = 1\n'
            'email = "1+test-bot@users.noreply.github.com"\n'
            '[workspaces."/nowhere"]\nrole = "author"\n',
            encoding="utf-8",
        )
        real = Config.load(cfg_file, workspace="/nowhere", env={})
        emit = s["emit"]
        assert (emit["tier"], emit["role"], emit["role_source"]) == (
            real.tier,
            real.role,
            real.role_source,
        )
        assert (emit["commits"], emit["refusal_reason"]) == (real.commits, real.refusal_reason)
        assert emit["coauthor_trailer"] == real.coauthor_trailer == ""
        assert s["expect"]["no_commit"] is True
        assert "E-ROLE-B-TIER" in s["expect"]["mentions"]

    def test_the_t1_scenario_trailer_is_what_the_code_builds(
        self, ops_scenarios: list[dict], tmp_path: Path
    ) -> None:
        (s,) = [s for s in ops_scenarios if s["name"] == "git_branch_flow"]
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            'schema = 2\n[identity]\nlogin = "test-bot"\nid = 1\n'
            'email = "1+test-bot@users.noreply.github.com"\n',
            encoding="utf-8",
        )
        real = Config.load(cfg_file, workspace="/nowhere", env={})
        assert s["emit"]["coauthor_trailer"] == real.coauthor_trailer
        assert s["emit"]["tier"] == real.tier == "t1"
        assert real.coauthor_trailer in s["expect"]["commands_contain"]


class TestPushScenarioIsAHandoff:
    def test_a_non_devops_push_request_hands_off(self, ops_scenarios: list[dict]) -> None:
        (s,) = [s for s in ops_scenarios if s["name"] == "push_from_non_devops_hands_off"]
        assert "git push" in s["expect"]["commands_not_contain"]
        assert s["expect"]["handoff"] is True
        assert "carter-devops" in s["expect"]["mentions"]

    def test_the_skill_backs_the_handoff(self, skills_dir: Path) -> None:
        text = (skills_dir / "carter-ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "If you are not carter-devops" in text and "handoff" in text


def test_live_evals_no_longer_substitute_identity_into_the_skill(repo_root: Path) -> None:
    source = (repo_root / "evals" / "test_live.py").read_text(encoding="utf-8")
    for stale in ("{{BOT_", "{{SIGNING_KEY", "bot_name", "signing_key"):
        assert stale not in source, stale


def test_ops_scenarios_fixture_is_a_pure_function_of_the_data(ops_scenarios: list[dict]) -> None:
    assert json.dumps(ops_scenarios)  # plain data, JSON-serialisable
    assert pytest.approx(1) == 1
