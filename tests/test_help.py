"""Every ``--help`` is short and free of internal notes ()."""

from __future__ import annotations

import re
import subprocess
import sys

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
        ctx = click.Context(cmd)
        for name in cmd.list_commands(ctx):
            sub = cmd.get_command(ctx, name)
            assert sub is not None, name
            found += commands(sub, (*path, name))
    return found


ALL = commands(main)


def resolve(path: tuple[str, ...]) -> click.Command:
    cmd: click.Command = main
    for name in path:
        assert isinstance(cmd, click.Group)
        found = cmd.get_command(click.Context(cmd), name)
        assert found is not None, name
        cmd = found
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


def test_the_lazy_table_cannot_drift_from_the_commands() -> None:
    """The root ``--help`` lists the table's text without importing: it must be the real one."""
    ctx = click.Context(main)
    for name, (_target, summary) in main.lazy.items():
        real = main.get_command(ctx, name)
        assert real is not None and real.name == name and not real.hidden, name
        stub = click.Command(name, help=summary)
        assert stub.get_short_help_str(1000) == real.get_short_help_str(1000), name
        assert (real.help or "").splitlines()[0] == summary, name


def test_the_profile_choices_are_the_configured_profiles() -> None:
    from carter.cli import _PROFILE_NAMES
    from carter.config import PROFILES

    assert tuple(sorted(PROFILES)) == _PROFILE_NAMES


def test_root_help_and_tab_completion_list_every_command_without_importing_them() -> None:
    """Run in a child process: the 7 lazy modules must stay unimported while listing."""
    code = (
        "import sys, click\n"
        "from carter.cli import main\n"
        "ctx = click.Context(main)\n"
        "text = main.get_help(ctx)\n"
        "names = [i.value for i in main.shell_complete(ctx, '')]\n"
        "assert names == main.list_commands(ctx) and len(names) == 14, names\n"
        "assert all(n in text for n in names)\n"
        "assert [i.value for i in main.shell_complete(ctx, 'gu')] == ['guard']\n"
        "loaded = [m for m in sys.modules if m.endswith(('guard.cli', 'ci_cli', 'identity_cli'))]\n"
        "assert not loaded, loaded\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
