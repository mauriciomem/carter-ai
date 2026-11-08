"""How ``carter install`` and ``carter uninstall`` call the guard (plan 003 step 15, D68 h).

Both are the same engine as ``carter guard``, with the rules that make a combined command
safe: an agent shell never changes guards; without a terminal and without ``--yes`` the
install skips them (with a notice); and a guard failure is printed and returned as exit code 1
**without** undoing or aborting the rest. Nothing is asked on the way out. The caller decides what
to do with the code (the install/uninstall already finished its own work).
"""

from __future__ import annotations

from pathlib import Path

import click

from carter import terminal, ui
from carter.guard import engine, report
from carter.install.paths import guard_state_path


def _run(fn, what: str) -> int:  # type: ignore[no-untyped-def]
    try:
        return int(fn())
    except engine.GuardAbort as exc:
        ui.info(f"  {exc}")
        return 0
    except Exception as exc:
        found = engine.describe_error(exc)
        if found is None:
            raise
        cause, fix, code = found
        ui.fail(f"guards: {what} failed: {cause}", fix, code)
        return 1


def install_guards(base_dir: Path | None, *, assume_yes: bool) -> int:
    """The guard step of ``carter install``. Returns 0, or 1 if the guard step failed."""
    if terminal.is_agent_shell():
        ui.warn("guards skipped: this looks like an agent shell", "run `carter guard install`")
        return 0

    def run() -> int:
        code = engine.install(
            base_dir=base_dir,
            only=None,
            assume_yes=assume_yes,
            interactive=terminal.stdin_is_tty(),
            dry_run=False,
            echo=report.say,
            confirm=click.confirm,
        )
        if code == 0:
            report.installed(base_dir)
        return code

    return _run(run, "install")


def uninstall_guards(base_dir: Path | None, *, assume_yes: bool) -> int:
    """The guard step of ``carter uninstall`` (skipped silently when Carter owns nothing)."""
    del assume_yes  # nothing is asked any more (D68 h)
    if not guard_state_path(base_dir).exists():
        return 0
    if terminal.is_agent_shell():
        ui.warn("guards kept: agent shell", "run `carter guard remove` yourself")
        return 0

    def run() -> int:
        code = engine.remove(base_dir=base_dir, only=None, dry_run=False, echo=report.say)
        if code == 0:
            ui.ok("guards removed")
        return code

    return _run(run, "removal")


def uninstall_identity(base_dir: Path | None, *, assume_yes: bool) -> int:
    """The identity step of ``carter uninstall``: ``carter identity remove``; an agent shell
    keeps everything. Nothing is asked."""
    del assume_yes
    from carter import identity_remove

    if terminal.is_agent_shell():
        ui.warn("LLM identity kept: agent shell", "run `carter identity remove` yourself")
        return 0
    report_ = identity_remove.remove_identity(base_dir)
    for line in report_.removed:
        ui.detail(f"removed {line}")
    for line in report_.kept:
        ui.warn(f"kept {line}")
    if report_.removed:
        ui.ok("LLM identity removed")
    return 0
