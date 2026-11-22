"""The output rule, enforced on the source: a message is short, so its fixed text is short.

Every printed line targets ``ui.TARGET`` (60) columns and never passes ``ui.MAX`` (80). A message
is a call to ``ui.*``, ``click.echo`` / ``confirm`` / ``prompt``, the install log helpers, or the
construction of an error a command prints. Its text is checked here where it is written: the fixed
part of one line (the parts around ``{...}`` in an f-string) may not pass ``STATIC_MAX``, which
leaves the rest of the 80 columns for what is substituted (a path, a name, a count). A message
that needs more says less and points at the help (``(see: carter push -v)``); the detail goes to
``-v``, a ``--help`` epilog or the docs.

The runtime side is ``tests/guard/test_output_width.py`` and the golden snapshots.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from carter import ui
from carter.identity.policyset import SHORT_MAX, consent_groups

ROOT = Path(__file__).resolve().parents[1] / "carter"
STATIC_MAX = ui.MAX - 8  # the fixed part of a line; 8 columns stay for the substituted parts

# What prints (or is printed by the command that catches it).
PRINTS = {
    "ok", "warn", "fail", "info", "next", "fix", "detail", "line", "summary", "header",
    "section", "echo", "secho", "confirm", "prompt", "say", "log_ok", "log_warn", "log_err",
    "log_skip", "log_debug", "Row", "Item",
}  # fmt: skip
ERRORS = {
    "ClickException", "UsageError", "BadParameter", "IdentityError", "ConfigError",
    "PolicyWriteError", "GitError", "PluginInstallError", "InstallError", "CommitRefused",
    "PrerequisiteError", "UnmodelledKeysError", "WriterError", "GuardAbort", "DebugConfigError",
}  # fmt: skip
# Whole modules whose every string is a line of `carter check --host` (areas, texts and fixes).
CHECK_MODULES = (
    "hostcheck.py", "hostcheck_g2.py", "hostcheck_id.py", "hostcheck_broker.py", "human_items.py",
)  # fmt: skip

# Not output for the person at the terminal: text for agents and CI, or help the reader opens.
EXEMPT_DIRS = (
    "gate/",  # the command gate speaks to agents
    "broker/",  # carter_push refusals are read by an agent, mirrored in the skills
    "ops/",  # carter ops: the agent's own tool
    "plugin/",
)
# (file, text) pairs over STATIC_MAX that stay, each with the reason.
EXCEPTIONS: dict[tuple[str, str], str] = {}


def _static(node: ast.AST) -> str | None:
    """The fixed text of a string expression, ``None`` when it is not one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value for v in node.values if isinstance(v, ast.Constant))
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _static(node.left), _static(node.right)
        return None if left is None or right is None else left + right
    return None


def _name(func: ast.expr) -> str:
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _texts(call: ast.Call) -> list[tuple[int, str]]:
    found = []
    for arg in [*call.args, *(k.value for k in call.keywords if k.arg != "default")]:
        nodes = arg.elts if isinstance(arg, ast.Tuple | ast.List) else [arg]
        for node in nodes:
            if (text := _static(node)) is not None:
                found.append((node.lineno, text))
    return found


def _docstrings(tree: ast.Module) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.ClassDef) and body:
            first = body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def message_lines() -> list[tuple[str, int, str]]:
    """``(file, line number, one line of fixed text)`` for every message in ``carter/``."""
    found = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(EXEMPT_DIRS):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if rel in CHECK_MODULES:
            skip = _docstrings(tree)
            nodes = [
                (n.lineno, n.value)
                for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
            ]
        else:
            nodes = [
                text
                for n in ast.walk(tree)
                if isinstance(n, ast.Call) and _name(n.func) in PRINTS | ERRORS
                for text in _texts(n)
            ]
        for lineno, text in nodes:
            found += [(rel, lineno, row.strip()) for row in text.split("\n") if row.strip()]
    return found


def test_the_scan_finds_the_messages() -> None:
    lines = message_lines()
    assert len(lines) > 500 and any(f == "aplus/push.py" for f, _, _ in lines)


def test_no_message_has_more_fixed_text_than_the_budget_allows() -> None:
    over = [
        f"{file}:{lineno} ({len(text)}) {text[:60]}..."
        for file, lineno, text in message_lines()
        if len(text) > STATIC_MAX and (file, text) not in EXCEPTIONS
    ]
    assert not over, (
        f"fixed text over {STATIC_MAX} columns: say less and point at the help "
        "(see: carter <cmd> --help); details go to -v, an epilog or the docs\n" + "\n".join(over)
    )


def test_every_exception_still_applies() -> None:
    present = {(f, t) for f, _, t in message_lines() if len(t) > STATIC_MAX}
    assert set(EXCEPTIONS) <= present, "an exception no longer needed: remove it"


def test_a_message_that_reaches_ui_has_no_newline_in_it() -> None:
    bad = []
    for path in sorted(ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _name(node.func) in {"ok", "warn", "fail", "detail"}:
                bad += [
                    f"{path.name}:{ln}"
                    for ln, text in _texts(node)
                    if "\n" in text and _name(node.func) != "fail"
                ]
    assert not bad, bad


@pytest.mark.parametrize("group", consent_groups(), ids=lambda g: g.id)
def test_a_consent_group_has_a_short_row_for_the_install_question(group) -> None:
    assert group.short and len(group.short) <= SHORT_MAX and "\n" not in group.short
    assert group.short != group.effect[:SHORT_MAX], "write the short text, do not cut the long one"


def test_the_target_and_the_hard_max_are_the_decided_ones() -> None:
    assert (ui.TARGET, ui.MAX) == (60, 80)
