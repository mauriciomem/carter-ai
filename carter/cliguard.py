"""Turn the failures a command expects into ``✗ cause`` / ``→ fix`` and exit 1."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

import click

from carter import ui

if TYPE_CHECKING:
    from click.shell_completion import CompletionItem


def report(exc: BaseException) -> bool:
    """Print an expected failure through the output layer; False if ``exc`` is not one."""
    from carter.guard.engine import describe_error  # heavy: only when a command fails

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


class LazyGroup(CarterGroup):
    """A group whose subcommands live in other modules, imported only when one is used.

    ``lazy`` maps a command name to ``("package.module:attr", one-line summary)``. Listing,
    ``--help`` and Tab completion read the summary and import nothing; ``get_command`` imports
    the module. Commands defined on the group itself (``@main.command()``) work as usual.
    """

    def __init__(
        self, *args: object, lazy: Mapping[str, tuple[str, str]] | None = None, **kwargs: object
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.lazy = dict(lazy or {})

    def list_commands(self, ctx: click.Context) -> list[str]:
        return sorted({*self.commands, *self.lazy})

    def get_command(self, ctx: click.Context, cmd_name: str) -> click.Command | None:
        if cmd_name not in self.lazy:
            return super().get_command(ctx, cmd_name)
        module, _, attr = self.lazy[cmd_name][0].partition(":")
        return getattr(importlib.import_module(module), attr)

    def _visible(self, ctx: click.Context, prefix: str = "") -> list[tuple[str, click.Command]]:
        """The commands to list: a stub (name and summary) stands in for each unimported one."""
        listed = []
        for name in self.list_commands(ctx):
            if name in self.lazy:
                cmd: click.Command | None = click.Command(name, help=self.lazy[name][1])
            else:
                cmd = self.commands.get(name)
            if cmd is not None and not cmd.hidden and name.startswith(prefix):
                listed.append((name, cmd))
        return listed

    def format_commands(self, ctx: click.Context, formatter: click.HelpFormatter) -> None:
        listed = self._visible(ctx)
        if listed:
            limit = formatter.width - 6 - max(len(name) for name, _ in listed)
            with formatter.section("Commands"):
                formatter.write_dl([(name, cmd.get_short_help_str(limit)) for name, cmd in listed])

    def shell_complete(self, ctx: click.Context, incomplete: str) -> list[CompletionItem]:
        from click.shell_completion import CompletionItem

        found = [
            CompletionItem(name, help=cmd.get_short_help_str())
            for name, cmd in self._visible(ctx, incomplete)
        ]
        return [*found, *click.Command.shell_complete(self, ctx, incomplete)]


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
