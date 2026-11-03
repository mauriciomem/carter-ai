"""``carter push`` and ``carter pr``: the click layer over ``carter.aplus`` (RFC-0007 C.6.6).

Both run only in the human's own terminal (RFC-0007 App B §1): they refuse in an agent shell and
without a TTY, *before* any git or gh call. An OpenCode ``!`` shell has no TTY either (spike 2),
so it is refused as well; the text always says "run it in your own terminal".
"""

from __future__ import annotations

from pathlib import Path

import click

from carter.aplus import pr as pr_flow
from carter.aplus import push as push_flow
from carter.cliguard import guarded
from carter.identity.errors import E_APLUS_ARGS, IdentityError
from carter.terminal import require_human_terminal


def _ask(text: str) -> str:
    try:
        return str(click.prompt(text.rstrip(), default="", show_default=False, prompt_suffix=" "))
    except click.Abort as exc:
        raise EOFError from exc


def io() -> push_flow.Io:
    return push_flow.Io(
        echo=click.echo, ask=_ask, red=lambda text: click.style(text, fg="red", bold=True)
    )


def no_arguments(command: str, extra: tuple[str, ...]) -> None:
    if extra:  # names only: an argument could be a mistyped secret
        raise IdentityError(
            E_APLUS_ARGS, detail=f"{command} takes no arguments ({len(extra)} given)"
        )


@click.command("push")
@click.argument("extra", nargs=-1)
@click.option("--dry-run", is_flag=True, help="Show what would be pushed and asked; push nothing.")
@click.option("--set-upstream", "-u", is_flag=True, help="Set origin/<branch> as the upstream.")
def push(extra: tuple[str, ...], dry_run: bool, set_upstream: bool) -> None:
    """Push the current branch to origin after showing and checking it (own terminal only).

    There is no way to force, push tags, name another remote or branch, or pass git options.
    Commits by the LLM must carry a valid LLM signature. On the default branch you type its
    name to confirm."""

    def run() -> int:
        require_human_terminal("carter push")
        no_arguments("carter push", extra)
        opts = push_flow.Options(dry_run=dry_run, set_upstream=set_upstream)
        return push_flow.run_push(Path.cwd(), opts, io())

    guarded(run)


@click.command("pr")
@click.argument("extra", nargs=-1)
def pr(extra: tuple[str, ...]) -> None:
    """Open a pull request from the agent's handoff file (own terminal only).

    Reads only .carter/state/handoff/<branch>.md for the current branch, scans it for secrets,
    shows the title, target, base and the start of the body, and asks before it runs gh. The
    file is deleted once the pull request exists."""

    def run() -> int:
        require_human_terminal("carter pr")
        no_arguments("carter pr", extra)
        return pr_flow.run_pr(Path.cwd(), io())

    guarded(run)
