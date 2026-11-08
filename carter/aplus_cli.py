"""``carter push`` and ``carter pr``: the click layer over ``carter.aplus`` (RFC-0007 C.6.6).

Both are for the human (RFC-0007 App B §1, D68 g): they refuse in an agent shell *before* any git
or gh call, and need no TTY. OpenCode's ``!`` shell counts as the human's when the plugin tagged it
(``CARTER_HUMAN_SHELL`` and no agent signal, AD1). They ask nothing.
"""

from __future__ import annotations

from pathlib import Path

import click

from carter.aplus import pr as pr_flow
from carter.aplus import push as push_flow
from carter.cliguard import guarded, verbose_option
from carter.identity.errors import E_APLUS_ARGS, IdentityError
from carter.terminal import require_human_terminal


def no_arguments(command: str, extra: tuple[str, ...]) -> None:
    if extra:  # names only: an argument could be a mistyped secret
        raise IdentityError(
            E_APLUS_ARGS, detail=f"{command} takes no arguments ({len(extra)} given)"
        )


@click.command("push")
@click.argument("extra", nargs=-1)
@click.option("--dry-run", is_flag=True, help="Check and show; push nothing.")
@click.option("--set-upstream", "-u", is_flag=True, help="Set origin/<branch> as upstream.")
@verbose_option
def push(extra: tuple[str, ...], dry_run: bool, set_upstream: bool) -> None:
    """Push the current branch to origin (never forced)."""

    def run() -> int:
        require_human_terminal("carter push", need_tty=False)
        no_arguments("carter push", extra)
        opts = push_flow.Options(dry_run=dry_run, set_upstream=set_upstream)
        return push_flow.run_push(Path.cwd(), opts)

    guarded(run)


@click.command("pr")
@click.argument("extra", nargs=-1)
@verbose_option
def pr(extra: tuple[str, ...]) -> None:
    """Open a pull request from the agent's handoff file."""

    def run() -> int:
        require_human_terminal("carter pr", need_tty=False)
        no_arguments("carter pr", extra)
        return pr_flow.run_pr(Path.cwd())

    guarded(run)
