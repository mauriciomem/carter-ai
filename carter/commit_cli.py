"""``carter commit``: ``git commit`` as the LLM identity (RFC-0007 §4.3; plan 005 step 22).

A thin wrapper over ``carter.identity.commit``: every argument goes to ``git commit`` untouched
(the command parses nothing itself, so ``-m``, ``--`` and empty strings arrive as typed) except the
flags that skip a hook, change the signature or pick an identity, which are refused. At T2 with the
key loaded the LLM signs; with it locked, an agent shell is refused and a person at a terminal is
offered the unlock once. Below T2 the commit is unsigned with the trailer. Exit codes are git's.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from carter import terminal
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


def _offer_unlock() -> bool:
    """Ask once whether to unlock now; any refusal or failure means "no" (the fallback follows)."""
    from carter import identity_cli

    if not click.confirm("The LLM signing key is locked. Unlock now?", default=False, err=True):
        return False
    try:
        return identity_cli.perform_unlock(None, False, False) == 0
    except (IdentityError, click.ClickException) as exc:
        click.echo(f"Not unlocked: {getattr(exc, 'message', None) or exc}", err=True)
        return False


@click.command("commit", cls=_PassThrough, context_settings={"ignore_unknown_options": True})
def commit_cmd() -> None:
    """Commit the staged changes as the LLM identity: `git commit` with Carter's identity.

    Usage: carter commit [GIT COMMIT ARGUMENTS...]

    At T2 the LLM signs (committer and signer), you stay the author; the Co-authored-by trailer
    is always added once. With the key locked in your own terminal you are asked once whether to
    unlock; on no it commits unsigned with the trailer. In an agent shell a locked key is refused
    and the changes stay staged. T1 commits unsigned with the trailer, T0 with Assisted-by.

    Refused: --no-verify, -n, --no-gpg-sign, -S<key>, --gpg-sign=<key>, -s, --signoff, --author
    (use plain `git commit` for those). A bare -S is dropped; -a and --reset-author pass. Your own
    signing key is never used. Exit codes are git's."""
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
                human_tty=not agent and terminal.stdin_is_tty(),
                offer_unlock=_offer_unlock,
            )
        except core.CommitRefused as exc:
            raise click.UsageError(str(exc)) from exc
        for note in plan.notes:
            click.echo(f"Note: {note}", err=True)
        for warning in plan.warnings:
            click.echo(f"Warning: {warning}", err=True)
        sys.stdout.flush()
        return core.run_git(plan)

    guarded(run)
