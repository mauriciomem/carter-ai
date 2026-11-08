"""The output layer (D68 a): short lines, cause and fix, no markup surprises, plain when piped."""

from __future__ import annotations

import io

import pytest

from carter import ui
from carter.checkitems import Item


@pytest.fixture(autouse=True)
def _reset() -> None:
    ui.configure(verbose=False, color=True)


def test_ok_is_one_line_with_a_check_mark(capsys: pytest.CaptureFixture[str]) -> None:
    ui.ok("main → origin", "1 commit")
    out = capsys.readouterr()
    assert out.out == "✓ main → origin  1 commit\n" and out.err == ""


def test_fail_has_the_cause_the_fix_and_the_code_last(capsys: pytest.CaptureFixture[str]) -> None:
    ui.fail("that is a private key", "pass the .pub file", "E-IDENTITY-CHECK")
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err.splitlines() == [
        "✗ that is a private key",
        "→ pass the .pub file  E-IDENTITY-CHECK",
    ]


def test_fail_without_a_fix_puts_the_code_on_the_cause_line(
    capsys: pytest.CaptureFixture[str],
) -> None:
    ui.fail("nothing to push", code="E-APLUS-ARGS")
    assert capsys.readouterr().err == "✗ nothing to push  E-APLUS-ARGS\n"


def test_warn_goes_to_stderr_and_is_one_line(capsys: pytest.CaptureFixture[str]) -> None:
    ui.warn("the key has no passphrase")
    out = capsys.readouterr()
    assert out.out == "" and out.err == "! the key has no passphrase\n"


def test_square_brackets_are_not_markup(capsys: pytest.CaptureFixture[str]) -> None:
    ui.fail("[identity] mode is not [bold]auto[/bold]", "set [y/N]")
    err = capsys.readouterr().err
    assert "[identity] mode is not [bold]auto[/bold]" in err and "set [y/N]" in err


def test_a_long_line_is_not_wrapped_or_cut(capsys: pytest.CaptureFixture[str]) -> None:
    long = "x" * 300
    ui.ok(long)
    assert capsys.readouterr().out == f"✓ {long}\n"


def test_no_escape_codes_when_not_a_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    ui.ok("a")
    ui.fail("b", "c", "E-X")
    ui.kv([("k", "v")])
    out = capsys.readouterr()
    assert "\x1b" not in out.out + out.err


def test_no_color_flag_and_env_keep_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    stream.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setenv("FORCE_COLOR", "1")
    ui.ok("coloured")
    assert "\x1b[" in stream.getvalue()
    stream.truncate(0)
    stream.seek(0)
    ui.configure(color=False)
    ui.ok("plain")
    assert "\x1b[3" not in stream.getvalue() and "plain" in stream.getvalue()


def test_no_color_env_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    stream = io.StringIO()
    stream.isatty = lambda: True  # type: ignore[method-assign]
    monkeypatch.setattr("sys.stdout", stream)
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.setenv("NO_COLOR", "1")
    ui.ok("text")
    assert "\x1b[3" not in stream.getvalue() and "text" in stream.getvalue()


def test_ascii_fallback_when_the_stream_cannot_show_the_glyphs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="ascii", errors="replace")
    monkeypatch.setattr("sys.stdout", stream)
    ui.ok("done")
    stream.flush()
    assert raw.getvalue() == b"ok done\n"


def test_kv_is_aligned_and_skips_empty_values(capsys: pytest.CaptureFixture[str]) -> None:
    ui.kv([("login", "mauri"), ("tier", "T2"), ("note", "")])
    assert capsys.readouterr().out.splitlines() == ["  login  mauri", "  tier   T2"]


def test_summary_joins_with_middle_dots(capsys: pytest.CaptureFixture[str]) -> None:
    ui.summary("mauri-droid", "T2", "SHA256:2hx1…")
    assert capsys.readouterr().out == "✓ mauri-droid · T2 · SHA256:2hx1…\n"


def test_detail_only_with_verbose(capsys: pytest.CaptureFixture[str]) -> None:
    ui.detail("hidden")
    assert capsys.readouterr().out == ""
    ui.configure(verbose=True)
    ui.detail("shown")
    assert capsys.readouterr().out == "  shown\n"


class TestItems:
    ROWS = [
        Item("ok", "policies", "39 statements loaded"),
        Item("info", "mirror", "nothing to do"),
        Item("warn", "plugin", "not loaded yet", "restart OpenCode"),
    ]

    def test_a_normal_run_shows_only_what_needs_attention_then_one_summary(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert ui.items(self.ROWS, "host") == 0
        out = capsys.readouterr()
        assert out.err.splitlines() == ["! plugin: not loaded yet", "  → restart OpenCode"]
        assert out.out == "✓ host  1 warning\n"

    def test_verbose_shows_everything(self, capsys: pytest.CaptureFixture[str]) -> None:
        ui.configure(verbose=True)
        ui.items(self.ROWS, "host")
        out = capsys.readouterr().out
        assert "policies: 39 statements loaded" in out and "mirror: nothing to do" in out

    def test_a_red_item_is_a_failure_and_exit_one(self, capsys: pytest.CaptureFixture[str]) -> None:
        rows = [*self.ROWS, Item("red", "git", "cannot parse the config", "rm ~/.carter/gitconfig")]
        assert ui.items(rows, "host") == 1
        err = capsys.readouterr().err
        assert "✗ git: cannot parse the config" in err and "✗ host: 1 problem, 1 warning" in err

    def test_all_good_is_a_single_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        assert ui.items([Item("ok", "a", "b")], "host") == 0
        assert capsys.readouterr().out == "✓ host\n"
