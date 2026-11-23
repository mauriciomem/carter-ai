"""The output rule, enforced on the source: a message is short, so its text is short.

Every printed line targets ``ui.TARGET`` (60) columns and never passes ``ui.MAX`` (80). Messages are
built in too many ways to find them by call site (a constant printed later, an exception raised
through a helper, a ``%`` or ``.format()`` template, a local ``hint = ...``), so this scans **every
string literal** in ``carter/`` and applies the budget to the literal itself:

- a one-line literal (or an f-string, whose substituted parts are left out) may have at most
  ``STATIC_MAX`` characters, which leaves 8 columns for what is substituted (a path, a name);
- each line of a multi-line literal (an epilog, a block of fixed lines) may have at most
  ``ui.MAX``.

What is not a message is listed below with the reason: agent-facing text, files Carter writes,
shell scripts, data. Anything else that is over has to say less, point at the help
(``(see: carter push -v)``) and move the detail to ``-v``, an epilog or the docs.

The runtime side is ``tests/guard/test_output_width.py`` and the golden snapshots.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from carter import ui
from carter.identity.errors import registry
from carter.identity.policyset import SHORT_MAX, consent_groups

ROOT = Path(__file__).resolve().parents[1] / "carter"
STATIC_MAX = ui.MAX - 8  # the fixed part of a one-line message; 8 columns stay for the rest

# Directories and files whose strings are not lines for the person at the terminal.
EXEMPT_DIRS = {
    "gate/": "the command gate speaks to agents",
    "broker/": "carter_push refusals are read by an agent and mirrored in the skills",
    "ops/": "carter ops: the agent's own tool",
    "plugin/": "TypeScript, not Python text",
}
EXEMPT_FILES = {
    "ci/review.py": "the review prompt for the model, and CI step output",
    "ci/template.py": "the GitHub workflow file Carter writes",
    "guard/hooks.py": "the git hook script and the messages it prints to an agent",
    "identity/isolation.py": "shell commands of the isolation block",
    "install/components.py": "agent rules Carter writes into AGENTS.md and agent files",
    "state.py": "templates of the .carter/ state files",
}
# (file, start of the literal) over the budget that stay, each with the reason.
EXCEPTIONS = {
    ("aplus/push.py", "Run `carter push` yourself"): (
        "one sentence mirrored verbatim in the skills and templates (parity tests); "
        "the terminal shows it only through E-HUMAN-TERMINAL's own short fix"
    ),
    ("aplus/repocfg.py", "applypatch-msg"): "the list of git hook names",
    ("cli.py", "Agents (the `agents:`"): "help prose: click re-wraps it to the terminal width",
    ("cli.py", "A workspace can only tighten"): "help prose: click re-wraps it",
    ("identity/writer.py", "# Carter settings (schema 2)"): "header written to config.toml",
    ("scaffold.py", "Strictness policy is"): "text of the agent files, not the terminal",
    ("scaffold.py", "the workspace `docs_language`"): "text of the agent files",
    ("guard/gitconfig.py", "# Managed by Carter"): "header written to ~/.carter/gitconfig",
    ("guard/report.py", "MISSING|CHANGED"): "a regular expression",
    ("identity_show.py", "author is you, committer"): "`identity show` line, rewritten by plan R8",
    ("identity_show.py", "author, committer and signer"): "`identity show` line (plan R8)",
}
# Registry messages the person at the terminal never sees: they are for agents (plugin, hooks,
# the carter_push tool) and are mirrored in the skills' error table.
AGENT_FACING = {
    "E-SIGN-LOCKED", "E-SIGN-NOAGENT", "E-SHIM-REFUSED", "E-ISOLATION-MISSING",
    "E-SIGN-UNAVAILABLE", "E-SELFTEST", "E-GUARD-NOIDENT", "E-GUARD-SIGNCFG",
    "E-GUARD-NOSIGN", "E-GUARD-UNSIGNED", "E-GATE", "E-GATE-FAIL", "E-GH-READONLY",
    "E-B-DWELL", "E-B-POLLUTED", "E-B-REPOCFG", "E-B-NOAGENT", "E-B-DEFAULT",
    "E-B-REJECTED", "E-B-UNSIGNED", "E-TIER-CAPPED", "E-CI-REVIEW", "E-B-ARGS",
    "E-B-HEADLESS", "E-PUSH-GUARD", "E-PUSH-ISOLATED", "E-POLICY", "E-SSH-ISOLATED",
}  # fmt: skip


def _docstrings(tree: ast.Module) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def literals() -> list[tuple[str, int, str]]:
    """``(file, line number, text)`` of every string literal in ``carter/``: an f-string counts
    once, as its fixed parts joined, and a docstring not at all."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(tuple(EXEMPT_DIRS)) or rel in EXEMPT_FILES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip, parts = _docstrings(tree), set()
        for node in ast.walk(tree):
            if isinstance(node, ast.JoinedStr):
                parts |= {id(v) for v in node.values}
                text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
                found.append((rel, node.lineno, text))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip | parts
            ):
                found.append((rel, node.lineno, node.value))
    return found


def over_budget() -> list[tuple[str, int, int, str]]:
    over = []
    for rel, lineno, text in literals():
        rows = text.split("\n")
        limit = ui.MAX if len(rows) > 1 else STATIC_MAX
        for row in rows:
            row = row.rstrip()
            if len(row) > limit and not any(
                rel == f and row.strip().startswith(start) for f, start in EXCEPTIONS
            ):
                over.append((rel, lineno, len(row), row.strip()[:60]))
    return over


def test_the_scan_sees_the_text_of_the_cli() -> None:
    files = {f for f, _, _ in literals()}
    assert {"aplus/push.py", "guard/engine.py", "dotfiles_help.py", "access_cli.py"} <= files
    assert len(literals()) > 3000
    assert not files & set(EXEMPT_FILES)


def test_no_string_in_the_cli_is_longer_than_the_budget_allows() -> None:
    over = [f"{f}:{n} ({size}) {text}..." for f, n, size, text in over_budget()]
    assert not over, (
        f"over {STATIC_MAX} columns (one line) or {ui.MAX} (a line of a block): say less and "
        "point at the help (see: carter <cmd> --help); details go to -v, an epilog or the docs\n"
        + "\n".join(over)
    )


def test_every_exception_and_exemption_still_applies() -> None:
    over = {(f, t) for f, _, _, t in over_budget()}  # nothing is over: the listed ones are skipped
    assert not over
    seen = {(f, t.strip()) for f, _, t in literals()}
    for file, start in EXCEPTIONS:
        assert any(f == file and t.startswith(start) for f, t in seen), (file, start)
    for name in EXEMPT_FILES:
        assert (ROOT / name).is_file(), name


def test_a_message_that_reaches_ui_has_no_newline_in_it() -> None:
    bad = []
    for path in sorted(ROOT.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            func = node.func if isinstance(node, ast.Call) else None
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in {"ok", "warn", "detail"} and isinstance(node, ast.Call):
                for arg in node.args:
                    if isinstance(arg, ast.Constant) and "\n" in str(arg.value):
                        bad.append(f"{path.name}:{arg.lineno}")
    assert not bad, bad


def test_the_registry_messages_a_person_can_see_fit_the_line() -> None:
    """The text of an error is the cause line: 80 columns with its placeholders left in. The
    agent-facing ones are listed above; their text is the contract with the skills."""
    long = [
        f"{e.code} ({len(e.message)})"
        for e in registry().values()
        if e.code not in AGENT_FACING and len(e.message) > ui.MAX
    ]
    assert not long, long
    assert {c for c in AGENT_FACING if c not in registry()} == set()
    fixes = [f"{e.code}: {e.fix}" for e in registry().values() if len(e.fix) > ui.MAX - 6]
    assert not fixes, fixes


def test_the_data_file_texts_fit_too() -> None:
    data = json.loads((ROOT / "identity" / "g2_rules.json").read_text(encoding="utf-8"))
    for group in data["consent_groups"]:
        for row in group.get("explain", []):
            assert len(row) <= ui.MAX, (group["id"], row)


@pytest.mark.parametrize("group", consent_groups(), ids=lambda g: g.id)
def test_a_consent_group_has_a_short_row_for_the_install_question(group) -> None:
    assert group.short and len(group.short) <= SHORT_MAX and "\n" not in group.short
    assert group.short != group.effect[:SHORT_MAX], "write the short text, do not cut the long one"


def test_the_hooks_row_says_it_covers_every_repo() -> None:
    hooks = next(g for g in consent_groups() if g.id == "hooks")
    assert "all repos" in hooks.short


def test_the_target_and_the_hard_max_are_the_decided_ones() -> None:
    assert (ui.TARGET, ui.MAX) == (60, 80)
