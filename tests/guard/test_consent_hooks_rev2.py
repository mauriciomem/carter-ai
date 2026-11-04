# ruff: noqa: E501
"""``hooks`` revision 2 asks again and never upgrades silently (plan 005 step 19; D65, H15).

Revision 1 wired ``pre-push`` only. Revision 2 adds the three commit events. A user who accepted
revision 1 keeps exactly the pre-push hook until a human confirms revision 2 in a terminal (or
names it: ``--yes --only hooks``); a bare ``--yes`` names the pending step and changes nothing.
"""

from __future__ import annotations

import subprocess

from click.testing import CliRunner

from carter.cli import main
from carter.guard import hooks
from carter.guard.state import GuardState, load, save
from carter.install.paths import carter_gitconfig_path, guard_state_path
from guard.helpers import debug_config

PENDING = "the commit checks need your confirmation (`hooks` revision 2)"
FOUR = {"pre-push", "prepare-commit-msg", "commit-msg", "post-commit"}


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False, **kw)


def written_events() -> set[str]:
    done = subprocess.run(
        ["git", "config", "--file", str(carter_gitconfig_path(None)), "--get-regexp", r"\.event$"],
        capture_output=True, text=True,
    )  # fmt: skip
    return {line.split()[1] for line in done.stdout.splitlines()}


def downgrade_to_rev1(stack) -> None:
    """An existing 2a install: hooks accepted at revision 1, only pre-push in the file."""
    stack.fake()
    assert guard("install", "--yes").exit_code == 0
    state = load(guard_state_path(None))
    state.consents["hooks"]["rev"] = 1
    save(state, guard_state_path(None))
    carter_gitconfig_path(None).unlink()
    state = load(guard_state_path(None))
    state.forget_file(carter_gitconfig_path(None))
    save(state, guard_state_path(None))
    from carter.guard import gitconfig

    text = gitconfig.render_gitconfig(hooks.hook_entries(hooks.script_path(None)))
    state = load(guard_state_path(None))
    gitconfig.install_file(carter_gitconfig_path(None), text, state)
    save(state, guard_state_path(None))
    assert written_events() == {"pre-push"}


class TestFreshInstall:
    def test_a_yes_records_revision_2_and_wires_all_four_events(self, stack) -> None:
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert load(guard_state_path(None)).consents["hooks"]["rev"] == 2
        assert written_events() == FOUR
        assert "git config: 8 key(s)" in res.output

    def test_each_event_command_is_the_self_contained_wrapper(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        for event in hooks.EVENTS:
            done = subprocess.run(
                ["git", "config", "--file", str(carter_gitconfig_path(None)), "--get",
                 f"hook.{hooks.hook_name(event)}.command"],
                capture_output=True, text=True,
            )  # fmt: skip
            assert done.stdout.rstrip("\n") == hooks.hook_command(hooks.script_path(None), event)

    def test_a_second_run_changes_nothing(self, stack) -> None:
        stack.fake()
        guard("install", "--yes")
        before = (carter_gitconfig_path(None).read_bytes(), guard_state_path(None).read_bytes())
        stack.fake(before=debug_config(stack.live))
        assert guard("install", "--yes").exit_code == 0
        assert (
            carter_gitconfig_path(None).read_bytes(),
            guard_state_path(None).read_bytes(),
        ) == before


class TestUpgradeFromRevision1:
    def test_a_bare_yes_names_the_pending_step_and_keeps_pre_push_only(self, stack) -> None:
        downgrade_to_rev1(stack)
        before = carter_gitconfig_path(None).read_bytes()
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and PENDING in res.output
        assert "carter guard install --yes --only hooks" in res.output
        assert (
            written_events() == {"pre-push"}
            and load(guard_state_path(None)).consents["hooks"]["rev"] == 1
        )
        assert carter_gitconfig_path(None).read_bytes() == before

    def test_a_terminal_yes_upgrades_with_the_explanation_first(self, stack, human_tty) -> None:
        downgrade_to_rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live))
        res = guard("install", input="y\n" * 6)
        assert res.exit_code == 0, res.output
        out = res.output
        assert out.index("hooks now also checks agent commits") < out.index("Install this group?")
        assert (
            written_events() == FOUR and load(guard_state_path(None)).consents["hooks"]["rev"] == 2
        )

    def test_yes_with_only_hooks_confirms_without_a_question(self, stack, human_tty) -> None:
        downgrade_to_rev1(stack)
        human_tty(False)
        stack.fake(before=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "hooks")
        assert res.exit_code == 0, res.output
        assert "hooks now also checks agent commits" in res.output  # explained even unasked
        assert written_events() == FOUR

    def test_a_terminal_no_keeps_pre_push_and_does_not_nag(self, stack, human_tty) -> None:
        downgrade_to_rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live))
        res = guard("install", input="n\n" * 6)
        assert res.exit_code == 0, res.output
        state = load(guard_state_path(None))
        assert state.consents["hooks"]["rev"] == 1 and written_events() == {"pre-push"}
        assert state.extra["consent_offers"]["hooks"]["decision"] == "declined"
        stack.fake(before=debug_config(stack.live))
        again = guard("install", "--yes")
        assert PENDING not in again.output  # said no already: no nagging

    def test_the_dry_run_says_what_needs_confirmation(self, stack) -> None:
        downgrade_to_rev1(stack)
        stack.fake()
        res = guard("install", "--dry-run")
        assert "needs your confirmation for revision 2" in res.output


class TestRemoveKeepsTheMirror:
    """`guard remove` takes the hooks away but never the tier mirror (`identity remove` does)."""

    def test_remove_rewrites_the_file_with_the_mirror_alone(self, stack) -> None:
        from carter.guard import mirror_io
        from carter.identity.schema import Identity, IdentityConfig

        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        state = load(guard_state_path(None))
        cfg = IdentityConfig(
            identity=Identity(login="b", id=7, email="7+b@users.noreply.github.com"),
            state="current",
        )
        mirror_io.sync(None, state, cfg)
        save(state, guard_state_path(None))
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        keys = [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(None))]
        assert keys == ["carter.tier", "carter.llmEmail"]
        assert not hooks.script_path(None).exists()

    def test_install_after_a_mirror_keeps_it(self, stack) -> None:
        from carter.guard import mirror_io
        from carter.identity.schema import Identity, IdentityConfig

        cfg = IdentityConfig(
            identity=Identity(login="b", id=7, email="7+b@users.noreply.github.com"),
            state="current",
        )
        state = GuardState()
        mirror_io.sync(None, state, cfg)  # what `identity add` does: write, record, save
        save(state, guard_state_path(None))
        stack.fake()
        assert guard("install", "--yes").exit_code == 0
        keys = [k for k, _ in mirror_io.read_entries(carter_gitconfig_path(None))]
        assert (
            keys[:2] == ["carter.tier", "carter.llmEmail"]
            and "hook.carter-guard-pre-push.event" in keys
        )
