"""Decline one group on its own, and keep it declined.

The install question stays one question (``Install? [Y/n]``). A *no* leads to a short prompt per
group (``g2 [Y/n]``); each no is recorded as *declined* in ``guard-state.json`` and the group is
not offered again until ``guard install --only <group>``. ``guard remove --only <group>`` records
the same decision, and ``isolation.json`` follows the state in the same run.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner, Result

from carter import ui
from carter.cli import main
from carter.guard import agent_rules, consent
from carter.guard.state import GuardState, load, save
from carter.identity.policyset import consent_groups
from carter.install.paths import guard_state_path, isolation_path
from guard.helpers import tree_hash, verbose

ONE = "read-edit-denies"
OFFERED = consent.to_offer(GuardState(), only=None, unavailable={"repo_hooks": "not needed"})
SSH_READ = {"action": "read", "resource": "*/.ssh/*", "effect": "deny"}


def guard(*args: str, input: str | None = None) -> Result:
    ui.configure(verbose=False)
    return CliRunner().invoke(main, ["guard", *verbose(args)], input=input, catch_exceptions=False)


def answers(*no: str) -> str:
    """The input of the question: a no to ``Install?``, then one answer per group."""
    return "n\n" + "".join("n\n" if g in no else "y\n" for g in OFFERED)


def decisions() -> dict[str, str]:
    return {g: rec["decision"] for g, rec in load(guard_state_path(None)).consents.items()}


def isolation_declined() -> list[str]:
    return json.loads(isolation_path(None).read_text())["plugin"]["declined_groups"]


class TestDecideEach:
    """``consent.decide_each``: the plan for one yes or no per group (no I/O)."""

    def test_a_yes_accepts_and_a_no_declines_a_group_nobody_decided(self) -> None:
        plan = consent.decide_each(GuardState(), {"g2": True, ONE: False})
        assert plan.accepted == ["g2"] and plan.declined == [ONE]
        assert plan.asked == ["g2", ONE] and plan.refused_offers == []

    def test_a_no_never_withdraws_an_accepted_group(self) -> None:
        state = GuardState()
        state.consent("g2", "accepted", "2026-11-01", 3)
        plan = consent.decide_each(state, {"g2": False}, only=["g2"])
        assert plan.declined == [] and plan.asked == [] and plan.refused_offers == []

    def test_a_no_to_a_revision_upgrade_is_remembered_not_declined(self) -> None:
        state = GuardState()
        state.consent("g2", "accepted", "2026-11-01", 1)
        plan = consent.decide_each(state, {"g2": False})
        assert plan.refused_offers == ["g2"] and plan.declined == []

    def test_a_yes_re_enables_a_declined_group(self) -> None:
        state = GuardState()
        state.consent(ONE, "declined", "2026-11-01", 1)
        plan = consent.decide_each(state, {ONE: True}, only=[ONE])
        assert plan.accepted == [ONE] and plan.asked == [ONE]

    def test_a_no_to_a_declined_group_changes_nothing(self) -> None:
        state = GuardState()
        state.consent(ONE, "declined", "2026-11-01", 1)
        plan = consent.decide_each(state, {ONE: False}, only=[ONE])
        assert plan.asked == [] and plan.declined == []


class TestThePerGroupQuestion:
    def test_a_no_leads_to_one_short_prompt_per_group(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", input=answers(ONE))
        assert res.exit_code == 0, res.output
        for name in OFFERED:
            assert f"{name} [Y/n]" in res.output
        assert "see: carter guard --help" in res.output  # where the rest is explained
        assert all(len(line) <= ui.MAX for line in res.output.splitlines())

    def test_one_no_declines_just_that_group_and_installs_the_rest(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", input=answers(ONE))
        assert res.exit_code == 0, res.output
        got = decisions()
        assert got.pop(ONE) == "declined" and set(got.values()) == {"accepted"}
        assert set(got) == set(OFFERED) - {ONE}
        assert "Declined: read-edit-denies" in res.output

    def test_what_the_declined_group_denies_is_not_rendered(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        rules = agent_rules.current_rules()
        assert SSH_READ not in rules
        assert {"action": "shell", "resource": "git push *", "effect": "deny"} in rules

    def test_isolation_json_names_the_declined_group(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        assert isolation_declined() == [ONE]

    def test_the_declined_group_is_not_offered_or_asked_again(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        before = guard_state_path(None).read_bytes()
        again = guard("install", input="y\n")  # nothing left to ask: no question at all
        assert again.exit_code == 0 and "Install?" not in again.output
        assert guard_state_path(None).read_bytes() == before

    def test_a_scripted_install_keeps_it_declined(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        human_tty(False)
        assert guard("install", "--yes").exit_code == 0
        assert decisions()[ONE] == "declined" and isolation_declined() == [ONE]

    def test_status_says_declined_and_how_to_ask_again(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        out = guard("status").output
        assert f"{ONE:<16} declined" in out and "see: carter guard install --help" in out

    def test_the_group_comes_back_only_by_name(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        guard("install", input=answers(ONE))
        res = guard("install", "--only", ONE, input="y\n")
        assert res.exit_code == 0, res.output
        assert decisions()[ONE] == "accepted" and isolation_declined() == []
        assert SSH_READ in agent_rules.current_rules()

    def test_every_no_declines_every_group_and_installs_nothing(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", input=answers(*OFFERED))
        assert res.exit_code == 0 and "nothing installed" in res.output
        assert set(decisions().values()) == {"declined"} and set(decisions()) == set(OFFERED)
        rules = agent_rules.current_rules()
        assert {r["resource"] for r in rules} >= {"sudo *"}  # the floor stays
        assert not [r for r in rules if r["resource"] in ("git push *", "docker *")]
        assert not isolation_path(None).exists()

    def test_leaving_midway_records_nothing(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        before = tree_hash(stack.home)
        res = guard("install", input="n\ny\n")  # the input ends: same as Ctrl-C
        assert res.exit_code == 1 and not guard_state_path(None).exists()
        assert tree_hash(stack.home) == before

    def test_a_single_group_in_the_question_has_no_second_prompt(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", "--only", ONE, input="n\n")
        assert res.exit_code == 0 and res.output.count("[Y/n]") == 1
        assert decisions() == {ONE: "declined"}

    def test_a_no_to_an_upgrade_keeps_the_old_consent(self, stack, human_tty) -> None:
        state = GuardState()
        for group in consent_groups():
            if group.id in OFFERED:
                state.consent(
                    group.id, "accepted", "2026-11-01", 1 if group.id == "g2" else group.rev
                )
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        save(state, path)
        human_tty(True)
        stack.fake()
        res = guard("install", input="n\n")
        assert res.exit_code == 0
        assert load(path).consents["g2"]["decision"] == "accepted"
        assert load(path).extra["consent_offers"]["g2"]["decision"] == "declined"


class TestRemoveOnlyIsPersistent:
    def installed(self, stack) -> None:
        stack.fake()
        assert guard("install", "--yes").exit_code == 0

    @pytest.mark.usefixtures("at_terminal")
    def test_it_records_the_group_as_declined(self, stack) -> None:
        self.installed(stack)
        stack.fake()
        res = guard("remove", "--only", ONE)
        assert res.exit_code == 0, res.output
        assert decisions()[ONE] == "declined" and decisions()["g2"] == "accepted"

    @pytest.mark.usefixtures("at_terminal")
    def test_the_next_install_does_not_bring_it_back(self, stack, human_tty) -> None:
        human_tty(True)
        self.installed(stack)
        guard("remove", "--only", ONE)
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        assert decisions()[ONE] == "declined"
        again = guard("install", input="y\n")
        assert "Install?" not in again.output and decisions()[ONE] == "declined"

    @pytest.mark.usefixtures("at_terminal")
    def test_isolation_json_is_re_rendered_in_the_same_run(self, stack) -> None:
        self.installed(stack)
        assert isolation_declined() == []
        guard("remove", "--only", ONE)
        assert isolation_declined() == [ONE]
        assert SSH_READ not in agent_rules.current_rules()

    @pytest.mark.usefixtures("at_terminal")
    def test_install_only_brings_it_back(self, stack) -> None:
        self.installed(stack)
        guard("remove", "--only", ONE)
        stack.fake()
        assert guard("install", "--yes", "--only", ONE).exit_code == 0
        assert decisions()[ONE] == "accepted" and isolation_declined() == []

    @pytest.mark.usefixtures("at_terminal")
    def test_isolation_json_matches_the_state_after_every_change(self, stack) -> None:
        self.installed(stack)
        for step in (("remove", "--only", "hooks"), ("remove", "--only", ONE)):
            guard(*step)
            declined = sorted(g for g, d in decisions().items() if d == "declined")
            assert isolation_declined() == declined
        stack.fake()
        guard("install", "--yes", "--only", "hooks")
        assert isolation_declined() == [ONE]

    @pytest.mark.usefixtures("at_terminal")
    def test_it_says_in_two_short_lines_what_happened_and_where_to_read(self, stack) -> None:
        self.installed(stack)
        out = guard("remove", "--only", ONE).output.splitlines()
        tail = out[-2:]
        assert tail[0].startswith("✓ removed") and ONE in tail[0]
        assert "declined" in tail[1] and "see: carter guard --help" in tail[1]
        assert all(len(line) <= ui.TARGET for line in tail)

    def test_a_dry_run_writes_nothing(self, stack) -> None:
        self.installed(stack)
        before = tree_hash(stack.home)
        stack.fake()
        res = guard("remove", "--dry-run", "--only", ONE)
        assert res.exit_code == 0 and tree_hash(stack.home) == before

    @pytest.mark.usefixtures("at_terminal")
    def test_removing_a_component_records_no_decision(self, stack) -> None:
        self.installed(stack)
        before = decisions()
        guard("remove", "--only", "broker")
        assert {g: d for g, d in decisions().items() if g != "g2"} == {
            g: d for g, d in before.items() if g != "g2"
        }

    @pytest.mark.usefixtures("at_terminal")
    def test_removing_g2_declines_it_and_the_plugin_goes(self, stack) -> None:
        self.installed(stack)
        guard("remove", "--only", "g2")
        assert decisions()["g2"] == "declined" and not isolation_path(None).exists()
