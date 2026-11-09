"""``carter commit``: ``git commit`` as the LLM identity.

A thin wrapper over ``carter.identity.commit``: every argument goes to ``git commit`` untouched
(the command parses nothing itself, so ``-m``, ``--`` and empty strings arrive as typed) except the
flags that skip a hook, change the signature or pick an identity, which are refused. At T2 with the
key loaded the LLM signs. With it locked, an agent shell is refused; a person at a terminal gets
``✗ key locked → carter identity unlock`` and an unsigned commit (nothing is asked). Below T2 the
commit is unsigned with the trailer. Exit codes are git's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from carter import terminal, ui
from carter.cliguard import guarded
from carter.identity import commit as core
from carter.identity.config import ConfigError, default_path, load_identity
from carter.identity.errors import E_CONFIG, IdentityError


class _PassThrough(click.Command):
    """Keeps the raw argument list: click would drop a ``--`` and guess at ``-m``."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        if args in (["--help"], ["-h"]):
            return super().parse_args(ctx, ["--help"])
        ctx.meta["carter.git_args"] = list(args)
        ctx.args = []
        return []


@click.command("commit", cls=_PassThrough, context_settings={"ignore_unknown_options": True})
def commit_cmd() -> None:
    """Commit as the LLM identity (git commit arguments).

    Refuses --no-verify, --no-gpg-sign, --gpg-sign=<key>, --signoff and --author."""
    args = click.get_current_context().meta.get("carter.git_args", [])

    def run() -> int:
        try:
            cfg = load_identity(default_path())
        except ConfigError as exc:
            raise IdentityError(E_CONFIG, detail=exc.detail) from exc
        agent = terminal.is_agent_shell()
        try:
            plan = core.plan_commit(
                args,
                cfg=cfg,
                env=os.environ,
                cwd=os.getcwd(),
                home=Path.home(),
                agent=agent,
            )
        except core.CommitRefused as exc:
            raise click.UsageError(str(exc)) from exc
        for note in plan.notes:
            ui.detail(note)
        if plan.key_locked:
            ui.fail("key locked", "carter identity unlock", inline=True)
        for warning in plan.warnings:
            ui.warn(warning)
        sys.stdout.flush()
        return core.run_git(plan)

    guarded(run)
