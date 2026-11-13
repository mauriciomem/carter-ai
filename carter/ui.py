"""One small output layer for every Carter command.

``ok`` / ``warn`` / ``info`` / ``fail`` print one line each; ``kv`` prints a compact two-column
table; ``detail`` prints only with ``-v``. A normal run ends in one to three lines.
The reports of ``install`` and ``uninstall`` add ``header`` / ``section`` / ``rows`` / ``steps``:
a title, blank-line-separated sections of aligned rows, and the closing commands.

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
from typing import Any, NamedTuple, TextIO

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


# Every non-ASCII character Carter prints, with its stand-in on a stream that cannot show it.
# The one place that owns the fallback: ``_emit`` runs all text through ``_plain``.
STAND_INS = {
    GLYPHS["ok"]: ASCII["ok"],
    GLYPHS["fail"]: ASCII["fail"],
    GLYPHS["fix"]: ASCII["fix"],
    GLYPHS["info"]: ASCII["info"],
    "⚠": ASCII["warn"],
    "…": "...",
    "—": "-",
}


def _glyph(kind: str, stream: TextIO) -> str:
    encoding = (getattr(stream, "encoding", None) or "ascii").lower().replace("-", "")
    return (GLYPHS if encoding in ("utf8", "utf16", "utf32") else ASCII)[kind]


def _plain(line: str, stream: TextIO) -> str:
    """``line`` as is on a UTF-8 stream. Otherwise the glyphs become ASCII stand-ins and any
    other character the stream cannot encode becomes a ``\\xe9`` / ``\\u2260`` escape: printing
    never raises, and a path or command in the text stays exact when copied (``?`` would be a
    shell glob)."""
    if _glyph("ok", stream) == GLYPHS["ok"]:
        return line
    line = line.replace(" · ", ", ")  # an inline list reads as a list, not as dashes
    for glyph, stand_in in STAND_INS.items():
        line = line.replace(glyph, stand_in)
    encoding = getattr(stream, "encoding", None) or "ascii"
    try:
        return line.encode(encoding, "backslashreplace").decode(encoding)
    except LookupError:  # a codec name Python does not know
        return line.encode("ascii", "backslashreplace").decode("ascii")


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


def _fix_line(stream: TextIO, fix: str, indent: int = 2) -> list[tuple[str, str]]:
    """The indented ``  → fix`` line under a warning: the arrow coloured, the fix readable."""
    return [(" " * indent, ""), (_glyph("fix", stream), "cyan"), (f" {fix}", "")]


def _emit(stream: TextIO, *lines: Sequence[tuple[str, str]]) -> None:
    console = _console(stream)
    for parts in lines:
        console.print(_text(*((_plain(content, stream), style) for content, style in parts)))


def ok(text: str, detail: str = "", *, strong: bool = False) -> None:
    """``✓ text`` (and a dimmed ``detail`` after it); ``strong`` is the bold green verdict."""
    out = sys.stdout
    parts = [(_glyph("ok", out), "green"), (f" {text}", "green bold" if strong else "")]
    if detail:
        parts.append((f"  {detail}", "dim"))
    _emit(out, parts)


def info(text: str, *, indent: int = 0) -> None:
    """A plain line, dimmed on a terminal."""
    _emit(sys.stdout, [(" " * indent + text, "dim")])


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


def next(text: str) -> None:
    """``→ text``: what to do now, on stdout, with the arrow in the fix colour."""
    out = sys.stdout
    _emit(out, [(_glyph("fix", out), "cyan"), (f" {text}", "")])


# --- the report layout: header, sections, aligned rows, closing steps --------------------------
#
#   Carter uninstall  v0.19.2            header: bold title, dim note
#                                        one blank line before every section
#   ✓ Removed                            section: coloured glyph + coloured bold title (+ dim note)
#       agents            8              rows at INDENT: label  count  note, columns aligned
#   · Kept, because they are yours
#       ~/.carter/memories/  12  files   path: dim folder, readable name; count bold; note dim
#
#   ✓ Uninstalled                        verdict: bold green
#   → last step  uv tool uninstall x     steps: cyan arrow, command bold cyan, commands aligned

INDENT = 4  # where the rows of a section start
_GLYPH_STYLE = {"ok": "green", "warn": "yellow bold", "fail": "red bold", "info": "dim"}
_TITLE_STYLE = {"ok": "green bold", "warn": "yellow bold", "fail": "red bold", "info": "bold"}
COMMAND_STYLE = "cyan bold"


class Row(NamedTuple):
    """One report line: ``label  count  note``, and an optional ``→ fix`` line under it."""

    label: str
    num: int | None = None
    note: str = ""
    cmd: bool = False  # the note is a command to copy: bold cyan instead of dim, never shortened
    fix: str = ""


def _width(stream: TextIO) -> int | None:
    """Columns of a terminal; ``None`` for a pipe or file (nothing is laid out for it)."""
    console = _console(stream)
    return int(console.width) if console.is_terminal else None


def _path_parts(label: str) -> list[tuple[str, str]]:
    """``~/.carter/`` dim, ``memories/`` readable: the name is what the eye needs."""
    stem = label.rstrip("/")
    head, slash, leaf = stem.rpartition("/")
    return [(head + slash, "dim"), (leaf + label[len(stem) :], "")]


def gap() -> None:
    """One blank line (before the closing verdict)."""
    _emit(sys.stdout, [("", "")])


def header(title: str, note: str = "") -> None:
    """The first line of a report: ``Carter install  v0.19.2``."""
    _emit(sys.stdout, [(title, "bold"), *([(f"  {note}", "dim")] if note else [])])


def section(title: str, kind: str = "info", note: str = "") -> None:
    """A blank line, then ``✓ Title  (note)``. ``warn`` and ``fail`` sections go to stderr."""
    stream = sys.stderr if kind in ("warn", "fail") else sys.stdout
    glyph = _glyph(kind, stream).ljust(1 if _glyph("ok", stream) == GLYPHS["ok"] else 2)
    parts = [(glyph, _GLYPH_STYLE[kind]), (f" {title}", _TITLE_STYLE[kind])]
    if note:
        parts.append((f"  ({note})", "dim"))
    _emit(stream, [("", "")], parts)


def rows(items: Iterable[Row], *, paths: bool = False, err: bool = False) -> None:
    """The lines of a section as aligned columns (``err`` for a warning section).

    On a terminal, a row that does not fit becomes two lines (label, then count and note under
    it) while the others keep their columns; a pipe or file always gets the columns, one line per
    row. Nothing is cut."""
    items = list(items)
    if not items:
        return
    stream = sys.stderr if err else sys.stdout
    label_w = max(len(r.label) for r in items)
    count_w = max((len(str(r.num)) for r in items if r.num is not None), default=0)
    width = _width(stream)
    lines: list[list[tuple[str, str]]] = []
    for r in items:
        name = _path_parts(r.label) if paths else [(r.label, "")]
        count = "" if r.num is None else str(r.num)
        note = (r.note, COMMAND_STYLE if r.cmd else "dim")
        wide = (
            INDENT + label_w + (count_w + 2 if count_w else 0) + (len(r.note) + 2 if r.note else 0)
        )
        if width is not None and wide > width:
            lines.append([(" " * INDENT, ""), *name])
            if count or r.note:
                gap_ = " " if count and r.note else ""
                lines.append([(" " * (INDENT + 2), ""), (count, "bold"), (gap_, ""), note])
        else:
            parts = [(" " * INDENT, ""), *name]
            if count or r.note:  # a bare label ends at its last visible character
                parts.append((" " * (label_w - len(r.label) + 2), ""))
                if count_w:
                    parts.append((count.rjust(count_w), "bold" if count else ""))
                if r.note:
                    parts += [("  " if count_w else "", ""), note]
            lines.append(parts)
        if r.fix:
            lines.append(_fix_line(stream, r.fix, INDENT + 2))
    _emit(stream, *lines)


def steps(items: Sequence[tuple[str, str]]) -> None:
    """``→ label  command`` lines: cyan arrows, bold cyan commands, commands aligned."""
    out = sys.stdout
    arrow = _glyph("fix", out)
    label_w = max(len(label) for label, _ in items)
    width = _width(out)
    lines: list[list[tuple[str, str]]] = []
    for label, command in items:
        if width is not None and len(arrow) + 1 + label_w + 2 + len(command) > width:
            lines += [
                [(arrow, "cyan"), (f" {label}", "")],
                [(" " * (len(arrow) + 1), ""), (command, COMMAND_STYLE)],
            ]
        else:
            lines.append(
                [(arrow, "cyan"), (f" {label.ljust(label_w)}  ", ""), (command, COMMAND_STYLE)]
            )
    _emit(out, *lines)


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
            _emit(stream, [(row.raw, "yellow")])
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
