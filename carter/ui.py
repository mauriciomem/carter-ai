"""One small output layer for every Carter command.

``ok`` / ``warn`` / ``info`` / ``fail`` print one line each; ``kv`` prints a compact two-column
table; ``detail`` prints only with ``-v``. A normal run ends in one to three lines.

- Errors say the actual cause and the fix: ``✗ <cause>`` then ``→ <fix>`` (cyan arrow, fix never
  dimmed); only the code is dimmed.
- ``ok``, ``info``, ``kv`` and ``detail`` go to stdout; ``warn`` and ``fail`` go to stderr.
- Colour follows the terminal: none when output is not a terminal, none with ``NO_COLOR``
  (rich reads it) or ``--no-color``. Plain text keeps the same glyphs; on a terminal that cannot
  show them (not UTF-8) they fall back to ``ok``/``!``/``x``/``->``.
- Text is never parsed as markup: a ``[y/N]`` or a ``[identity]`` in a message stays as typed.

Rich is imported on first use so commands that print nothing stay fast.
"""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from typing import Any, TextIO

_state: dict[str, bool] = {"verbose": False, "color": True}

GLYPHS = {"ok": "✓", "warn": "!", "fail": "✗", "fix": "→", "info": "·"}
ASCII = {"ok": "ok", "warn": "!", "fail": "x", "fix": "->", "info": "-"}


def configure(*, verbose: bool | None = None, color: bool | None = None) -> None:
    """Set the global switches (the CLI group calls this for ``-v`` and ``--no-color``)."""
    if verbose is not None:
        _state["verbose"] = verbose
    if color is not None:
        _state["color"] = color


def verbose() -> bool:
    return _state["verbose"]


def _glyph(kind: str, stream: TextIO) -> str:
    encoding = (getattr(stream, "encoding", None) or "ascii").lower().replace("-", "")
    return (GLYPHS if encoding in ("utf8", "utf16", "utf32") else ASCII)[kind]


def _plain(line: str, stream: TextIO) -> str:
    """``line`` as is on a UTF-8 stream, with ASCII stand-ins for its two glyphs otherwise."""
    if _glyph("ok", stream) == GLYPHS["ok"]:
        return line
    return line.replace("⚠", ASCII["warn"]).replace("→", ASCII["fix"])


def _console(stream: TextIO) -> Any:
    from rich.console import Console

    return Console(
        file=stream,
        highlight=False,
        markup=False,
        emoji=False,
        soft_wrap=True,
        no_color=not _state["color"] or None,
        force_terminal=None,
    )


def _text(*parts: tuple[str, str]) -> Any:
    from rich.text import Text

    text = Text()
    for content, style in parts:
        text.append(content, style=style or None)
    return text


def _fix_line(stream: TextIO, fix: str) -> list[tuple[str, str]]:
    """The indented ``  → fix`` line under a warning: the arrow coloured, the fix readable."""
    return [("  ", ""), (_glyph("fix", stream), "cyan"), (f" {fix}", "")]


def _emit(stream: TextIO, *lines: Sequence[tuple[str, str]]) -> None:
    console = _console(stream)
    for parts in lines:
        console.print(_text(*parts))


def ok(text: str, detail: str = "") -> None:
    """``✓ text`` (and a dimmed ``detail`` after it)."""
    out = sys.stdout
    parts = [(_glyph("ok", out), "green"), (f" {text}", "")]
    if detail:
        parts.append((f"  {detail}", "dim"))
    _emit(out, parts)


def info(text: str) -> None:
    """A plain line, dimmed on a terminal."""
    _emit(sys.stdout, [(text, "dim")])


def detail(text: str) -> None:
    """A line shown only with ``-v``."""
    if _state["verbose"]:
        _emit(sys.stdout, [(f"  {text}", "dim")])


def warn(text: str, fix: str = "") -> None:
    """``! text`` on stderr (one line; the optional fix is a second, indented one)."""
    err = sys.stderr
    lines = [[(_glyph("warn", err), "yellow"), (f" {text}", "")]]
    if fix:
        lines.append(_fix_line(err, fix))
    _emit(err, *lines)


def fail(cause: str, fix: str = "", code: str = "", *, inline: bool = False) -> None:
    """``✗ cause`` / ``→ fix`` with the error code dimmed at the end, on stderr.

    ``inline`` puts the fix on the cause's line: ``✗ cause → fix``."""
    err = sys.stderr
    tail = [(f"  {code}", "dim")] if code else []
    first = [(_glyph("fail", err), "red bold"), (f" {cause}", "")]
    if fix and inline:
        _emit(err, [*first, (f" {_glyph('fix', err)} ", "cyan"), (fix, ""), *tail])
    elif fix:
        _emit(err, [*first], [(_glyph("fix", err), "cyan"), (f" {fix}", ""), *tail])
    else:
        _emit(err, [*first, *tail])


def kv(rows: Iterable[tuple[str, str]], *, indent: int = 2) -> None:
    """A compact key/value table: dim keys, aligned values, no borders."""
    items = [(k, v) for k, v in rows if v != ""]
    if not items:
        return
    width = max(len(k) for k, _ in items)
    pad = " " * indent
    _emit(sys.stdout, *([(f"{pad}{k:<{width}}  ", "dim"), (v, "")] for k, v in items))


def summary(*parts: str) -> None:
    """``✓ a · b · c``: the one line a command ends with."""
    ok(" · ".join(p for p in parts if p))


def items(rows: Sequence[Any], noun: str, *, all_items: bool | None = None) -> int:
    """Print ``checkitems.Item`` results compactly; returns the exit code (1 if any is red).

    Normal runs show only warnings and problems, then one summary line. ``-v`` shows everything."""
    from carter.checkitems import exit_code

    show_all = verbose() if all_items is None else all_items
    out, err = sys.stdout, sys.stderr
    for row in rows:
        if row.level in ("ok", "info") and not show_all:
            continue
        mark = {"ok": "ok", "info": "info", "warn": "warn", "red": "fail"}[row.level]
        stream = err if row.level in ("warn", "red") else out
        if row.raw:
            _emit(stream, [(_plain(row.raw, stream), "yellow")])
            continue
        style = {"ok": "green", "info": "dim", "warn": "yellow", "red": "red bold"}[row.level]
        lines = [[(_glyph(mark, stream), style), (f" {row.area}: ", "bold"), (row.text, "")]]
        if row.fix:
            lines.append(_fix_line(stream, row.fix))
        _emit(stream, *lines)
    red = sum(1 for r in rows if r.level == "red")
    warns = sum(1 for r in rows if r.level == "warn")
    if red:
        fail(
            f"{noun}: {red} problem{'s' if red != 1 else ''}"
            + (f", {warns} warning{'s' if warns != 1 else ''}" if warns else "")
        )
    else:
        ok(noun, f"{warns} warning{'s' if warns != 1 else ''}" if warns else "")
    return exit_code(list(rows))
