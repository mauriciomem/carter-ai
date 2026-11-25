"""Review follow-ups of the consent UX: the all-no run when guards are already installed, the
short lines, and the one warning when a broken config hides the commit-hooks re-ask."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner, Result

from carter import hostcheck_g2, ui
from carter.cli import main
from carter.guard import consent
from carter.guard.state import GuardState, load
from carter.install.paths import guard_state_path, isolation_path
from guard.helpers import decline, verbose

ONE = "read-edit-denies"
POINTER = "see: carter guard --help"


def guard(*args: str, input: str | None = None) -> Result:
    ui.configure(verbose=False)
    return CliRunner().invoke(main, ["guard", *verbose(args)], input=input, catch_exceptions=False)


def decisions() -> dict[str, str]:
    return {g: rec["decision"] for g, rec in load(guard_state_path(None)).consents.items()}


def isolation_declined() -> list[str]:
    return json.loads(isolation_path(None).read_text())["plugin"]["declined_groups"]


def only_g2_installed(stack) -> list[str]:
    """``g2`` installed on its own; returns the groups the next question offers."""
    stack.fake()
    assert guard("install", "--yes", "--only", "g2").exit_code == 0
    return consent.to_offer(
        load(guard_state_path(None)), only=None, unavailable={"repo_hooks": "not needed"}
    )


class TestAllNoWhenSomethingIsInstalled:
    """Review #2: the decisions and ``isolation.json`` agree, and the output says one thing."""

    def run_all_no(self, stack, human_tty) -> tuple[Result, list[str]]:
        offered = only_g2_installed(stack)
        human_tty(True)
        stack.fake()
        return guard("install", input="n\n" + "n\n" * len(offered)), offered

    def test_the_decisions_are_written_and_isolation_json_follows(self, stack, human_tty) -> None:
        res, offered = self.run_all_no(stack, human_tty)
        assert res.exit_code == 0, res.output
        assert offered and {decisions()[g] for g in offered} == {"declined"}
        assert decisions()["g2"] == "accepted"
        assert isolation_declined() == sorted(offered)

    def test_check_host_sees_no_disagreement(self, stack, human_tty) -> None:
        self.run_all_no(stack, human_tty)
        items = hostcheck_g2.g2_items(load(guard_state_path(None)), None)
        assert not [item for item in items if "disagree" in item.text]

    def test_the_output_does_not_contradict_itself(self, stack, human_tty) -> None:
        res, _ = self.run_all_no(stack, human_tty)
        assert "nothing installed" not in res.output
        assert "✓ guards installed" in res.output

    def test_an_empty_machine_still_ends_with_nothing_installed(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        offered = consent.to_offer(GuardState(), only=None, unavailable={"repo_hooks": "x"})
        res = guard("install", input="n\n" + "n\n" * len(offered))
        assert "nothing installed" in res.output and not isolation_path(None).exists()


class TestShortLines:
    def test_declined_is_said_once_when_it_is_decided_not_on_every_run(
        self, stack, human_tty
    ) -> None:
        human_tty(True)
        stack.fake()
        offered = consent.to_offer(GuardState(), only=None, unavailable={"repo_hooks": "x"})
        first = guard(
            "install", input="n\n" + "".join("n\n" if g == ONE else "y\n" for g in offered)
        )
        assert f"Declined: {ONE}" in first.output
        human_tty(False)
        again = guard("install", "--yes")
        assert "Declined" not in again.output and decisions()[ONE] == "declined"

    def test_every_pointer_to_the_help_is_the_same(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        offered = consent.to_offer(GuardState(), only=None, unavailable={"repo_hooks": "x"})
        out = guard("install", input="n\n" + "".join("n\n" if g == ONE else "y\n" for g in offered))
        assert f"Declined: {ONE} ({POINTER})" in out.output
        assert "declined" in guard("status").output
        assert f"({POINTER})" in guard("status").output
        assert "install --help" not in guard("status").output

    @pytest.mark.usefixtures("at_terminal")
    def test_remove_says_which_group_is_declined_and_where_to_read(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        stack.fake()
        out = guard("remove", "--only", ONE).output.splitlines()
        assert out[-1] == f"· {ONE} declined ({POINTER})"
        assert len(out[-1]) <= ui.MAX

    @pytest.mark.usefixtures("at_terminal")
    def test_several_groups_are_listed_in_one_line(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        stack.fake()
        last = guard("remove", "--only", f"{ONE},hooks,docker,config-edit").output.splitlines()[-1]
        assert last.startswith("· ") and last.endswith(f"declined ({POINTER})")
        assert len(last) <= ui.MAX


class TestABrokenConfigHidesTheHooksReask:
    BROKEN = "schema = 2\n[identity\n"

    def test_one_warning_line_says_so(self, stack, human_tty, home) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(self.BROKEN)
        decline("hooks")
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n" * 8)
        warned = [line for line in res.output.splitlines() if "hooks not re-asked" in line]
        assert len(warned) == 1 and len(warned[0]) <= ui.MAX
        assert "see: carter check" in warned[0]

    def test_a_good_config_says_nothing_of_it(self, stack, human_tty) -> None:
        decline("hooks")
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n" * 8)
        assert "re-asked" not in res.output

    def test_without_a_declined_commit_guard_there_is_nothing_to_say(
        self, stack, human_tty, home
    ) -> None:
        (home / ".carter").mkdir(exist_ok=True)
        (home / ".carter" / "config.toml").write_text(self.BROKEN)
        human_tty(True)
        stack.fake()
        res = guard("install", input="y\n" * 8)
        assert "re-asked" not in res.output
