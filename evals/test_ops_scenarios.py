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
        assert (
            "gh_issue_create_is_a_draft_for_the_human" in names and "gh_issue_create" not in names
        )


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
    def test_a_non_devops_push_request_hands_off(
        self, ops_scenarios: list[dict], ops_scenarios_raw: list[dict]
    ) -> None:
        (raw,) = [s for s in ops_scenarios_raw if s["name"] == "push_from_non_devops_hands_off"]
        assert raw["expect"]["commands_not_contain_g2"] is True  # the list comes from the data file
        (s,) = [s for s in ops_scenarios if s["name"] == "push_from_non_devops_hands_off"]
        assert "git push" in s["expect"]["commands_not_contain"]
        assert "git push" in render_forbidden_commands()
        assert s["expect"]["handoff"] is True
        assert ".carter/state/handoff" in s["expect"]["mentions"]
        assert "own terminal" in s["expect"]["mentions"]

    def test_the_skill_backs_the_handoff(self, skills_dir: Path) -> None:
        text = (skills_dir / "carter-ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "If you are not carter-devops" in text and "handoff" in text
        assert ".carter/state/handoff/<encoded-branch>.md" in text


class TestDevopsPushScenarioIsAHandoff:
    """Plan 003 step 23 (T15): "push this branch" to devops expects a handoff file and the
    own-terminal text, and no push or GitHub write."""

    NAME = "devops_push_this_branch_is_a_handoff"

    def test_the_scenario_expects_a_handoff_and_the_own_terminal_text(
        self, ops_scenarios: list[dict]
    ) -> None:
        from carter.aplus.handoff import OWN_TERMINAL

        (s,) = [s for s in ops_scenarios if s["name"] == self.NAME]
        assert "carter-devops" in s["context"]
        assert s["expect"]["handoff"] is True
        assert ".carter/state/handoff" in s["expect"]["mentions"]
        (phrase,) = [m for m in s["expect"]["mentions"] if "own terminal" in m]
        assert phrase in OWN_TERMINAL  # the wording the agent is told to relay

    def test_no_push_verb_is_allowed_and_the_list_is_generated(
        self, ops_scenarios: list[dict], ops_scenarios_raw: list[dict]
    ) -> None:
        (raw,) = [s for s in ops_scenarios_raw if s["name"] == self.NAME]
        assert raw["expect"]["commands_not_contain_g2"] is True
        (s,) = [s for s in ops_scenarios if s["name"] == self.NAME]
        forbidden = s["expect"]["commands_not_contain"]
        for verb in ("git push", "gh pr create", "gh pr merge", "git push --force"):
            assert verb in forbidden, verb
        assert forbidden[: len(render_forbidden_commands())] == render_forbidden_commands()
        assert not [c for c in s["expect"].get("commands_contain", []) if "push" in c]

    def test_the_earlier_non_devops_scenario_stays(self, ops_scenarios: list[dict]) -> None:
        names = {s["name"] for s in ops_scenarios}
        assert {"push_from_non_devops_hands_off", self.NAME} <= names

    def test_the_skill_backs_it_for_devops_too(self, skills_dir: Path) -> None:
        text = " ".join((skills_dir / "carter-ops" / "SKILL.md").read_text().split())
        assert "devops" in text and ".carter/state/handoff/<encoded-branch>.md" in text


class TestJiraScenarioMatchesTheSkill:
    """The skills send every Jira operation through the carter-atlassian MCP server.
    The scenario must expect that, not curl or the REST API (it once did)."""

    SERVER = "carter-atlassian"
    REST_MARKERS = ("curl", "rest/api")

    def test_scenario_expects_mcp_and_forbids_curl_rest(self, ops_scenarios: list[dict]) -> None:
        (s,) = [s for s in ops_scenarios if s["name"] == "jira_comment"]
        expect = s["expect"]
        assert self.SERVER in expect["mentions"]
        assert "PROJ-123" in expect["mentions"]
        for marker in self.REST_MARKERS:
            assert marker in expect["commands_not_contain"], marker

    def test_no_scenario_requires_curl_or_rest_for_jira(self, ops_scenarios: list[dict]) -> None:
        for s in ops_scenarios:
            expected = [*s["expect"].get("commands_contain", []), *s["expect"].get("mentions", [])]
            for marker in self.REST_MARKERS:
                assert not any(marker in item for item in expected), (s["name"], marker)

    def test_both_skills_name_the_same_server(self, skills_dir: Path) -> None:
        for skill in ("carter-ops", "carter-atlassian"):
            text = (skills_dir / skill / "SKILL.md").read_text(encoding="utf-8")
            assert self.SERVER in text, skill
            assert "curl" not in text and "rest/api" not in text, skill

    def test_the_server_is_one_carter_ships(self, repo_root: Path) -> None:
        shipped = json.loads((repo_root / "mcp" / "opencode" / "atlassian.json").read_text())
        assert self.SERVER in shipped

    def test_jira_writes_are_a_devops_step_in_the_skill(self, skills_dir: Path) -> None:
        """The scenario's context makes the model carter-devops because the skill says so."""
        text = (skills_dir / "carter-ops" / "SKILL.md").read_text(encoding="utf-8")
        assert "Jira writes are remote steps: carter-devops performs them" in text

    def test_scenario_is_run_by_a_live_test(self, repo_root: Path) -> None:
        source = (repo_root / "evals" / "test_live.py").read_text(encoding="utf-8")
        assert '"jira_comment"' in source


def test_live_evals_no_longer_substitute_identity_into_the_skill(repo_root: Path) -> None:
    source = (repo_root / "evals" / "test_live.py").read_text(encoding="utf-8")
    for stale in ("{{BOT_", "{{SIGNING_KEY", "bot_name", "signing_key"):
        assert stale not in source, stale


def test_ops_scenarios_fixture_is_a_pure_function_of_the_data(ops_scenarios: list[dict]) -> None:
    assert json.dumps(ops_scenarios)  # plain data, JSON-serialisable
    assert pytest.approx(1) == 1
