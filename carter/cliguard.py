"""Turn the failures a command expects into ``✗ cause`` / ``→ fix`` and exit 1."""

from __future__ import annotations

from collections.abc import Callable

import click

from carter import ui
from carter.guard.engine import describe_error


def report(exc: BaseException) -> bool:
    """Print an expected failure through the output layer; False if ``exc`` is not one."""
    found = describe_error(exc)
    if found is None:
        return False
    cause, fix, code = found
    ui.fail(cause, fix, code)
    return True


def guarded(fn: Callable[[], int]) -> None:
    """Run ``fn`` (returns an exit code); expected failures are printed and exit 1."""
    try:
        code = fn()
    except Exception as exc:
        if not report(exc):
            raise
        raise SystemExit(1) from exc
    if code:
        raise SystemExit(code)


class CarterGroup(click.Group):
    """The top-level group: a plain ``ClickException`` is shown as ``✗ message`` too."""

    def invoke(self, ctx: click.Context) -> object:
        try:
            return super().invoke(ctx)
        except click.UsageError:
            raise
        except click.ClickException as exc:
            ui.fail(exc.format_message())
            raise SystemExit(exc.exit_code) from exc


def verbose_option(f: Callable[..., object]) -> Callable[..., object]:
    """``-v`` / ``--verbose`` on a command: show the lines a normal run leaves out."""
    return click.option(
        "-v",
        "--verbose",
        is_flag=True,
        expose_value=False,
        help="Show more detail.",
        callback=lambda _c, _p, value: ui.configure(verbose=True) if value else None,
    )(f)
