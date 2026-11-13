"""The report helpers: header, section, rows, steps, gap."""

from __future__ import annotations

import io
import re

import pytest

from carter import ui
from carter.ui import Row


class _Tty(io.StringIO):
    encoding = "utf-8"

    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _reset() -> None:
    ui.configure(verbose=False, color=True)


def _tty(monkeypatch: pytest.MonkeyPatch, columns: int = 100) -> _Tty:
    stream = _Tty()
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setenv("COLUMNS", str(columns))
    monkeypatch.setenv("TERM", "xterm-256color")
    for var in ("NO_COLOR", "FORCE_COLOR", "TTY_COMPATIBLE"):
        monkeypatch.delenv(var, raising=False)
    return stream


def _text(stream: io.StringIO) -> list[str]:
    return re.sub(r"\x1b\[[0-9;]*m", "", stream.getvalue()).splitlines()


ROWS = [
    Row("agents", 8, "new"),
    Row("skills", 27),
    Row("config.toml", None, "created"),
    Row("plugin"),
]


def test_rows_align_label_count_and_note(capsys: pytest.CaptureFixture[str]) -> None:
    ui.rows(ROWS)
    assert capsys.readouterr().out == (
        "    agents        8  new\n    skills       27\n    config.toml      created\n    plugin\n"
    )


def test_a_row_without_a_note_has_no_trailing_blanks(capsys: pytest.CaptureFixture[str]) -> None:
    ui.rows([Row("a", 1), Row("longer")])
    assert all(line == line.rstrip() for line in capsys.readouterr().out.splitlines())


def test_header_section_and_gap(capsys: pytest.CaptureFixture[str]) -> None:
    ui.header("Carter x", "v1")
    ui.section("Kept", note="yours")
    ui.gap()
    assert capsys.readouterr().out == "Carter x  v1\n\n· Kept  (yours)\n\n"


def test_warn_sections_and_rows_go_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    ui.section("Edited", "warn")
    ui.rows([Row("~/a/b.md", fix="copy: ~/c")], paths=True, err=True)
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == "\n! Edited\n    ~/a/b.md\n      → copy: ~/c\n"


def test_narrow_terminal_stacks_a_row_and_never_cuts_it(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _tty(monkeypatch, columns=30)
    command = "rm /home/u/src/proj/.opencode/agents/carter-*.md"
    ui.rows([Row("~/src/proj", None, command, cmd=True)], paths=True)
    lines = _text(out)
    assert lines == ["    ~/src/proj", f"      {command}"]  # whole, though wider than the terminal


def test_only_the_rows_that_do_not_fit_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _tty(monkeypatch, columns=40)
    ui.rows(
        [Row("agents", 8, "new"), Row("guards", None, "g2 · hooks · sudo-docker · config-edit")]
    )
    assert _text(out) == [
        "    agents  8  new",
        "    guards",
        "      g2 · hooks · sudo-docker · config-edit",
    ]


def test_a_pipe_never_stacks(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLUMNS", "20")
    ui.rows([Row("~/src/proj", None, "rm /home/u/src/proj/.opencode/agents/carter-*.md")])
    assert capsys.readouterr().out.count("\n") == 1  # one line per row


def test_paths_dim_the_folder_and_keep_the_name_readable(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _tty(monkeypatch)
    ui.rows([Row("~/.carter/memories/")], paths=True)
    assert "\x1b[2m~/.carter/\x1b[0mmemories/" in out.getvalue()


def test_palette_titles_take_the_role_colour_and_commands_are_bold_cyan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _tty(monkeypatch)
    ui.section("Removed", "ok")
    ui.rows([Row("agents", 8)])
    ui.steps([("last", "uv tool uninstall carter-ai")])
    text = out.getvalue()
    assert "\x1b[1;32m Removed" in text  # title: bold green, next to its green glyph
    assert "\x1b[1m8\x1b[0m" in text  # counts: bold
    assert "\x1b[1;36muv tool uninstall carter-ai" in text  # command: bold cyan


def test_no_colour_keeps_bold_and_dim(monkeypatch: pytest.MonkeyPatch) -> None:
    out = _tty(monkeypatch)
    monkeypatch.setenv("NO_COLOR", "1")
    ui.section("Removed", "ok")
    ui.rows([Row("~/a/b", 8, "note")], paths=True)
    text = out.getvalue()
    assert "\x1b[32m" not in text and "\x1b[1;32m" not in text
    assert "\x1b[1m" in text and "\x1b[2m" in text


def test_ascii_stream_gets_ascii_glyphs_padded_so_titles_line_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="strict")
    monkeypatch.setattr("sys.stdout", stream)
    ui.section("Removed", "ok")
    ui.section("Kept")
    ui.rows([Row("guards", None, "g2 · hooks · ñ")])
    ui.steps([("last step", "uv tool uninstall carter-ai")])
    stream.flush()
    assert raw.getvalue().decode() == (
        "\nok Removed\n\n-  Kept\n    guards  g2, hooks, \\xf1\n"
        "-> last step  uv tool uninstall carter-ai\n"
    )


def test_steps_align_the_commands(capsys: pytest.CaptureFixture[str]) -> None:
    ui.steps(
        [("last step", "uv tool uninstall carter-ai"), ("to delete everything", "rm -r ~/.carter")]
    )
    assert capsys.readouterr().out == (
        "→ last step             uv tool uninstall carter-ai\n"
        "→ to delete everything  rm -r ~/.carter\n"
    )


def test_a_step_that_does_not_fit_puts_its_command_on_the_next_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    out = _tty(monkeypatch, columns=30)
    ui.steps([("last step", "uv tool uninstall carter-ai")])
    assert _text(out) == ["→ last step", "  uv tool uninstall carter-ai"]
