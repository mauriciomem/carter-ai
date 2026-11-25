"""Every line the commands print fits the output rule: at most 80 columns, most under 60.

The commands run under the sandbox home (a long temp path); the report replaces it with a real
home's length, because ``~`` paths are what a person sees. Each scenario is a way the output can be
at its longest: the question, a full install with ``-v``, status, a dry run, a remove, the install
over a symlinked ``~/.gitconfig``, the ``--help`` page of every command, and the error paths of
``init``, ``update`` and ``check``. Every run asserts its exit code, so a scenario that fails early
cannot pass. ``carter push`` has its own scenarios in ``tests/aplus/test_push.py``."""

from __future__ import annotations

import os
import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from carter import ui
from carter.cli import main
from guard.helpers import NO_TO_ALL, decline

HOME_AS_SEEN = "/home/dev"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
TABLE_MAX = 74  # a row of the install question: 4 + 16 (id) + 2 + the short text (<= 50)


def run(*args: str, input: str | None = None, code: int = 0) -> list[str]:
    ui.configure(verbose=False)  # a -v of an earlier run in this test must not leak into this one
    res = CliRunner().invoke(main, list(args), input=input, catch_exceptions=False)
    assert res.exit_code == code, f"{args}: exit {res.exit_code}, wanted {code}\n{res.output}"
    return ANSI.sub("", res.output).replace(os.environ["HOME"], HOME_AS_SEEN).splitlines()


def question_rows(lines: list[str]) -> list[str]:
    """The rows of the install question's table: after its heading, up to ``Install?``."""
    start = next(i for i, ln in enumerate(lines) if "Guards to install" in ln)
    end = next(i for i, ln in enumerate(lines) if ln.startswith("Install?"))
    return lines[start + 1 : end]


def check(lines: list[str], *, target: bool = False, table: tuple[str, ...] = ()) -> None:
    """The hard max for every line; the 60-column target for what a normal run prints (``-v``, the
    dry run and ``--help`` are the detail a person asked for: they only have to fit). The one
    table that may pass the target is named by the caller: its rows pass ``TABLE_MAX``."""
    assert lines, "the scenario printed nothing"
    too_long = [ln for ln in lines if len(ln) > ui.MAX]
    assert not too_long, "\n".join(too_long)
    if target:
        long = [ln for ln in lines if len(ln) > ui.TARGET and ln not in table]
        assert not long, "over the 60-column target (shorten, or name the table):\n" + "\n".join(
            long
        )
        assert all(len(ln) <= TABLE_MAX for ln in table)


@pytest.fixture
def at_a_terminal(stack, human_tty) -> None:
    human_tty(True)
    stack.fake()


def test_the_install_question_is_a_short_table(at_a_terminal) -> None:
    lines = run("guard", "install", input=NO_TO_ALL)
    rows = question_rows(lines)
    check(lines, target=True, table=tuple(rows))
    assert any("(details: carter guard --help)" in ln for ln in lines)  # where the rest is
    assert any(ln.startswith("Install? [Y/n]: ") for ln in lines)
    assert 1 <= len(rows) <= 5 and all(ln.startswith("    ") for ln in rows)
    hooks = next(ln for ln in rows if ln.strip().startswith("hooks"))
    assert "all repos" in hooks  # what the group covers is in the row the user consents to


def test_the_question_for_a_revision_names_what_is_new(at_a_terminal) -> None:
    decline("hooks")
    lines = run("guard", "install", input=NO_TO_ALL)
    check(lines, target=True, table=tuple(question_rows(lines)))


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
    lines = run("install", "--yes")
    check(lines, target=True, table=tuple(ln for ln in lines if ln.strip().startswith("guards ")))
    check(run("install", "--yes", "-v"))
    check(run("check", "--host"), code=None) if False else None
    check(run("uninstall", "--yes"))
    check(run("uninstall", "--yes", "-v"))


def test_a_workspace_check_and_update(at_a_terminal, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    check(run("init", str(ws), "--no-git-state"))
    check(run("update", str(ws)), target=True)
    check(run("check", str(ws), "--no-harness"), target=True)
    check(run("check", str(ws), "--no-harness", "-v"))


def test_the_error_paths_of_init_update_and_check(at_a_terminal, tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    run("init", str(ws), "--no-git-state")
    config = ws / ".carter" / "carter.yaml"
    original = config.read_text()
    config.write_text(original.replace("- maestro", "- nonexistent", 1))
    commands = (("update", str(ws)), ("check", str(ws), "--no-harness"))
    for command in commands:
        lines = run(*command, code=1)
        check(lines, target=True)
        assert any("nonexistent" in ln for ln in lines)
    config.write_text("agents: [unclosed\n")
    for command in commands:
        check(run(*command, code=1))
    other = tmp_path / "y"
    other.mkdir()
    check(run("init", str(other), "--agent-suffix", "Bad Suffix", code=2))


def test_the_host_check(at_a_terminal) -> None:
    run("guard", "install", "--yes")
    check(run("check", "--host"), target=True)
    check(run("check", "--host", "-v"))


def test_access_and_identity_show(at_a_terminal) -> None:
    check(run("access"), target=True)
    check(run("access", "-v"))
    check(run("identity", "show"))
    check(run("identity", "show", "-v"))
    check(run("github-token", "check", code=1))


def _help_pages() -> list[tuple[str, ...]]:
    pages: list[tuple[str, ...]] = []

    def walk(command: click.Command, path: tuple[str, ...], ctx: click.Context) -> None:
        pages.append(path)
        if isinstance(command, click.Group):
            for name in command.list_commands(ctx):
                sub = command.get_command(ctx, name)
                assert sub is not None
                walk(sub, (*path, name), click.Context(sub, parent=ctx))

    walk(main, (), click.Context(main))
    return pages


AGENT_TOOL = ("ops",)  # `carter ops` is the agent's own tool; its help is written for the model


@pytest.mark.parametrize(
    "path",
    [p for p in _help_pages() if p[:1] != AGENT_TOOL],
    ids=lambda p: " ".join(p) or "carter",
)
def test_every_help_page_fits_the_line(path: tuple[str, ...]) -> None:
    check(run(*path, "--help"))
