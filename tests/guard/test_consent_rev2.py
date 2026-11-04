"""D65: ``g2`` revision 2 asks again, and never upgrades silently (plan 004 step 27).

The plugin changes the environment of every agent shell. Until a human confirms in a terminal
(or passes ``--yes --only g2``), the plugin and ``isolation.json`` are not installed and the 1G
denies stay.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.cli import main
from carter.guard import consent
from carter.guard.state import GuardState, load
from carter.identity.errors import E_STATE_INVALID
from carter.install.paths import guard_state_path, isolation_path, plugin_dir
from guard.helpers import debug_config

PENDING = "plugin and isolation need your confirmation"


def guard(*args: str, **kw):
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False, **kw)


def rev1(stack) -> None:
    """A 1G install: g2 accepted at revision 1, no plugin (what every existing user has)."""
    stack.fake()
    state = GuardState()
    for g in ("g2", "sudo-docker", "read-edit-denies", "config-edit"):
        state.consent(g, "accepted", "2026-11-01", 1)
    from carter.guard.state import save

    save(state, guard_state_path(None))
    stack.fake()
    assert guard("install", "--yes", "--only", "sudo-docker").exit_code == 0
    assert load(guard_state_path(None)).consents["g2"]["rev"] == 1


def plugin_present() -> bool:
    return isolation_path(None).exists() or plugin_dir(None).exists()


class TestMatrix:
    def resolve(self, state: GuardState, **kw):
        defaults = {"only": None, "assume_yes": False, "interactive": True, "ask": lambda g: True}
        return consent.resolve_consents(state, **{**defaults, **kw})

    def test_a_fresh_install_asks_g2_at_revision_2(self) -> None:
        asked: list[str] = []
        plan = self.resolve(GuardState(), ask=lambda g: asked.append(g.id) or True)
        assert "g2" in asked and "g2" in plan.accepted
        st = GuardState()
        consent.record(st, plan, today="2026-11-04")
        assert st.consents["g2"] == {"decision": "accepted", "date": "2026-11-04", "rev": 2}
        assert consent.plugin_wanted(st)

    def test_accepted_at_revision_1_needs_reconsent(self) -> None:
        st = GuardState()
        st.consent("g2", "accepted", "2026-11-01", 1)
        assert consent.reconsent_pending(st) == ["g2"] and not consent.plugin_wanted(st)

    def test_declined_stays_declined_unless_named(self) -> None:
        st = GuardState()
        st.consent("g2", "declined", "2026-11-01", 1)
        plan = self.resolve(st, assume_yes=True, interactive=False)
        assert "g2" in plan.declined and "g2" not in plan.asked
        named = self.resolve(st, only=["g2"], assume_yes=True, interactive=False)
        assert named.accepted == ["g2"] and named.asked == ["g2"]

    def test_accepted_at_revision_2_is_done(self) -> None:
        st = GuardState()
        st.consent("g2", "accepted", "2026-11-01", 2)
        asked: list[str] = []
        plan = self.resolve(st, ask=lambda g: asked.append(g.id) or True)
        assert "g2" in plan.accepted and "g2" not in asked + plan.asked and not plan.pending

    @pytest.mark.parametrize("interactive", [False, True])
    def test_a_bare_yes_leaves_revision_1_alone(self, interactive: bool) -> None:
        st = GuardState()
        st.consent("g2", "accepted", "2026-11-01", 1)
        plan = self.resolve(st, assume_yes=True, interactive=interactive)
        assert plan.pending == ["g2"] and "g2" not in plan.asked
        assert any(PENDING in n for n in plan.notices())

    def test_a_tty_yes_upgrades_and_a_tty_no_is_recorded_as_an_offer(self) -> None:
        st = GuardState()
        st.consent("g2", "accepted", "2026-11-01", 1)
        yes = self.resolve(st, ask=lambda g: True)
        no = self.resolve(st, ask=lambda g: False)
        assert "g2" in yes.asked and "g2" in yes.accepted
        assert no.refused_offers == ["g2"] and "g2" not in no.asked
        consent.record(st, no, today="2026-11-04")
        assert st.consents["g2"] == {"decision": "accepted", "date": "2026-11-01", "rev": 1}
        assert st.extra["consent_offers"] == {
            "g2": {"rev": 2, "decision": "declined", "date": "2026-11-04"}
        }
        seen: list[str] = []
        again = self.resolve(st, ask=lambda g: seen.append(g.id) or True)
        assert "g2" not in seen and not again.pending  # no nagging after a refusal
        named = self.resolve(st, only=["g2"], assume_yes=True, interactive=False)
        assert named.asked == ["g2"]  # --only g2 asks again
        consent.record(st, named, today="2026-11-05")
        assert st.consents["g2"]["rev"] == 2 and "consent_offers" not in st.extra


class TestNoSilentUpgrade:
    @pytest.mark.parametrize(
        "args", [("install", "--yes"), ("install",), ("install", "--yes", "--only", "sudo-docker")]
    )
    def test_guard_install_without_a_confirmation_changes_nothing(
        self, stack, args: tuple[str, ...], human_tty
    ) -> None:
        rev1(stack)
        human_tty(False)
        before = load(guard_state_path(None)).consents["g2"]
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard(*args)
        assert res.exit_code == 0, res.output
        assert not plugin_present() and load(guard_state_path(None)).consents["g2"]["rev"] == 1
        assert load(guard_state_path(None)).consents["g2"] == before  # not even re-dated
        if args == ("install", "--yes"):
            assert PENDING in res.output
        if args == ("install",):
            assert "no terminal and no --yes" in res.output

    def test_a_yes_names_the_pending_step_and_still_exits_0(self, stack, human_tty) -> None:
        rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes")
        assert res.exit_code == 0 and PENDING in res.output and "carter guard install" in res.output
        assert not plugin_present()

    def test_carter_install_yes_runs_the_same_rule(self, stack, human_tty) -> None:
        from carter.guard import wiring

        rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        assert wiring.install_guards(None, assume_yes=True) == 0
        assert not plugin_present() and load(guard_state_path(None)).consents["g2"]["rev"] == 1

    def test_yes_with_only_g2_confirms_and_installs(self, stack, human_tty) -> None:
        rev1(stack)
        human_tty(False)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", "--yes", "--only", "g2")
        assert res.exit_code == 0, res.output
        assert load(guard_state_path(None)).consents["g2"]["rev"] == 2
        assert plugin_dir(None).joinpath("index.ts").exists() and isolation_path(None).exists()
        assert "no SSH agent" in res.output  # the explanation is printed even without a question

    def test_a_tty_yes_confirms_with_the_explanation_before_the_question(
        self, stack, human_tty
    ) -> None:
        rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", input="y\n" * 6)
        out = res.output
        assert res.exit_code == 0, out
        assert out.index("no SSH agent") < out.index("Install this group?")
        assert load(guard_state_path(None)).consents["g2"]["rev"] == 2 and plugin_present()

    def test_a_tty_no_keeps_the_denies_and_installs_nothing(self, stack, human_tty) -> None:
        rev1(stack)
        human_tty(True)
        stack.fake(before=debug_config(stack.live), after=debug_config(stack.live))
        res = guard("install", input="n\n" * 6)
        state = load(guard_state_path(None))
        assert res.exit_code == 0 and not plugin_present()
        assert state.consents["g2"] == {"decision": "accepted", "date": "2026-11-01", "rev": 1}
        assert state.extra["consent_offers"]["g2"]["decision"] == "declined"
        assert state.opencode_policies  # the 1G denies keep working

    def test_the_dry_run_says_the_plugin_needs_confirmation(self, stack) -> None:
        rev1(stack)
        stack.fake()
        res = guard("install", "--dry-run")
        assert (
            "needs your confirmation for revision 2" in res.output
            and "would write" not in res.output
        )


class TestExplanation:
    def test_the_text_holds_the_facts_a_person_needs(self) -> None:
        g2 = next(g for g in consent.consent_groups() if g.id == "g2")
        text = " ".join(g2.explain)
        for fact in (
            "no SSH agent", "read-only GitHub token", "no push", "unsigned",
            "does NOT change your own terminal", "`!` shell",
            "guard-state.json", "isolation.json",
            "carter guard remove --only plugin", "plugins/carter", "Restart the OpenCode server",
        ):  # fmt: skip
            assert fact in text, fact
        assert len(g2.explain) <= 15 and all("slice" not in line for line in g2.explain)


class TestStateSafety:
    def test_a_corrupt_state_is_never_rewritten(self, stack) -> None:
        stack.fake()
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        res = guard("install", "--yes", "--only", "g2")
        assert res.exit_code != 0 or E_STATE_INVALID in res.output or "unreadable" in res.output
        assert path.read_text() == "{broken" or list(path.parent.glob("guard-state.json.corrupt-*"))

    def test_a_newer_state_is_never_rewritten(self, stack) -> None:
        stack.fake()
        path = guard_state_path(None)
        path.parent.mkdir(parents=True)
        path.write_text('{"schema": 99}')
        res = guard("install", "--yes", "--only", "g2")
        assert res.exit_code == 1 and E_STATE_INVALID in res.output
        assert path.read_text() == '{"schema": 99}'


def test_the_unrelated_home_is_untouched(stack, home: Path) -> None:
    assert not (home / ".carter").exists()
