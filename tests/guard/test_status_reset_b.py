# ruff: noqa: E501
"""``carter guard status --reset-b``: human terminal only; nothing agent-callable."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from carter.broker import counter
from carter.cli import main
from carter.identity.errors import E_HUMAN_TERMINAL


def run(*args: str, base: Path):
    return CliRunner().invoke(main, ["guard", "status", "--base-dir", str(base), *args])


@pytest.fixture
def stopped(tmp_path: Path) -> Path:
    for _ in range(3):
        counter.add("ses_root", tmp_path / "carter")
    assert counter.stopped("ses_root", tmp_path / "carter")
    return tmp_path


def test_a_human_at_a_terminal_clears_every_family(stopped: Path, human_tty) -> None:
    human_tty(True)
    res = run("--reset-b", base=stopped)
    assert res.exit_code == 0 and "cleared (1 session family)" in res.output
    assert not counter.stopped("ses_root", stopped / "carter")


def test_an_agent_shell_is_refused_and_nothing_changes(
    stopped: Path, human_tty, monkeypatch: pytest.MonkeyPatch
) -> None:
    human_tty(True)
    monkeypatch.setenv("AGENT", "1")
    res = run("--reset-b", base=stopped)
    assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
    assert counter.stopped("ses_root", stopped / "carter")


def test_no_terminal_is_refused(stopped: Path, human_tty) -> None:
    human_tty(False)
    res = run("--reset-b", base=stopped)
    assert res.exit_code == 1 and E_HUMAN_TERMINAL in res.output
    assert counter.stopped("ses_root", stopped / "carter")


def test_a_corrupt_counter_is_replaced_by_the_reset(tmp_path: Path, human_tty) -> None:
    human_tty(True)
    path = counter.path(tmp_path / "carter")
    path.parent.mkdir(parents=True)
    path.write_text("{nope")
    assert run("--reset-b", base=tmp_path).exit_code == 0
    assert counter.count("x", tmp_path / "carter") == 0


def test_plain_status_does_not_reset(stopped: Path) -> None:
    run(base=stopped)
    assert counter.stopped("ses_root", stopped / "carter")
