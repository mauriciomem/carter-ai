"""``carter github-token set | check`` (RFC-0007 App C.7). A thin click layer over ``ghtoken``.

``set`` reads the token from stdin (a hidden prompt on a terminal), never from argv or the
environment, and needs a human terminal on stderr. ``check`` refuses in agent shells but needs
no TTY. Errors print as ``Error: <E-CODE>: <message>`` and exit 1.
"""

from __future__ import annotations

import getpass
from pathlib import Path

import click

from carter import ghtoken, ui
from carter.cliguard import guarded as _guarded
from carter.cliguard import verbose_option
from carter.terminal import require_human_terminal, stdin_is_tty

_BASE_DIR = click.option(
    "--base-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    hidden=True,
    help="Override the install base directory (for testing).",
)
_MAX_READ = 1024  # a token is under 300 characters; refuse to slurp more


@click.group("github-token")
def github_token() -> None:
    """Store and check the read-only GitHub token."""


@github_token.command("set")
@click.argument("extra", nargs=-1)
@_BASE_DIR
def set_cmd(extra: tuple[str, ...], base_dir: Path | None) -> None:
    """Store a read-only token (stdin or a hidden prompt)."""

    if extra:  # never echo it: click would print the extra argument, i.e. the token
        raise click.UsageError(
            "`carter github-token set` takes no arguments: the token is read from stdin. "
            "If that was a real token, it is in your shell history; revoke it."
        )

    def run() -> int:
        require_human_terminal("carter github-token set", streams=("stderr",))
        if stdin_is_tty():
            raw = getpass.getpass("GitHub fine-grained token (input hidden): ")
        else:
            raw = click.get_text_stream("stdin").read(_MAX_READ)
        stored = ghtoken.store_token(raw, base_dir)
        ui.ok("token stored", f"{stored.path} (0600)")
        if stored.note:
            ui.detail(stored.note)
        ui.info("→ next: carter github-token check")
        return 0

    _guarded(run)


@github_token.command("check")
@_BASE_DIR
@verbose_option
def check_cmd(base_dir: Path | None) -> None:
    """Check the stored token (file, type, expiry, read-only)."""

    def run() -> int:
        require_human_terminal("carter github-token check", need_tty=False)
        items = ghtoken.check_token(base_dir)
        return ui.items(items, "token")

    _guarded(run)
