"""Every line the guard commands print fits the output rule: at most 80 columns, most under 60.

The commands run under the sandbox home (a long temp path); the report replaces it with a real
home's length, because ``~`` paths are what a person sees. Each scenario is a way the output can be
at its longest: the question, a full install with ``-v``, status, a dry run, a remove, and the
install over a symlinked ``~/.gitconfig``. A line over ``ui.TARGET`` has to be listed below."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from carter import ui
from carter.cli import main
from guard.helpers import decline

HOME_AS_SEEN = "/home/dev"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TABLE_MAX = 74  # a row of the install question: 4 + 16 (id) + 2 + the short text


def over_target(line: str) -> bool:
    """A line over the target that is not a row of the install question's table."""
    return len(line) > ui.TARGET and not (line.startswith("    ") and len(line) <= TABLE_MAX)


def run(*args: str, input: str | None = None) -> list[str]:
    ui.configure(verbose=False)  # a -v of an earlier run in this test must not leak into this one
    res = CliRunner().invoke(main, list(args), input=input, catch_exceptions=False)
    home = os.environ["HOME"]
    text = ANSI.sub("", res.output).replace(home, HOME_AS_SEEN)
    return text.splitlines()


def check(lines: list[str], *, target: bool = False) -> None:
    """The hard max for every line; the 60-column target for what a normal run prints (``-v`` and
    the dry run are the detail a person asked for: they only have to fit)."""
    assert lines, "the scenario printed nothing"
    too_long = [ln for ln in lines if len(ln) > ui.MAX]
    assert not too_long, "\n".join(too_long)
    if target:
        long = [ln for ln in lines if over_target(ln)]
        assert not long, "over the 60-column target (shorten, or list it):\n" + "\n".join(long)


@pytest.fixture
def at_a_terminal(stack, human_tty) -> None:
    human_tty(True)
    stack.fake()


def test_the_install_question_is_a_short_table(at_a_terminal) -> None:
    lines = run("guard", "install", input="n\n")
    check(lines, target=True)
    assert "Install? [Y/n]: " in lines[-1] or any("Install?" in ln for ln in lines)
    assert sum(ln.startswith("    ") for ln in lines) <= 6  # one row per group, at most five


def test_the_question_for_a_revision_names_what_is_new(at_a_terminal) -> None:
    decline("hooks")
    check(run("guard", "install", input="n\n"), target=True)


def test_a_full_install_with_v(at_a_terminal) -> None:
    check(run("guard", "install", "-v", "--yes"))


def test_status_normal_and_with_v(at_a_terminal) -> None:
    run("guard", "install", "--yes")
    check(run("guard", "status"), target=True)
    check(run("guard", "status", "-v"))


def test_a_dry_run_with_v(at_a_terminal) -> None:
    check(run("guard", "install", "--dry-run", "-v"))


def test_remove_with_v(at_a_terminal) -> None:
    run("guard", "install", "--yes")
    check(run("guard", "remove", "-v"))


def test_install_over_a_symlinked_gitconfig(at_a_terminal, tmp_path: Path) -> None:
    config = Path(os.environ["GIT_CONFIG_GLOBAL"])
    real = tmp_path / "dotfiles" / "gitconfig"
    real.parent.mkdir()
    real.write_text(config.read_text())
    config.unlink()
    config.symlink_to(real)
    check(run("guard", "install", "-v", "--yes"))
    check(run("guard", "status"), target=True)


def test_install_and_uninstall_reports(at_a_terminal) -> None:
    check(run("install", "--yes"), target=True)
    check(run("install", "--yes", "-v"))
    check(run("check", "--host"))
    check(run("check", "--host", "-v"))
    check(run("uninstall", "--yes"))
    check(run("uninstall", "--yes", "-v"))


def test_a_workspace_check_and_update(at_a_terminal, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    check(run("init", str(ws), "--no-git-state"))
    check(run("update", str(ws)), target=True)
    check(run("check", str(ws), "--no-harness"), target=True)
    check(run("check", str(ws), "--no-harness", "-v"))


def test_access_and_identity_show(at_a_terminal) -> None:
    check(run("access"), target=True)
    check(run("access", "-v"))
    check(run("identity", "show"))
    check(run("identity", "show", "-v"))
    check(run("github-token", "check"))
