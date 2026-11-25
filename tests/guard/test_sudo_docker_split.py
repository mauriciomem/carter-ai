"""``sudo-docker`` is two statements: ``sudo`` is the floor, ``docker`` is a group.

The floor denies (``sudo`` and its relatives) are rendered into every Carter agent whenever
Carter keeps a guard state, whatever was consented. An existing ``guard-state.json`` that records
``sudo-docker`` migrates without a new prompt and no rule is loosened.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from carter import access, hostcheck_g2
from carter.cli import main
from carter.gate import check
from carter.guard import agent_rules, consent
from carter.guard.state import GuardState, load, save
from carter.identity.policyset import (
    consent_groups,
    floor_statements,
    policy_set,
    policy_statements,
)
from carter.install.paths import guard_state_path, isolation_path
from guard.helpers import verbose

HOME = "/home/u"
OLD = "sudo-docker"
SUDO, DOCKER = "shell:sudo *", "shell:docker *"
FLOOR_VERBS = (
    "sudo",
    "sudoedit",
    "sudo-rs",
    "doas",
    "pkexec",
    "run0",
    "su -c",
    "su -lc",
    "su root -c",
    "machinectl shell",
)
CONTAINER_VERBS = ("docker", "podman", "nerdctl", "docker-compose", "buildah")
CONSENT_REVS = {"g2": 3, "hooks": 2, "read-edit-denies": 1, "config-edit": 2}


def guard(*args: str, input: str | None = None):  # type: ignore[no-untyped-def]
    return CliRunner().invoke(main, ["guard", *verbose(args)], input=input, catch_exceptions=False)


def write_old_state(sudo_docker: str | None, **others: str | None) -> None:
    """What an earlier Carter wrote: ``sudo-docker`` and the other groups, as the file reads.
    A group set to ``None`` has no record."""
    consents = {
        name: {"decision": others.get(name, "accepted"), "date": "2026-11-03", "rev": rev}
        for name, rev in CONSENT_REVS.items()
        if others.get(name, "accepted") is not None
    }
    if sudo_docker:
        consents[OLD] = {"decision": sudo_docker, "date": "2026-11-03", "rev": 1}
    path = guard_state_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": 1, "consents": consents}, indent=2) + "\n")


def isolation_declined() -> list[str]:
    return json.loads(isolation_path(None).read_text())["plugin"]["declined_groups"]


def resources(state: GuardState) -> set[str]:
    rules = agent_rules.rules_for(state, home=HOME)
    return {f"{r['action']}:{r['resource']}" for r in rules if r["effect"] == "deny"}


class TestTheData:
    def test_the_groups_are_docker_not_sudo_docker(self) -> None:
        ids = [g.id for g in consent_groups()]
        assert OLD not in ids and "docker" in ids and "sudo" not in ids

    def test_sudo_is_the_floor_and_docker_has_its_own_group(self) -> None:
        groups = {s.id: s.group for s in policy_set()}
        assert groups["deny-sudo"] == "floor" and groups["deny-docker"] == "docker"

    def test_docker_alone_denies_only_docker_and_no_group_carries_sudo(self) -> None:
        assert [s.resource for s in policy_statements(("docker",), home=HOME)] == [
            f"shell:{verb} *" for verb in CONTAINER_VERBS
        ]
        every = {s.resource for s in policy_statements(home=HOME)}
        assert SUDO not in every and SUDO in {s.resource for s in floor_statements(home=HOME)}

    def test_the_gate_asks_each_verb_of_its_group(self) -> None:
        skip = ("docker",)  # a declined docker group
        for verb in ("docker", "podman"):
            assert check(f"{verb} ps", skip_groups=skip).rule is None
            assert check(f"{verb} ps").rule == "other-verbs"
        for verb in ("sudo", "doas", "pkexec"):
            assert check(f"{verb} ls", skip_groups=skip).rule == "other-verbs"

    def test_program_text_is_judged_word_by_word(self) -> None:
        skip = ("docker",)
        assert check("python3 -c \"os.system('docker ps')\"", skip_groups=skip).rule is None
        assert check("python3 -c \"os.system('sudo ls')\"", skip_groups=skip).rule == "other-verbs"
        both = "python3 -c \"os.system('docker ps; sudo ls')\""
        assert check(both, skip_groups=skip).rule == "other-verbs"  # sudo is still named

    def test_sudo_is_no_group_floor_and_g2_off_does_not_claim_it_is_open(self) -> None:
        assert not any("sudo" in ids for ids in access.GROUP_FLOORS.values())
        assert OLD not in access.GROUP_FLOORS
        (line,) = access.missing_group_lines(["hooks", "read-edit-denies", "config-edit", "docker"])
        assert line.startswith("! g2 off: ") and "sudo" not in line


class TestTheMigration:
    def test_an_accepted_record_becomes_an_accepted_docker_record(self) -> None:
        write_old_state("accepted")
        state = load(guard_state_path(None))
        assert OLD not in state.consents
        assert state.consents["docker"] == {"decision": "accepted", "date": "2026-11-03", "rev": 1}

    def test_a_declined_record_becomes_a_declined_docker_record(self) -> None:
        write_old_state("declined")
        state = load(guard_state_path(None))
        assert OLD not in state.consents and state.consents["docker"]["decision"] == "declined"

    @pytest.mark.parametrize(
        ("old", "new", "wanted"),
        [
            ("declined", "accepted", "accepted"),  # an older Carter declined, the new one accepted
            ("accepted", "declined", "accepted"),  # the order of the writes does not matter
            ("accepted", "accepted", "accepted"),
            ("declined", "declined", "declined"),
        ],
    )
    def test_when_both_names_are_recorded_an_accepted_one_wins(
        self, old: str, new: str, wanted: str
    ) -> None:
        write_old_state(old)
        path = guard_state_path(None)
        data = json.loads(path.read_text())
        data["consents"]["docker"] = {"decision": new, "date": "2026-11-20", "rev": 1}
        path.write_text(json.dumps(data))
        state = load(path)
        assert OLD not in state.consents and state.consents["docker"]["decision"] == wanted

    def test_the_record_under_the_new_name_keeps_its_date_when_nothing_is_accepted(self) -> None:
        write_old_state("declined")
        path = guard_state_path(None)
        data = json.loads(path.read_text())
        data["consents"]["docker"] = {"decision": "declined", "date": "2026-11-20", "rev": 1}
        path.write_text(json.dumps(data))
        assert load(path).consents["docker"]["date"] == "2026-11-20"

    def test_nothing_recorded_stays_nothing_recorded(self) -> None:
        write_old_state(None)
        assert "docker" not in load(guard_state_path(None)).consents

    def test_the_next_save_writes_the_new_name(self) -> None:
        write_old_state("accepted")
        path = guard_state_path(None)
        state = load(path)
        state.consent("hooks", "accepted", "2026-11-25", 2)  # any change
        save(state, path)
        assert OLD not in json.loads(path.read_text())["consents"]
        assert "docker" in json.loads(path.read_text())["consents"]

    def test_a_schema_1_file_is_read_and_the_next_save_writes_schema_2(self) -> None:
        """An older Carter then calls the file "newer" and keeps every deny (it would otherwise
        read it as "no sudo-docker consent" and render neither deny)."""
        write_old_state("accepted")
        path = guard_state_path(None)
        assert json.loads(path.read_text())["schema"] == 1
        state = load(path)
        assert state.schema == 2
        state.consent("hooks", "accepted", "2026-11-25", 2)
        save(state, path)
        assert json.loads(path.read_text())["schema"] == 2

    def test_a_reader_that_knows_only_schema_1_refuses_the_new_file(self) -> None:
        """The older Carter's own rule, applied to the number we write: newer means refused."""
        state = GuardState()
        assert state.schema > 1  # what an older ``load`` compares against its SCHEMA (1)

    def test_the_migrated_record_is_not_stale_so_nobody_is_asked(self) -> None:
        write_old_state("accepted")
        state = load(guard_state_path(None))
        assert consent.reconsent_pending(state) == []
        assert consent.to_offer(state, only=None, unavailable={"repo_hooks": "x"}) == []


class TestNoRuleIsLoosened:
    def test_accepted_renders_the_same_rules_as_before(self) -> None:
        write_old_state("accepted")
        before = {"shell:git push *", SUDO, DOCKER}  # what the old group and g2 denied
        got = resources(load(guard_state_path(None)))
        assert before <= got
        assert {s.resource for s in policy_set() if s.group in ("g2", "docker")} <= got

    def test_declined_keeps_docker_open_and_now_denies_sudo(self) -> None:
        write_old_state("declined")
        got = resources(load(guard_state_path(None)))
        assert DOCKER not in got  # the user's own decision stands
        assert SUDO in got  # tighter than before, never looser

    def test_the_gate_skip_list_follows_the_migrated_state(self) -> None:
        write_old_state("declined")
        assert consent.declined_groups(load(guard_state_path(None))) == ["docker"]

    def test_never_decided_stays_denied_for_g2_users(self) -> None:
        write_old_state(None)
        got = resources(load(guard_state_path(None)))
        assert SUDO in got and DOCKER not in got  # docker waits for its own consent

    @pytest.mark.parametrize("old", ["accepted", "declined", None])
    @pytest.mark.parametrize("g2", ["accepted", "declined", None])
    def test_sudo_is_denied_in_every_combination_of_the_old_and_the_new_state(
        self, g2: str | None, old: str | None
    ) -> None:
        """No state may open ``sudo`` (the review's loosening case: g2 declined or never decided
        with ``sudo-docker`` accepted used to deny it, and must still)."""
        write_old_state(old, g2=g2)
        got = resources(load(guard_state_path(None)))
        assert {f"shell:{verb} *" for verb in FLOOR_VERBS} <= got, (g2, old)
        assert (DOCKER in got) == (old == "accepted")  # docker follows the old record

    def test_the_floor_rules_are_rendered_even_with_no_group_accepted(self) -> None:
        got = resources(GuardState())  # a state that holds nothing yet
        assert {f"shell:{verb} *" for verb in FLOOR_VERBS} <= got
        assert "shell:git push *" not in got and DOCKER not in got

    def test_an_unreadable_state_keeps_the_floor_too(self) -> None:
        path = guard_state_path(None)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken")
        got = agent_rules.current_rules(home=HOME)
        assert {f"shell:{verb} *" for verb in FLOOR_VERBS} <= {
            f"{r['action']}:{r['resource']}" for r in got
        }

    def test_no_state_at_all_renders_nothing_and_access_says_sudo_is_open(self) -> None:
        assert agent_rules.current_rules(home=HOME) == []
        lines = access.missing_group_lines([], state=False)
        assert lines[0] == "! g2 off: push, gh_api, github_admin, sudo, carter_internals"


class TestTheCommands:
    def test_install_does_not_ask_again_and_writes_the_new_name(self, stack, human_tty) -> None:
        human_tty(True)
        write_old_state("accepted")
        stack.fake()
        res = guard("install", input="y\n")
        assert res.exit_code == 0, res.output
        assert "Install?" not in res.output
        consents = json.loads(guard_state_path(None).read_text())["consents"]
        assert OLD not in consents and consents["docker"]["decision"] == "accepted"

    def test_a_new_install_offers_docker_in_the_one_question(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n")
        head = res.output.split("Install?")[0]
        assert "docker" in head and "agents can't use docker" in head and "sudo" not in head

    def test_declining_docker_leaves_sudo_denied(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        offered = consent.to_offer(GuardState(), only=None, unavailable={"repo_hooks": "x"})
        answers = "n\n" + "".join("n\n" if g == "docker" else "y\n" for g in offered)
        assert guard("install", input=answers).exit_code == 0
        got = resources(load(guard_state_path(None)))
        assert DOCKER not in got and SUDO in got

    def test_install_writes_the_new_name_into_isolation_json(self, stack) -> None:
        write_old_state("declined")
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        assert isolation_declined() == ["docker"]
        assert "docker" in guard("status").output

    def test_an_isolation_json_of_the_old_name_is_flagged_and_fixed_by_install(self, stack) -> None:
        write_old_state("declined")
        stack.fake()
        guard("install", "--yes")
        path = isolation_path(None)
        doc = json.loads(path.read_text())
        doc["plugin"]["declined_groups"] = [OLD]  # what the earlier Carter wrote
        path.write_text(json.dumps(doc))
        state = load(guard_state_path(None))
        state.record_file(path, path.read_bytes())  # unedited, as far as Carter knows
        save(state, guard_state_path(None))
        items = hostcheck_g2.g2_items(load(guard_state_path(None)), None)
        assert any("disagree on declined groups" in item.text for item in items)
        assert guard("install", "--yes").exit_code == 0
        assert isolation_declined() == ["docker"]

    def test_access_says_when_docker_is_off(self) -> None:
        lines = access.missing_group_lines(["g2", "hooks", "read-edit-denies", "config-edit"])
        assert lines == ("! docker off: agents may run docker (root-equivalent)",)
        assert all(len(line) <= 60 for line in lines)
