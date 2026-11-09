"""``carter.identity`` stays stdlib-only so later slices (gate, plugin entry) can import
it without pulling in click, jinja2 or yaml."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "carter" / "identity"
ALLOWED_CARTER = {"carter.home"}  # itself stdlib-only
MODULES = sorted(PACKAGE.glob("*.py"))


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


def test_package_is_not_empty() -> None:
    assert {"config.py", "resolve.py", "schema.py", "errors.py"} <= {p.name for p in MODULES}


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_imports_are_stdlib_or_the_package_itself(module: Path) -> None:
    bad = []
    for name in _imports(module):
        root = name.split(".")[0]
        if root in sys.stdlib_module_names or name in ALLOWED_CARTER:
            continue
        if name == "carter.identity" or name.startswith("carter.identity."):
            continue
        bad.append(name)
    assert bad == []


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
def test_modules_stay_small(module: Path) -> None:
    # resolve.py: 250 since (the mode adds 17 lines); everything else stays at 220
    limit = 250 if module.name == "resolve.py" else 220
    assert len(module.read_text(encoding="utf-8").splitlines()) <= limit
