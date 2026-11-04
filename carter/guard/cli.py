"""``carter guard install | status | remove`` (RFC-0007 App B §1, freeze F7-F9).

A thin click layer over ``engine`` and ``status``. ``install`` and ``remove`` refuse in
agent shells (AD1). A non-TTY ``install`` without ``--yes`` is skipped with a notice (exit 0);
``remove`` needs a TTY or ``--yes``. ``--dry-run`` and ``--print-policies`` write nothing,
so they need no terminal. ``status`` is read-only and allowed anywhere. Errors print as
``Error: <E-CODE>: <message>`` and exit 1.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carter import terminal
from carter.guard import consent, engine, status


def _only(_ctx: click.Context, _param: click.Parameter, value: str | None) -> list[str] | None:
    try:
        return consent.parse_only(value)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--only") from exc


def _only_remove(
    _ctx: click.Context, _param: click.Parameter, value: str | None
) -> list[str] | None:
    try:
        return consent.parse_only(value, allow_plugin=True)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--only") from exc


def _guarded(fn: Callable[[], int]) -> None:
    """Run ``fn`` and turn the expected failures into ``Error: ...`` + exit 1."""
    try:
        code = fn()
    except Exception as exc:
        text = engine.format_error(exc)
        if text is None:
            raise
        raise click.ClickException(text) from exc
    if code:
        raise SystemExit(code)


def _common(f: Callable[..., Any], *, remove: bool = False) -> Callable[..., Any]:
    f = click.option("--yes", "-y", "assume_yes", is_flag=True, help="Accept without asking.")(f)
    f = click.option("--dry-run", is_flag=True, help="Show what would change; write nothing.")(f)
    f = click.option(
        "--only",
        callback=_only_remove if remove else _only,
        default=None,
        help="Comma-separated consent groups: "
        + ", ".join(consent.group_names())
        + (", plugin (the OpenCode plugin only; keeps the other guards)." if remove else "."),
    )(f)
    return click.option(
        "--base-dir",
        type=click.Path(file_okay=False, path_type=Path),
        default=None,
        hidden=True,
        help="Override the install base directory (for testing).",
    )(f)


@click.group()
def guard() -> None:
    """Install, inspect and remove Carter's policy guards (human terminal only)."""


@guard.command("install")
@_common
@click.option("--print-policies", is_flag=True, help="Print the policies block and exit.")
def install_cmd(
    only: list[str] | None,
    dry_run: bool,
    assume_yes: bool,
    base_dir: Path | None,
    print_policies: bool,
) -> None:
    """Write consented policies and per-agent denies into the OpenCode config.

    Every group is shown with a one-line effect and needs your yes. Without a terminal and
    without --yes nothing is installed. Policies are written atomically, verified with
    `opencode debug config` and rolled back if a provider or statement is lost."""

    def run() -> int:
        if not (dry_run or print_policies):
            terminal.require_human_terminal("guard install", need_tty=False)
        return engine.install(
            base_dir=base_dir,
            only=only,
            assume_yes=assume_yes,
            interactive=terminal.stdin_is_tty(),
            dry_run=dry_run,
            print_policies=print_policies,
            echo=click.echo,
            confirm=click.confirm,
        )

    _guarded(run)


@guard.command("remove")
@lambda f: _common(f, remove=True)
def remove_cmd(
    only: list[str] | None, dry_run: bool, assume_yes: bool, base_dir: Path | None
) -> None:
    """Remove what Carter installed, only where it is unchanged since (human terminal only)."""

    def run() -> int:
        terminal.require_human_terminal(
            "guard remove", need_tty=not (assume_yes or dry_run), streams=("stdin",)
        )
        return engine.remove(
            base_dir=base_dir,
            only=only,
            assume_yes=assume_yes,
            interactive=terminal.stdin_is_tty(),
            dry_run=dry_run,
            echo=click.echo,
            confirm=click.confirm,
        )

    _guarded(run)


@guard.command("status")
@click.option(
    "--base-dir", type=click.Path(file_okay=False, path_type=Path), default=None, hidden=True
)
def status_cmd(base_dir: Path | None) -> None:
    """Show consents, loaded policies and file drift (read-only; works anywhere)."""

    def run() -> int:
        status.report(base_dir, click.echo)
        return 0

    _guarded(run)
