"""A stream that cannot show Unicode (``encoding="ascii"``) never receives a non-ASCII byte.

``CliRunner(charset="ascii")`` gives the command a strict ASCII stdout, so a glyph that skips
``ui``'s fallback raises ``UnicodeEncodeError`` (stderr would hide it behind a backslash escape,
so it is checked for ``\\u`` too).
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter import ui
from carter.cli import main


def _assert_ascii(result: Result) -> None:
    assert result.exception is None or isinstance(result.exception, SystemExit), result.exception
    assert result.stdout_bytes.isascii() and result.stderr_bytes.isascii()
    assert "\\u" not in result.stderr and "\\x" not in result.stderr


def _run(*args: str) -> Result:
    return CliRunner(charset="ascii").invoke(main, list(args))


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    target = tmp_path / "ws"
    target.mkdir()
    assert _run("init", str(target), "--no-git-state").exit_code == 0
    return target


def test_check_prints_only_ascii(ws: Path) -> None:
    result = _run("check", str(ws), "--no-harness", "-v")
    assert result.exit_code == 0 and "ok Workspace OK" in result.stdout
    _assert_ascii(result)


def test_a_failed_check_prints_only_ascii(ws: Path) -> None:
    next((ws / ".opencode" / "agents").glob("carter-pm*.md")).unlink()
    result = _run("check", str(ws), "--no-harness")
    assert result.exit_code == 1 and "-> run `carter update`" in result.stderr
    _assert_ascii(result)


def test_install_prints_only_ascii(fake_opencode, tmp_path: Path) -> None:
    fake_opencode()
    result = _run("install", "--base-dir", str(tmp_path / "home"))
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[-1].startswith("-> restart the OpenCode server")
    _assert_ascii(result)


def test_next_prints_only_ascii(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii")  # strict: a stray glyph raises
    monkeypatch.setattr("sys.stdout", stream)
    ui.next("go on")
    stream.flush()
    assert raw.getvalue().decode("ascii") == "-> go on\n"


@pytest.mark.parametrize(
    ("glyph", "stand_in"),
    [("✓", "ok"), ("✗", "x"), ("→", "->"), ("⚠", "!"), ("·", "-"), ("…", "..."), ("—", "-")],
)
def test_every_printed_glyph_has_an_ascii_stand_in(glyph: str, stand_in: str) -> None:
    ascii_stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    utf8_stream = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    assert ui._plain(f"a {glyph} b", ascii_stream) == f"a {stand_in} b"
    assert ui._plain(f"a {glyph} b", utf8_stream) == f"a {glyph} b"


def test_a_character_without_a_stand_in_becomes_a_question_mark() -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="ascii")
    assert ui._plain("caf\u00e9 \u2260", stream) == "caf? ?"
