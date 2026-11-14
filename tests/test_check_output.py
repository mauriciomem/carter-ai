"""What ``carter check`` prints: every red line has its fix, the run ends in a summary line, and
the model advisory is one line (the roles behind it only with ``-v``)."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from carter.cli import main
from carter.harness import UNAVAILABLE_FIX, HarnessResult

ADVISORY = (
    "Pinned models: anthropic/claude-opus-5-5, anthropic/claude-sonnet-5-5. "
    "Carter cannot verify your provider has them."
)


@pytest.fixture
def ws(tmp_path: Path) -> Path:
    target = tmp_path / "ws"
    target.mkdir()
    assert CliRunner().invoke(main, ["init", str(target), "--no-git-state"]).exit_code == 0
    return target


def _check(ws: Path, *args: str) -> Result:
    return CliRunner().invoke(main, [*args, "check", str(ws), "--no-harness"])


def test_a_clean_workspace_prints_the_one_line_advisory_and_ok(ws: Path) -> None:
    result = _check(ws)
    assert result.exit_code == 0
    assert result.stdout.splitlines() == [ADVISORY, "✓ Workspace OK  8 agents"]
    assert result.stderr == ""


def test_verbose_lists_the_role_behind_each_pin(ws: Path) -> None:
    lines = _check(ws, "-v").stdout.splitlines()
    assert lines[0] == ADVISORY and "  maestro: anthropic/claude-opus-5-5" in lines


def test_a_missing_agent_names_the_fix_and_ends_with_a_summary(ws: Path) -> None:
    next((ws / ".opencode" / "agents").glob("carter-pm*.md")).unlink()
    result = _check(ws)
    assert result.exit_code == 1
    assert result.stdout == ""  # no advisory or "OK" on a failed check
    assert result.stderr.splitlines() == [
        "✗ Missing agent file: .opencode/agents/carter-pm-local.md",
        "→ run `carter update`",
        "✗ workspace: 1 problem",
    ]


def test_a_missing_knowledge_file_points_to_init_and_problems_are_counted(ws: Path) -> None:
    (ws / ".carter" / "knowledge" / "gotchas.md").unlink()
    (ws / "AGENTS.md").unlink()
    err = _check(ws).stderr.splitlines()
    assert "→ run `carter init`" in err
    assert err[-1] == "✗ workspace: 2 problems"


def test_a_warning_does_not_change_the_exit_code(ws: Path) -> None:
    path = ws / ".carter" / "carter.yaml"
    path.write_text(path.read_text() + "identity:\n  git_account: someone\n")
    result = _check(ws)
    assert result.exit_code == 0
    assert result.stdout.splitlines()[-1] == "✓ Workspace OK  8 agents"
    assert "git_account" in result.stderr


def _with_harness(monkeypatch: pytest.MonkeyPatch, result: HarnessResult) -> None:
    monkeypatch.setattr("carter.harness.validate_agents", lambda *_a, **_k: result)


def test_an_opencode_that_does_not_answer_gets_its_own_fix_not_update(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    timed_out = "`opencode debug agents` timed out after 30s"
    _with_harness(monkeypatch, HarnessResult("fail", [timed_out], fix=UNAVAILABLE_FIX))
    result = CliRunner().invoke(main, ["check", str(ws)])
    assert result.exit_code == 1
    assert result.stderr.splitlines() == [
        f"✗ {timed_out}",
        f"→ {UNAVAILABLE_FIX}",
        "✗ workspace: 1 problem",
    ]


def test_harness_lines_that_name_their_own_command_get_no_second_fix(
    ws: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lines = ["a: not loaded. Run `carter update` to re-render it.", "b: different model."]
    _with_harness(monkeypatch, HarnessResult("fail", lines))
    err = CliRunner().invoke(main, ["check", str(ws)]).stderr.splitlines()
    assert err == [f"✗ {lines[0]}", f"✗ {lines[1]}", "✗ workspace: 2 problems"]
