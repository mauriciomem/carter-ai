"""The CLI surface is locked: 14 top-level commands, 24 leaf commands, 61 visible long flags.

Growing it is a user decision, not a side effect of a feature. Commands are
resolved through ``list_commands``/``get_command`` so the test keeps working once groups load
their subcommands lazily. Counting: the long flags of every leaf command, ``--verbose`` once
per leaf that has it, hidden options and Click's own ``--help`` excluded.
"""

from __future__ import annotations

import click

from carter.cli import main

TOP_LEVEL, LEAVES, LONG_FLAGS = 14, 24, 61


def _leaves(group: click.Group, ctx: click.Context) -> list[click.Command]:
    found: list[click.Command] = []
    for name in group.list_commands(ctx):
        cmd = group.get_command(ctx, name)
        assert cmd is not None, name
        if isinstance(cmd, click.Group):
            found += _leaves(cmd, click.Context(cmd, parent=ctx))
        else:
            found.append(cmd)
    return found


def _long_flags(cmd: click.Command) -> list[str]:
    return [
        flag
        for param in cmd.params
        if isinstance(param, click.Option) and not param.hidden
        for flag in (*param.opts, *param.secondary_opts)
        if flag.startswith("--")
    ]


def test_the_cli_surface_is_locked() -> None:
    ctx = click.Context(main)
    leaves = _leaves(main, ctx)
    measured = (
        len(main.list_commands(ctx)),
        len(leaves),
        sum(len(_long_flags(cmd)) for cmd in leaves),
    )
    assert measured == (TOP_LEVEL, LEAVES, LONG_FLAGS), (
        f"top-level/leaf/long-flag counts are {measured}, expected "
        f"{(TOP_LEVEL, LEAVES, LONG_FLAGS)}: new surface needs a user decision "
        "(change these numbers only once the user has approved the new command or flag)"
    )
