"""How ``carter install`` and ``carter uninstall`` call the guard (plan 003 step 15).

Both are the same engine as ``carter guard``, with the rules that make a combined command
safe: an agent shell never changes guards; without a terminal and without ``--yes`` the
install skips them (with a notice) and the uninstall keeps them; and a guard failure is
printed and returned as exit code 1 **without** undoing or aborting the rest. The caller
decides what to do with the code (the install/uninstall already finished its own work).
"""

from __future__ import annotations

from pathlib import Path

import click

from carter import terminal
from carter.guard import engine
from carter.install.paths import guard_state_path


def _run(fn, what: str) -> int:  # type: ignore[no-untyped-def]
    try:
        return int(fn())
    except engine.GuardAbort as exc:
        click.echo(f"  {exc}")
        return 0
    except Exception as exc:
        text = engine.format_error(exc)
        if text is None:
            raise
        click.echo(f"✗ guards: {what} failed: {text}", err=True)
        return 1


def install_guards(base_dir: Path | None, *, assume_yes: bool) -> int:
    """The guard step of ``carter install``. Returns 0, or 1 if the guard step failed."""
    click.echo("\n→ Guards (carter guard install)")
    if terminal.is_agent_shell():
        click.echo(
            "  skipped: this looks like an agent shell. Run `carter guard install` yourself."
        )
        return 0
    return _run(
        lambda: engine.install(
            base_dir=base_dir,
            only=None,
            assume_yes=assume_yes,
            interactive=terminal.stdin_is_tty(),
            dry_run=False,
            print_policies=False,
            echo=click.echo,
            confirm=click.confirm,
        ),
        "install",
    )


def uninstall_guards(base_dir: Path | None, *, assume_yes: bool) -> int:
    """The guard step of ``carter uninstall`` (skipped silently when Carter owns nothing)."""
    if not guard_state_path(base_dir).exists():
        return 0
    click.echo("\n→ Removing guards (carter guard remove)")
    if terminal.is_agent_shell():
        click.echo("  kept: agent shell. Run `carter guard remove` in your own terminal.")
        return 0
    interactive = terminal.stdin_is_tty()
    if not assume_yes and not interactive:
        click.echo("  kept: no terminal and no --yes. Run `carter guard remove` to remove them.")
        return 0
    return _run(
        lambda: engine.remove(
            base_dir=base_dir,
            only=None,
            assume_yes=assume_yes,
            interactive=interactive,
            dry_run=False,
            echo=click.echo,
            confirm=click.confirm,
        ),
        "removal",
    )
