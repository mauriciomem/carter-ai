"""Golden snapshots of ``carter access``: the three levels, an override, a workspace that
tightens, an opt-out and a missing group, each as the command prints it.

Pipe text is pinned in ``golden/access-*.txt`` (``pytest tests/snapshots --update-golden``
rewrites them; read the diff). The other terminals are checked against the pipe text: a
terminal with ``NO_COLOR`` has the same words, a strict ASCII stream has the same bytes, and a
colour terminal only adds escapes.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path
from unittest import mock

import pytest

from carter import access_cli, ui
from carter.access import Access, missing_group_lines, resolve
from snapshots.term import ANSI, Term

GOLDEN = Path(__file__).parent / "golden"
ALL_GROUPS = ["g2", "hooks", "sudo-docker", "read-edit-denies", "config-edit"]
_FOREIGN = ("NO_COLOR", "COLORTERM", "FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE")


def _scenarios() -> dict[str, tuple[Access, bool, list[str]]]:
    """name -> (resolved access, opt-out for this workspace, accepted consent groups)."""
    return {
        "strict": (resolve(None), False, ALL_GROUPS),
        "guarded": (resolve({"level": "guarded"}), False, ALL_GROUPS),
        "relaxed": (resolve({"level": "relaxed"}), False, ALL_GROUPS),
        "mixed": (
            resolve(
                {"level": "guarded", "pr_write": "ask"},
                workspace={"destructive": "denied", "issue_write": "denied"},
            ),
            True,
            [g for g in ALL_GROUPS if g != "g2"],
        ),
        "fallback": (resolve({"level": "guarded", "gitcommit": "ask"}), False, ALL_GROUPS),
    }


def play(
    name: str, kind: str, *, columns: int = 100, no_color: bool = False, v: bool = False
) -> Term:
    access, opt_out, accepted = _scenarios()[name]
    term = Term(kind)
    env = {"COLUMNS": str(columns), "TERM": "xterm-256color"}
    with mock.patch.dict(os.environ, env), contextlib.ExitStack() as stack:
        for key in _FOREIGN:
            os.environ.pop(key, None)
        if no_color:
            os.environ["NO_COLOR"] = "1"
        stack.enter_context(contextlib.redirect_stdout(term.out))  # type: ignore[type-var]
        stack.enter_context(contextlib.redirect_stderr(term.err))  # type: ignore[type-var]
        ui.configure(verbose=v, color=True)
        access_cli.show(access, opt_out=opt_out, lines=missing_group_lines(accepted))
    ui.configure(verbose=False, color=True)
    return term


def _golden(name: str, text: str, update: bool) -> None:
    path = GOLDEN / f"access-{name}.txt"
    if update:
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"{path.name} differs (--update-golden)"


@pytest.mark.parametrize("name", list(_scenarios()))
def test_the_pipe_text_matches_its_golden_file(name: str, update_golden: bool) -> None:
    _golden(name, play(name, "pipe").text(), update_golden)


@pytest.mark.parametrize("name", ["guarded", "mixed"])
def test_verbose_adds_what_enforces_each_row(name: str, update_golden: bool) -> None:
    text = play(name, "pipe", v=True).text()
    assert text.count("enforced by") == 15 and "enforced by" not in play(name, "pipe").text()
    _golden(f"{name}-v", text, update_golden)


@pytest.mark.parametrize("name", list(_scenarios()))
@pytest.mark.parametrize("v", [False, True])
def test_no_color_keeps_the_text_of_a_pipe(name: str, v: bool) -> None:
    piped = play(name, "pipe", v=v).text()
    plain = play(name, "tty", no_color=True, v=v).text()
    assert "\x1b" not in piped
    assert ANSI.sub("", plain) == piped
    assert not any(f"\x1b[{code}m" in plain for code in (31, 32, 33, 36))  # bold and dim stay


@pytest.mark.parametrize("name", list(_scenarios()))
def test_a_terminal_that_cannot_show_unicode_gets_the_same_bytes(name: str) -> None:
    ascii_text = play(name, "ascii", v=True).text()  # a non-ASCII character would raise
    assert ascii_text.isascii()
    assert ascii_text == play(name, "pipe", v=True).text()


def test_colour_only_on_a_terminal() -> None:
    assert "\x1b[" in play("mixed", "tty").text()
    assert ANSI.sub("", play("mixed", "tty").text()) == play("mixed", "pipe").text()


@pytest.mark.parametrize("name", list(_scenarios()))
@pytest.mark.parametrize("v", [False, True])
def test_no_line_is_wider_than_80_and_the_status_lines_than_60(name: str, v: bool) -> None:
    lines = play(name, "pipe", v=v).text().splitlines()
    assert max(len(line) for line in lines) <= 80
    status = [ln for ln in lines if ln.startswith(("Access level", "!", "see:"))]
    assert status and all(len(ln) <= 60 for ln in status), status


@pytest.mark.parametrize("v", [False, True])
def test_on_a_60_column_terminal_the_rows_stack_and_nothing_is_cut(
    v: bool, update_golden: bool
) -> None:
    text = ANSI.sub("", play("mixed", "tty", columns=60, v=v).text())
    widest = max(len(line) for line in text.splitlines())
    assert widest <= (80 if v else 60)  # the "enforced by" lines wrap on a narrow terminal
    assert text.count("[") == 15
    _golden(f"mixed{'-v' if v else ''}.w60", text, update_golden)
