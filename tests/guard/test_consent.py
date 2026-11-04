"""Consent groups and the statements that follow them (plan 003 step 11; App C.6.2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from carter.guard import consent, policies
from carter.guard.state import GuardState
from carter.identity import policyset
from carter.identity.policyset import ConsentGroup
from carter.install.mcp import config_target
from carter.install.paths import backups_dir

HOME = "/home/fixture"
LIVE = ["g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit", "repo_hooks"]


def accepted(*groups: str) -> GuardState:
    st = GuardState()
    revs = {g.id: g.rev for g in policyset.consent_groups()}
    for g in groups:
        st.consent(g, "accepted", "2026-11-02", revs[g])
    return st


def groups_of(statements) -> set[str]:
    return {s.group for s in statements}


class TestStatementsFollowConsent:
    def test_only_consented_groups_are_emitted(self) -> None:
        got = consent.desired_statements(accepted("sudo-docker"), home=HOME)
        assert groups_of(got) == {"sudo-docker"}
        assert [s.id for s in got] == ["deny-sudo", "deny-docker"]

    def test_all_live_groups_give_denies_then_allows(self) -> None:
        got = consent.desired_statements(accepted(*LIVE), home=HOME)
        assert groups_of(got) == set(LIVE) - {"hooks", "repo_hooks"}  # files, not statements
        effects = [s.effect for s in got]
        assert effects == sorted(effects, key=lambda e: e == "allow")

    def test_a_declined_group_is_recorded_and_absent(self) -> None:
        st = accepted("g2")
        st.consent("sudo-docker", "declined", "2026-11-02")
        got = consent.desired_statements(st, home=HOME)
        assert "sudo-docker" not in groups_of(got)
        assert st.consents["sudo-docker"] == {
            "decision": "declined",
            "date": "2026-11-02",
            "rev": 1,
        }
        assert consent.declined_groups(st) == ["sudo-docker"]

    def test_gh_allows_belong_to_g2_only(self) -> None:
        assert not [
            s
            for s in consent.desired_statements(accepted("config-edit"), home=HOME)
            if s.effect == "allow"
        ]
        assert [
            s for s in consent.desired_statements(accepted("g2"), home=HOME) if s.effect == "allow"
        ]

    def test_no_consent_no_statements(self) -> None:
        assert consent.desired_statements(GuardState(), home=HOME) == []

    def test_a_reserved_group_in_state_adds_nothing(self) -> None:
        st = accepted("g2")
        st.consent("alias", "accepted", "2026-11-02")  # cannot happen via resolve_consents
        assert consent.accepted_groups(st) == ["g2"]

    def test_optouts_ride_only_with_config_edit(self) -> None:
        extra = [
            policyset.Statement(
                "optout-x-json", "config-edit", "tool.use", "edit:/w/opencode.json", "allow", "t"
            )
        ]
        with_edit = consent.desired_statements(
            accepted("g2", "config-edit"), home=HOME, optouts=extra
        )
        assert with_edit[-1].id == "optout-x-json"
        without = consent.desired_statements(accepted("g2"), home=HOME, optouts=extra)
        assert "optout-x-json" not in [s.id for s in without]


class TestResolve:
    def ask_all(self, answer: bool):
        asked: list[str] = []

        def ask(group: ConsentGroup) -> bool:
            asked.append(group.id)
            return answer

        return ask, asked

    def test_non_tty_without_yes_decides_nothing(self) -> None:
        plan = consent.resolve_consents(
            GuardState(), only=None, assume_yes=False, interactive=False
        )
        assert plan.skipped and not plan.accepted and not plan.declined and not plan.asked
        assert any("NOT installed" in n for n in plan.notices())

    def test_yes_accepts_every_live_group(self) -> None:
        plan = consent.resolve_consents(GuardState(), only=None, assume_yes=True, interactive=False)
        assert plan.accepted == LIVE and plan.declined == [] and plan.asked == LIVE

    def test_tty_prompts_per_group_with_its_effect(self) -> None:
        ask, asked = self.ask_all(True)
        plan = consent.resolve_consents(
            GuardState(), only=None, assume_yes=False, interactive=True, ask=ask
        )
        assert asked == LIVE and plan.accepted == LIVE

    def test_a_no_declines_that_group_only(self) -> None:
        answers = dict.fromkeys(LIVE, True) | {"sudo-docker": False}
        plan = consent.resolve_consents(
            GuardState(), only=None, assume_yes=False, interactive=True, ask=lambda g: answers[g.id]
        )
        assert plan.declined == ["sudo-docker"] and "sudo-docker" not in plan.accepted

    def test_only_limits_the_groups_asked(self) -> None:
        ask, asked = self.ask_all(True)
        plan = consent.resolve_consents(
            GuardState(), only=["g2", "sudo-docker"], assume_yes=False, interactive=True, ask=ask
        )
        assert asked == ["g2", "sudo-docker"] and plan.accepted == ["g2", "sudo-docker"]

    def test_reserved_groups_are_never_prompted_or_recorded_even_with_only(self) -> None:
        ask, asked = self.ask_all(True)
        plan = consent.resolve_consents(
            GuardState(),
            only=["alias"],
            assume_yes=True,
            interactive=True,
            ask=ask,
        )
        assert asked == [] and plan.accepted == [] and plan.asked == []
        assert plan.reserved == ["alias"]
        assert all("nothing to install" in n for n in plan.notices())
        st = GuardState()
        consent.record(st, plan, today="2026-11-02")
        assert st.consents == {}

    def test_a_group_unavailable_on_this_machine_is_never_asked_or_recorded(self) -> None:
        """G10: no consent for nothing: ``hooks`` on git < 2.54, ``repo_hooks`` on newer git."""
        ask, asked = self.ask_all(True)
        why = {"hooks": "E-GIT-OLD: old", "repo_hooks": "not needed"}
        plan = consent.resolve_consents(
            GuardState(), only=None, assume_yes=False, interactive=True, ask=ask, unavailable=why
        )
        assert asked == ["g2", "sudo-docker", "read-edit-denies", "config-edit"]
        assert plan.unavailable == why and "hooks" not in plan.accepted + plan.declined
        assert "`hooks`: E-GIT-OLD: old" in plan.notices()
        explicit = consent.resolve_consents(
            GuardState(), only=["hooks"], assume_yes=True, interactive=False, unavailable=why
        )  # even a named group with --yes
        assert explicit.accepted == [] and explicit.asked == []
        st = GuardState()
        consent.record(st, explicit, today="2026-11-02")
        assert st.consents == {}

    def test_recorded_decisions_stand_without_asking_again(self) -> None:
        st = accepted("g2")
        st.consent("sudo-docker", "declined", "2026-11-01")
        ask, asked = self.ask_all(True)
        plan = consent.resolve_consents(st, only=None, assume_yes=False, interactive=True, ask=ask)
        assert asked == ["hooks", "read-edit-denies", "config-edit", "repo_hooks"]  # never decided
        assert plan.declined == ["sudo-docker"] and "g2" in plan.accepted

    def test_naming_a_declined_group_asks_again(self) -> None:
        st = GuardState()
        st.consent("sudo-docker", "declined", "2026-11-01")
        plan = consent.resolve_consents(
            st, only=["sudo-docker"], assume_yes=True, interactive=False
        )
        assert plan.accepted == ["sudo-docker"]
        consent.record(st, plan, today="2026-11-05")
        assert st.consents["sudo-docker"] == {
            "decision": "accepted",
            "date": "2026-11-05",
            "rev": 1,
        }

    def test_record_writes_only_what_was_decided(self) -> None:
        st = accepted("g2")
        plan = consent.resolve_consents(st, only=None, assume_yes=True, interactive=False)
        assert "g2" not in plan.asked  # already recorded, not re-decided
        consent.record(st, plan, today="2026-11-09")
        assert st.consents["g2"]["date"] == "2026-11-02"
        assert st.consents["config-edit"]["date"] == "2026-11-09"

    def test_a_missing_ask_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError):
            consent.resolve_consents(GuardState(), only=None, assume_yes=False, interactive=True)


class TestOnlyParsing:
    def test_none_when_not_given(self) -> None:
        assert consent.parse_only(None) is None

    def test_accepts_all_seven_names(self) -> None:
        names = "g2,hooks,sudo-docker,read-edit-denies,config-edit,alias,repo_hooks"
        assert consent.parse_only(names) == names.split(",")

    def test_spaces_and_duplicates(self) -> None:
        assert consent.parse_only("g2, sudo-docker,g2") == ["g2", "sudo-docker"]

    def test_unknown_group_names_the_valid_ones(self) -> None:
        with pytest.raises(ValueError, match="nope") as exc:
            consent.parse_only("g2,nope")
        assert "valid groups: g2, hooks, sudo-docker" in str(exc.value)

    def test_empty_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            consent.parse_only(" , ")


class TestUpgrade:
    def test_a_statement_added_to_a_consented_group_applies_with_a_diff(
        self, tmp_path: Path, fake_opencode, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        st = accepted("sudo-docker")
        wanted = consent.desired_statements(st, home=str(tmp_path))
        fake_opencode(config_sequence=[_dbg([]), _dbg(wanted)])
        policies.apply(tmp_path, st, wanted, backup_root=backups_dir(tmp_path) / "a")

        # A later Carter adds a statement to the same group.
        data = json.loads(json.dumps(policyset._data()))
        data["policy_set"].append(
            {"id": "deny-podman", "group": "sudo-docker", "action": "tool.use",
             "resource": "shell:podman *", "effect": "deny", "rfc": "t"}
        )  # fmt: skip
        monkeypatch.setattr(policyset, "_data", lambda: data)
        newer = consent.desired_statements(st, home=str(tmp_path))
        fake_opencode(config_sequence=[_dbg(wanted), _dbg(newer)])
        res = policies.apply(tmp_path, st, newer, backup_root=backups_dir(tmp_path) / "b")
        assert res.added == ["deny-podman"] and res.removed == []

    def test_a_new_group_is_not_applied_without_consent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        st = accepted("g2")
        data = json.loads(json.dumps(policyset._data()))
        data["consent_groups"].append({"id": "newgroup", "live": True, "effect": "something new"})
        data["policy_set"].append(
            {"id": "deny-new", "group": "newgroup", "action": "tool.use",
             "resource": "shell:new *", "effect": "deny", "rfc": "t"}
        )  # fmt: skip
        monkeypatch.setattr(policyset, "_data", lambda: data)
        assert "deny-new" not in [s.id for s in consent.desired_statements(st, home=HOME)]
        plan = consent.resolve_consents(st, only=None, assume_yes=False, interactive=False)
        assert plan.skipped  # a plain non-interactive install does not pick it up either

    def test_no_init_templatedir_or_alias_is_written_in_1g(self) -> None:
        text = json.dumps(policyset._data())
        assert "templateDir" not in text and "alias.ai-commit" not in text


def _dbg(statements) -> str:
    items = [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in statements]
    return json.dumps({"providers": {"anthropic": {}}, "policies": items})


def test_the_target_file_is_created_under_the_base_dir(tmp_path: Path, fake_opencode) -> None:
    st = accepted("sudo-docker")
    wanted = consent.desired_statements(st, home=str(tmp_path))
    fake_opencode(config_sequence=[_dbg([]), _dbg(wanted)])
    policies.apply(tmp_path, st, wanted, backup_root=backups_dir(tmp_path) / "a")
    assert config_target(tmp_path).is_file()
