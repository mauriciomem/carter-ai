"""``guard remove --only`` records a decline that outlives it, so it needs a person at a terminal
and it must not leave half a change behind when a step fails."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner, Result

from carter import ui
from carter.cli import main
from carter.guard import plugin
from carter.guard.state import load
from carter.identity.errors import E_HUMAN_TERMINAL
from carter.install.mcp import config_target
from carter.install.paths import guard_state_path, isolation_path
from guard.helpers import tree_hash, verbose

ONE = "read-edit-denies"


def guard(*args: str) -> Result:
    ui.configure(verbose=False)
    return CliRunner().invoke(main, ["guard", *verbose(args)], catch_exceptions=False)


def install(stack) -> None:
    stack.fake()
    assert guard("install", "--yes").exit_code == 0


class TestNeedsATerminal:
    def test_a_scoped_remove_without_a_terminal_is_refused_and_writes_nothing(
        self, stack, human_tty
    ) -> None:
        human_tty(False)
        install(stack)
        before = tree_hash(stack.home)
        res = guard("remove", "--only", ONE)
        assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
        assert tree_hash(stack.home) == before

    def test_it_works_at_a_terminal(self, stack, human_tty) -> None:
        human_tty(True)
        install(stack)
        assert guard("remove", "--only", ONE).exit_code == 0

    def test_the_full_remove_and_a_dry_run_need_none(self, stack, human_tty) -> None:
        human_tty(False)
        install(stack)
        assert guard("remove", "--dry-run", "--only", ONE).exit_code == 0
        stack.fake()
        assert guard("remove").exit_code == 0

    def test_an_agent_shell_is_still_refused_with_a_terminal(
        self, stack, human_tty, monkeypatch
    ) -> None:
        human_tty(True)
        install(stack)
        monkeypatch.setenv("AGENT", "x")
        assert guard("remove", "--only", ONE).exit_code == 1


@pytest.mark.usefixtures("at_terminal")
class TestAFailureLeavesNothingHalfDone:
    def snapshot(self) -> tuple[bytes, bytes, bytes]:
        return (
            guard_state_path(None).read_bytes(),
            config_target(None).read_bytes(),
            isolation_path(None).read_bytes(),
        )

    def test_a_failing_plugin_step_restores_state_config_and_isolation(
        self, stack, monkeypatch
    ) -> None:
        install(stack)
        before = self.snapshot()
        stack.fake(before=json.dumps({}), after=json.dumps({}))
        real = plugin.install
        calls = {"n": 0}

        def broken(*args, **kwargs):  # type: ignore[no-untyped-def]
            calls["n"] += 1
            if calls["n"] == 1:
                raise plugin.PluginInstallError("forced")
            return real(*args, **kwargs)

        monkeypatch.setattr(plugin, "install", broken)
        res = CliRunner().invoke(main, ["guard", "remove", "--only", ONE])
        assert res.exit_code != 0 and calls["n"] >= 1
        assert self.snapshot() == before  # still accepted everywhere
        assert load(guard_state_path(None)).consents[ONE]["decision"] == "accepted"

    def test_a_failure_after_the_isolation_file_was_written_rewrites_it_from_the_old_state(
        self, stack, monkeypatch
    ) -> None:
        install(stack)
        before = self.snapshot()
        from carter.guard import engine

        def broken(*_a: object, **_k: object) -> None:
            raise engine.GuardAbort("forced after the re-render")

        stack.fake()
        monkeypatch.setattr(engine, "save", broken)
        res = CliRunner().invoke(main, ["guard", "remove", "--only", ONE])
        assert res.exit_code != 0
        assert self.snapshot() == before  # isolation.json lists no declined group again
