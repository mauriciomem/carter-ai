"""A dotfile-managed (symlinked) global git config: what ``carter`` prints about the include line.

Every message is one line (no literal ``\\n``), at most 80 characters; the way to learn the line to
add is a help pointer on its own ``→`` line. A line the human already added counts in any spelling
git resolves to Carter's file (``~/`` or absolute), and then nothing is printed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter.cli import main
from carter.home import tilde
from carter.install.paths import carter_gitconfig_path
from guard.helpers import debug_config

HARD_MAX = 80  # the output rule: status lines target 60, hard max 80


def global_cfg() -> Path:
    return Path(os.environ["GIT_CONFIG_GLOBAL"])


def guard(*args: str) -> Result:
    return CliRunner().invoke(main, ["guard", *args], catch_exceptions=False)


def one_line_each(output: str) -> None:
    assert "\\n" not in output, output
    assert all(len(line) <= HARD_MAX for line in output.splitlines()), output


def dotfiles(tmp_path: Path, *, include: str | None = None) -> Path:
    """Make the global config a symlink into 'dotfiles'; ``include`` is the line the human added."""
    real = tmp_path / "dotfiles" / "gitconfig"
    real.parent.mkdir()
    text = global_cfg().read_text()
    real.write_text(text + (f"[include]\n\tpath = {include}\n" if include else ""))
    global_cfg().unlink()
    global_cfg().symlink_to(real)
    return real


def forms() -> dict[str, str]:
    """The same file, spelled the ways a dotfiles repo spells it."""
    absolute = str(carter_gitconfig_path(None))
    return {"tilde": "~/.carter/gitconfig", "absolute": absolute}


@pytest.fixture(autouse=True)
def _default_output() -> None:
    from carter import ui

    ui.configure(verbose=False)  # the -v switch is process-wide: these tests read the default


@pytest.fixture
def warned() -> str:
    return f"! {tilde(global_cfg())} is a symlink: add Carter's include line"


class TestInstallOnASymlinkedConfig:
    def test_no_line_yet_one_warning_and_a_help_pointer(
        self, stack, tmp_path: Path, warned: str
    ) -> None:
        dotfiles(tmp_path)
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        lines = res.output.splitlines()
        assert lines.count(warned) == 1
        assert lines[lines.index(warned) + 1] == "  → see: carter install --help"
        one_line_each(res.output)

    @pytest.mark.parametrize("spelling", ["tilde", "absolute"])
    def test_a_line_you_already_added_prints_nothing(
        self, stack, tmp_path: Path, spelling: str
    ) -> None:
        real = dotfiles(tmp_path, include=forms()[spelling])
        before = real.read_bytes()
        stack.fake()
        res = guard("install", "--yes")
        assert res.exit_code == 0, res.output
        assert "symlink" not in res.output and "include" not in res.output
        assert real.read_bytes() == before and global_cfg().is_symlink()

    def test_a_dry_run_says_the_same_in_the_same_two_lines(
        self, stack, tmp_path: Path, warned: str
    ) -> None:
        dotfiles(tmp_path)
        stack.fake()
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        lines = res.output.splitlines()
        assert lines[lines.index(warned.replace("! ", "⚠ ")) + 1] == "→ see: carter install --help"
        assert "\\n" not in res.output  # the plan has long detail lines; these two are the point

    def test_a_dry_run_is_quiet_when_the_line_is_there(self, stack, tmp_path: Path) -> None:
        dotfiles(tmp_path, include="~/.carter/gitconfig")
        stack.fake()
        res = guard("install", "--dry-run")
        assert res.exit_code == 0, res.output
        assert "symlink" not in res.output


class TestStatus:
    def test_inactive_hooks_are_one_warning_and_a_pointer(self, stack, tmp_path: Path) -> None:
        dotfiles(tmp_path)
        stack.fake()
        guard("install", "--yes")
        stack.fake(before=debug_config(stack.live))
        res = guard("status")
        assert "! include.path: NOT in ~/.gitconfig: hooks inactive" in res.output
        assert "  → see: carter install --help" in res.output
        one_line_each(res.output)

    @pytest.mark.parametrize("spelling", ["tilde", "absolute"])
    def test_a_line_in_either_spelling_is_present(
        self, stack, tmp_path: Path, spelling: str
    ) -> None:
        dotfiles(tmp_path, include=forms()[spelling])
        stack.fake()
        guard("install", "--yes")
        stack.fake(before=debug_config(stack.live))
        res = guard("status", "-v")
        assert "present (you added it" in res.output and "inactive" not in res.output


class TestRemoveOnASymlinkedConfig:
    @pytest.mark.parametrize("spelling", ["tilde", "absolute"])
    def test_the_line_you_added_is_yours_to_remove_in_one_line(
        self, stack, tmp_path: Path, spelling: str
    ) -> None:
        real = dotfiles(tmp_path)
        stack.fake()
        guard("install", "--yes")
        with real.open("a") as fh:
            fh.write(f"[include]\n\tpath = {forms()[spelling]}\n")
        before = real.read_bytes()
        stack.fake(before=debug_config(stack.live), after=debug_config())
        res = guard("remove", "--yes")
        assert res.exit_code == 0, res.output
        lines = res.output.splitlines()
        warning = "! your global git config still includes Carter's file"
        assert lines[lines.index(warning) + 1] == "  → see: carter uninstall --help"
        one_line_each(res.output)
        assert real.read_bytes() == before  # still the human's to edit


class TestSay:
    def test_an_arrow_line_is_a_fix_under_the_warning_before_it(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from carter.guard import report

        report.say("⚠ something is off")
        report.say("→ see: carter install --help")
        report.say("  a detail, shown with -v only")
        assert capsys.readouterr().err.splitlines() == [
            "! something is off",
            "  → see: carter install --help",
        ]


def test_no_message_the_guard_code_prints_embeds_a_newline() -> None:
    """``ui._visible`` writes a newline out as ``\\n`` (a file name must not fake a line), so a
    message is one line and a command goes on its own ``→`` line. Scans the call sites."""
    import ast

    import carter

    root = Path(carter.__file__).parent
    printers = {"warn", "fail", "ok", "info", "detail", "next", "fix"}
    found = []
    for path in [*(root / "guard").glob("*.py"), root / "cli.py"]:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            prints = (isinstance(fn, ast.Name) and fn.id == "echo") or (
                isinstance(fn, ast.Attribute)
                and fn.attr in printers
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "ui"
            )
            if prints and any(
                isinstance(part, ast.Constant)
                and isinstance(part.value, str)
                and "\n" in part.value
                for arg in node.args
                for part in ast.walk(arg)
            ):
                found.append(f"{path.name}:{node.lineno}")
    assert found == []


class TestTheHelpHasTheLine:
    """The warnings only point at help, so the help the pointers name must hold the snippet."""

    SNIPPET = ("[include]", "path = ~/.carter/gitconfig")

    @pytest.mark.parametrize("see", ["SEE_INSTALL", "SEE_UNINSTALL"])
    def test_the_pointer_names_a_command_whose_help_shows_the_snippet(self, see: str) -> None:
        from carter.guard import gitconfig

        command = getattr(gitconfig, see).removeprefix("→ see: ").split()
        assert command[-1] == "--help"
        out = CliRunner().invoke(main, command[1:]).output
        assert all(part in out for part in self.SNIPPET)

    @pytest.mark.parametrize("command", [["guard", "install"], ["guard", "remove"]])
    def test_the_guard_commands_show_it_too(self, command: list[str]) -> None:
        out = CliRunner().invoke(main, [*command, "--help"]).output
        assert all(part in out for part in self.SNIPPET)
