"""Turn the failures a human-terminal command expects into ``Error: <E-CODE>: ...`` and exit 1."""

from __future__ import annotations

from collections.abc import Callable

import click

from carter.guard.engine import format_error


def guarded(fn: Callable[[], int]) -> None:
    """Run ``fn`` (returns an exit code); expected failures become a ``ClickException``."""
    try:
        code = fn()
    except Exception as exc:
        text = format_error(exc)
        if text is None:
            raise
        raise click.ClickException(text) from exc
    if code:
        raise SystemExit(code)
