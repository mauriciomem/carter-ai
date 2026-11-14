"""Golden snapshots of the install and uninstall reports.

Six scenarios, each as it reaches a colour terminal, a terminal with ``NO_COLOR``, a pipe and a
strict ASCII stream, plus two 60-column terminals. A golden file is the combined stdout + stderr
text; ``pytest tests/snapshots --update-golden`` rewrites them (read the diff before committing).

The ``.ansi`` files pin Rich's exact escape codes, which is the point (a colour on the wrong word
fails here) and the cost: a ``rich`` upgrade that joins style codes differently fails them all with
no change in meaning. Then confirm the plain-text tests below still pass (they compare the text with
the escapes stripped) and run ``--update-golden``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from snapshots.scenarios import NAMES, play
from snapshots.term import ANSI

GOLDEN = Path(__file__).parent / "golden"
VARIANTS = {  # name: (terminal kind, NO_COLOR, columns, file suffix)
    "color": ("tty", False, 100, "ansi"),
    "nocolor": ("tty", True, 100, "ansi"),
    "pipe": ("pipe", False, 100, "txt"),
    "ascii": ("ascii", False, 100, "txt"),
}
NARROW = ("install-edited", "uninstall-full")


def _check(file: str, text: str, update: bool) -> None:
    path = GOLDEN / file
    if update:
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    assert text == path.read_text(encoding="utf-8"), f"{file} differs (--update-golden rewrites)"


@pytest.mark.parametrize("variant", VARIANTS)
@pytest.mark.parametrize("name", NAMES)
def test_report_matches_its_golden_file(name: str, variant: str, update_golden: bool) -> None:
    kind, no_color, columns, suffix = VARIANTS[variant]
    text = play(name, kind, columns=columns, no_color=no_color).text()
    _check(f"{name}.{variant}.{suffix}", text, update_golden)


@pytest.mark.parametrize("name", NARROW)
def test_report_at_60_columns_stacks_the_rows_that_do_not_fit(
    name: str, update_golden: bool
) -> None:
    text = ANSI.sub("", play(name, "tty", columns=60).text())
    _check(f"{name}.w60.txt", text, update_golden)


@pytest.mark.parametrize("name", NAMES)
def test_no_color_keeps_the_text_of_a_pipe_and_a_pipe_has_no_escapes(name: str) -> None:
    piped = play(name, "pipe").text()
    assert "\x1b" not in piped
    assert ANSI.sub("", play(name, "tty", no_color=True).text()) == piped


@pytest.mark.parametrize("name", NAMES)
def test_colour_is_only_on_a_terminal_and_no_color_leaves_bold_and_dim(name: str) -> None:
    coloured = play(name, "tty").text()
    plain = play(name, "tty", no_color=True).text()
    assert "\x1b[32m" in coloured and "\x1b[1m" in coloured
    assert not any(f"\x1b[{c}m" in plain for c in (31, 32, 33, 36)) and "\x1b[1m" in plain


def test_only_the_warning_sections_and_notices_go_to_stderr() -> None:
    edited = play("uninstall-full", "pipe")
    assert edited.text("err") == (
        "\n! Removed although you edited them\n"
        "    ~/.config/opencode/agents/carter-pm.md\n"
        "      → copy: ~/.carter/backups/20261112T101500/.config/opencode/agents/carter-pm.md\n"
    )
    replaced = play("install-edited", "pipe")
    assert replaced.text("err") == (
        "! gh CLI not found (optional)\n"
        "\n! Replaced 3 files you had edited  (copies in ~/.carter/backups/20261112T101500/)\n"
    )
    assert "Kept" in edited.text("out") and "Replaced" not in replaced.text("out")


def test_the_order_of_both_streams_is_the_order_a_terminal_shows(update_golden: bool) -> None:
    _check("uninstall-full.routed.txt", play("uninstall-full", "pipe").routed(), update_golden)
