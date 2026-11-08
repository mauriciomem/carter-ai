"""``carter guard install | status | remove`` (RFC-0007 App B §1, freeze F7-F9, D68 h).

A thin click layer over ``engine`` and ``status``. ``install`` and ``remove`` refuse in agent
shells (AD1). ``install`` asks one question (``--yes`` skips it) and, without a terminal and
without ``--yes``, is skipped with a notice (exit 0); ``remove`` asks nothing. ``--dry-run``
writes nothing. ``status`` is read-only and allowed anywhere. A normal run
ends in one line; ``-v`` shows the rest.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from carter import terminal, ui
from carter.broker import counter
from carter.cliguard import guarded, verbose_option
from carter.guard import consent, engine, report, status
from carter.install.paths import run_dir


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
    """Run ``fn`` and print the expected failures as ``✗ cause`` / ``→ fix``, exit 1."""
    guarded(fn)


def _common(f: Callable[..., Any], *, remove: bool = False) -> Callable[..., Any]:
    f = click.option("--yes", "-y", "assume_yes", is_flag=True, hidden=remove, help="Don't ask.")(f)
    f = click.option("--dry-run", is_flag=True, help="Show what would change; write nothing.")(f)
    f = click.option(
        "--only",
        callback=_only_remove if remove else _only,
        default=None,
        metavar="GROUPS",
        help="Only these groups, comma-separated"
        + (" (also plugin, broker)." if remove else " (g2, hooks, ...)."),
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
    """Install, inspect and remove Carter's guards."""


@guard.command("install")
@_common
@verbose_option
def install_cmd(
    only: list[str] | None, dry_run: bool, assume_yes: bool, base_dir: Path | None
) -> None:
    """Install the guards (one question)."""

    def run() -> int:
        if not dry_run:
            terminal.require_human_terminal("guard install", need_tty=False)
        code = engine.install(
            base_dir=base_dir,
            only=only,
            assume_yes=assume_yes,
            interactive=terminal.stdin_is_tty(),
            dry_run=dry_run,
            echo=click.echo if dry_run else report.say,
            confirm=click.confirm,
        )
        if code == 0 and not dry_run:
            report.installed(base_dir)
        return code

    _guarded(run)


@guard.command("remove")
@lambda f: _common(f, remove=True)
@verbose_option
def remove_cmd(
    only: list[str] | None, dry_run: bool, assume_yes: bool, base_dir: Path | None
) -> None:
    """Remove the guards Carter installed, where unchanged since."""
    del assume_yes  # accepted and ignored: nothing is asked any more (D68 h)

    def run() -> int:
        terminal.require_human_terminal("guard remove", need_tty=False)
        code = engine.remove(
            base_dir=base_dir,
            only=only,
            dry_run=dry_run,
            echo=click.echo if dry_run else report.say,
        )
        if code == 0 and not dry_run:
            ui.ok("guards removed" if only is None else f"removed {', '.join(only)}")
        return code

    _guarded(run)


@guard.command("status")
@click.option("--reset-b", is_flag=True, help="Clear the B rejection counters.")
@verbose_option
@click.option(
    "--base-dir", type=click.Path(file_okay=False, path_type=Path), default=None, hidden=True
)
def status_cmd(base_dir: Path | None, reset_b: bool) -> None:
    """Show the guards' consents, policies and drift (read-only)."""

    def run() -> int:
        if reset_b:
            terminal.require_human_terminal("guard status --reset-b", streams=("stdin",))
            cleared = counter.reset(run_dir(base_dir).parent)
            families = "session family" if cleared == 1 else "session families"
            ui.ok(f"B rejection counters cleared ({cleared} {families})")
            return 0
        lines: list[str] = []
        status.report(base_dir, lines.append)
        if ui.verbose():
            for line in lines:
                click.echo(line)
            return 0
        problems = [ln.strip() for ln in lines if report.PROBLEM.search(ln)]
        for line in problems:
            ui.warn(line)
        active = next((ln for ln in lines if ln.startswith("Active groups:")), "")
        groups = active.partition(": ")[2]
        if "absent" in lines[0]:
            ui.info("no guards installed: run `carter guard install`")
        elif problems:
            ui.warn(f"guards: {len(problems)} problem(s)", "run `carter guard install` again")
        else:
            ui.ok("guards", groups if groups != "none" else "none accepted")
        return 0

    _guarded(run)
