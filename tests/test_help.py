"""Every ``--help`` is short and free of internal notes (D68 b)."""

from __future__ import annotations

import re

import click
import pytest
from click.testing import CliRunner

from carter.cli import main

INTERNAL = re.compile(
    r"\b(RFC|App(?:endix)?\s[A-C]\b|D\d\d|slice|plan \d|step \d|spike|freeze)", re.I
)


def commands(cmd: click.Command, path: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    found = [path]
    if isinstance(cmd, click.Group):
        for name, sub in sorted(cmd.commands.items()):
            found += commands(sub, (*path, name))
    return found


ALL = commands(main)


def resolve(path: tuple[str, ...]) -> click.Command:
    cmd: click.Command = main
    for name in path:
        assert isinstance(cmd, click.Group)
        cmd = cmd.commands[name]
    return cmd


@pytest.mark.parametrize("path", ALL, ids=lambda p: " ".join(p) or "carter")
def test_the_summary_is_one_short_line(path: tuple[str, ...]) -> None:
    cmd = resolve(path)
    summary = (cmd.help or "").strip().splitlines()[0] if cmd.help else ""
    assert summary and len(summary) <= 62, (path, summary)


@pytest.mark.parametrize("path", ALL, ids=lambda p: " ".join(p) or "carter")
def test_every_option_has_one_short_line_and_no_internal_notes(path: tuple[str, ...]) -> None:
    cmd = resolve(path)
    for param in cmd.params:
        if isinstance(param, click.Option) and not param.hidden:
            help_text = param.help or ""
            assert help_text, (path, param.name)
            assert len(help_text) <= 70, (path, param.name, help_text)
            assert not INTERNAL.search(help_text), (path, param.name, help_text)
    assert not INTERNAL.search(cmd.help or ""), (path, cmd.help)


def test_guard_remove_help_lists_broker_and_plugin() -> None:
    out = CliRunner().invoke(main, ["guard", "remove", "--help"]).output
    assert "broker" in out and "plugin" in out


def test_the_removed_prompts_and_flags_are_gone_from_every_help() -> None:
    for path in ALL:
        out = CliRunner().invoke(main, [*path, "--help"]).output
        assert "--allow-no-passphrase" not in out, path
        assert "confirm" not in out.lower(), path


def test_the_global_switches_are_accepted_but_not_advertised() -> None:
    out = CliRunner().invoke(main, ["--help"]).output
    assert "--no-color" not in out  # cheap and hidden: NO_COLOR and a pipe already do it
    done = CliRunner().invoke(main, ["--no-color", "-v", "gate", "check", "git status"])
    assert done.exit_code == 0 and "\x1b" not in done.output
