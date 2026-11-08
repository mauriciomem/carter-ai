"""D65 for the B tools: ``g2`` revision 3 (plan 007 step 17, freeze B9).

A user at revision 2 has the plugin and its shell isolation; the B tools (``carter_push``,
for devops) are new content that needs its own yes. Until then ``isolation.json``
says ``b_enabled: false`` and the plugin registers nothing. Bare ``--yes``, ``carter install``
and every non-TTY run leave revision 2 alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import consent, plugin
from carter.guard.state import GuardState, load, save
from carter.install.paths import (
    guard_state_path,
    headless_profile_path,
    isolation_path,
    plugin_dir,
)
from guard.helpers import debug_config, verbose

PENDING = "need your confirmation"


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False, **kw)


def rev2(stack) -> None:
    """A 2a/2b/2c install: g2 at revision 2 with the plugin written, B off."""
    stack.fake()
    state = GuardState()
    for g in ("g2", "sudo-docker", "read-edit-denies", "config-edit"):
        state.consent(g, "accepted", "2026-11-01", 2 if g == "g2" else 1)
    save(state, guard_state_path(None))
    stack.fake()
    assert guard("install", "--yes", "--only", "sudo-docker").exit_code == 0
    plugin.install(None, load(guard_state_path(None)), lambda _t: None, allow_temp=True)
    save_state = load(guard_state_path(None))
    save(save_state, guard_state_path(None))


def iso_plugin() -> dict:
    return json.loads(isolation_path(None).read_text())["plugin"]


def state_g2() -> dict:
    return load(guard_state_path(None)).consents["g2"]


def plugin_hash_matches() -> bool:
    from carter.hostcheck_g2 import BAKED
    from carter.identity.isolation import sha256_hex

    baked = BAKED.search((plugin_dir(None) / "index.ts").read_text())
    return bool(baked) and baked.group(1) == sha256_hex(isolation_path(None).read_bytes())


class TestRevisionTwoUserKeepsB_Off:
    def test_the_precondition(self, stack) -> None:
        rev2(stack)
        assert iso_plugin()["b_enabled"] is False and iso_plugin()["b_git"] == ""
        assert state_g2()["rev"] == 2 and not headless_profile_path(None).exists()
        assert consent.plugin_wanted(load(guard_state_path(None)))
        assert not consent.broker_wanted(load(guard_state_path(None)))

    @pytest.mark.parametrize("args", [("install", "--yes"), ("install",)])
    def test_a_bare_yes_or_a_non_tty_run_changes_nothing(self, stack, human_tty, args) -> None:
        rev2(stack)
        human_tty(False)
        before = (isolation_path(None).read_bytes(), state_g2())
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard(*args)
        assert res.exit_code == 0, res.output
        assert (isolation_path(None).read_bytes(), state_g2()) == before
        assert iso_plugin()["b_enabled"] is False and not headless_profile_path(None).exists()
        if args == ("install", "--yes"):
            assert PENDING in res.output and "B tool" in res.output

    def test_a_yes_in_a_terminal_without_the_group_named_still_waits(
        self, stack, human_tty
    ) -> None:
        rev2(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and PENDING in res.output and iso_plugin()["b_enabled"] is False

    def test_carter_install_yes_runs_the_same_rule(self, stack, human_tty) -> None:
        from carter.guard import wiring

        rev2(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert wiring.install_guards(None, assume_yes=True) == 0
        assert state_g2()["rev"] == 2 and iso_plugin()["b_enabled"] is False


class TestConfirming:
    def test_yes_only_g2_moves_to_revision_3_and_turns_b_on_with_one_consistent_pair(
        self, stack, human_tty
    ) -> None:
        rev2(stack)
        human_tty(False)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "g2")
        assert res.exit_code == 0, res.output
        assert state_g2()["rev"] == 3
        doc = iso_plugin()
        assert (
            doc["b_enabled"] is True
            and doc["b_git"].startswith("/")
            and doc["b_caller"] == "carter-devops"
        )
        assert plugin_hash_matches(), "isolation.json and the plugin are re-rendered together"
        assert (plugin_dir(None) / "broker.ts").exists() and headless_profile_path(None).exists()
        assert "restart the OpenCode server" in res.output
        assert "convenience, not a security boundary" in res.output
        assert "B tool: carter_push is enabled for devops" in res.output

    def test_a_tty_yes_shows_what_b_is_before_the_question(self, stack, human_tty) -> None:
        rev2(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", input="y\n")
        out = res.output
        assert res.exit_code == 0, out
        assert out.index("`carter_push`") < out.index("Install?")
        assert "approve" in out and "your SSH agent is used only for that approved push" in out
        assert "carter guard remove --only broker" in out
        assert state_g2()["rev"] == 3 and iso_plugin()["b_enabled"] is True

    def test_a_tty_no_keeps_revision_2_records_the_offer_and_nobody_asks_again(
        self, stack, human_tty
    ) -> None:
        rev2(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", input="n\n")
        assert res.exit_code == 0
        state = load(guard_state_path(None))
        assert state.consents["g2"]["rev"] == 2
        assert state.extra["consent_offers"]["g2"] == {
            "rev": 3,
            "decision": "declined",
            "date": state.extra["consent_offers"]["g2"]["date"],
        }
        assert iso_plugin()["b_enabled"] is False and not headless_profile_path(None).exists()
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        again = guard("install", input="y\n")
        assert "g2 r3" not in again.output.split("Install?")[0] and state_g2()["rev"] == 2
        # the human can still change their mind, explicitly
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert guard("install", "--yes", "--only", "g2").exit_code == 0 and state_g2()["rev"] == 3

    def test_a_fresh_yes_install_goes_to_revision_3_in_one_step(self, stack, human_tty) -> None:
        human_tty(True)
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        assert state_g2()["rev"] == 3 and iso_plugin()["b_enabled"] is True


class TestUndo:
    def confirmed(self, stack, human_tty) -> None:
        rev2(stack)
        human_tty(False)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert guard("install", "--yes", "--only", "g2").exit_code == 0

    def test_remove_only_broker_turns_b_off_and_keeps_the_rest_of_g2(
        self, stack, human_tty
    ) -> None:
        self.confirmed(stack, human_tty)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--yes", "--only", "broker")
        assert res.exit_code == 0, res.output
        assert state_g2()["rev"] == 2
        assert iso_plugin()["b_enabled"] is False and plugin_hash_matches()
        assert (plugin_dir(None) / "index.ts").exists() and isolation_path(None).exists()
        assert not headless_profile_path(None).exists() and "B is off" in res.output
        offer = load(guard_state_path(None)).extra["consent_offers"]["g2"]
        assert offer["rev"] == 3 and offer["decision"] == "declined"

    def test_a_bare_yes_does_not_bring_b_back(self, stack, human_tty) -> None:
        self.confirmed(stack, human_tty)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        guard("remove", "--yes", "--only", "broker")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        guard("install", "--yes")
        assert state_g2()["rev"] == 2 and iso_plugin()["b_enabled"] is False

    def test_remove_only_plugin_takes_the_profile_and_broker_ts_too(self, stack, human_tty) -> None:
        self.confirmed(stack, human_tty)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert guard("remove", "--yes", "--only", "plugin").exit_code == 0
        assert (
            not headless_profile_path(None).exists()
            and not (plugin_dir(None) / "broker.ts").exists()
        )

    def test_a_full_remove_takes_every_b_file(self, stack, human_tty) -> None:
        self.confirmed(stack, human_tty)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert guard("remove", "--yes").exit_code == 0
        assert (
            not headless_profile_path(None).exists()
            and not (plugin_dir(None) / "broker.ts").exists()
        )
        assert not isolation_path(None).exists()

    def test_an_edited_profile_is_kept_and_reported(self, stack, human_tty) -> None:
        self.confirmed(stack, human_tty)
        headless_profile_path(None).write_text("{}\n")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--yes", "--only", "broker")
        assert headless_profile_path(None).exists() and "kept" in res.output

    def test_the_dry_run_names_the_broker_step(self, stack, human_tty) -> None:
        self.confirmed(stack, human_tty)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("remove", "--dry-run", "--only", "broker")
        assert "g2 would go back to revision 2" in res.output and state_g2()["rev"] == 3


class TestNoGit:
    def test_without_a_git_in_the_fixed_directories_b_stays_off_and_says_why(
        self, stack, human_tty, monkeypatch
    ) -> None:
        rev2(stack)
        human_tty(False)
        monkeypatch.setattr(plugin, "find_tool", lambda name, dirs=(): "")
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "g2")
        assert res.exit_code == 0 and iso_plugin()["b_enabled"] is False
        assert "B tools not enabled: no git found" in res.output
        assert not headless_profile_path(None).exists()


class TestGitAndGhArePinnedAtInstall:
    def test_the_paths_come_from_the_fixed_directories_never_from_path(
        self, monkeypatch, tmp_path: Path
    ) -> None:
        fake = tmp_path / "evil"
        fake.mkdir()
        (fake / "git").write_text("#!/bin/sh\n")
        (fake / "git").chmod(0o755)
        monkeypatch.setenv("PATH", f"{fake}:/usr/bin")
        assert plugin.find_tool("git") != str(fake / "git")
        assert plugin.find_tool("git") in {f"{d}/git" for d in plugin.TOOL_DIRS}
        assert plugin.find_tool("definitely-not-a-tool") == ""
