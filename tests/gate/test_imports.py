"""The gate stays stdlib-only and cheap to import (freeze G1; plan 004 steps 20-21)."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "carter" / "gate"
MODULES = sorted(PACKAGE.glob("*.py"))
FORBIDDEN_ROOTS = {"click", "jinja2", "yaml"}
FORBIDDEN_CARTER = {
    "carter.cli",
    "carter.config",
    "carter.identity",
    "carter.harness",
    "carter.gate_cli",
}
FORBIDDEN_STDLIB = {"importlib.resources", "importlib.metadata", "pathlib", "dataclasses", "typing"}


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    guarded = {
        id(n)
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.dump(node.test)
        for n in ast.walk(node)
    }
    for node in ast.walk(tree):
        if id(node) in guarded:
            continue
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
    return found


@pytest.mark.parametrize("module", MODULES, ids=lambda p: p.name)
class TestSources:
    def test_only_the_stdlib_and_the_gate_itself(self, module: Path) -> None:
        for name in imports(module):
            root = name.split(".")[0]
            assert root not in FORBIDDEN_ROOTS, name
            assert name not in FORBIDDEN_CARTER and not name.startswith("carter.identity"), name
            assert (
                root in sys.stdlib_module_names
                or name == "carter.gate"
                or name.startswith("carter.gate.")
            ), name

    def test_none_of_the_expensive_stdlib_modules(self, module: Path) -> None:
        assert not imports(module) & FORBIDDEN_STDLIB, module.name

    def test_modules_stay_small(self, module: Path) -> None:
        assert len(module.read_text(encoding="utf-8").splitlines()) <= 330


def run_python(code: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
    return subprocess.run(
        [sys.executable, "-I", "-c", code],
        capture_output=True,
        text=True,
        env=env,
        check=True,
        timeout=60,
    ).stdout.strip()


class TestRuntime:
    WATCHED = (
        "carter.identity",
        "importlib.metadata",
        "importlib.resources",
        "pathlib",
        "dataclasses",
        "typing",
        "click",
        "jinja2",
        "yaml",
        "carter.cli",
        "carter.config",
        "subprocess",
    )

    def loaded(self, body: str) -> list[str]:
        show = f"print(json.dumps([m for m in {self.WATCHED!r} if m in sys.modules]))"
        code = f"import sys, json; {body}; {show}"
        return json.loads(run_python(code))

    def test_a_check_loads_none_of_the_expensive_modules(self) -> None:
        cmds = [
            "git status",
            "git push",
            "echo $(ls)",
            "cat ~/.ssh/id",
            "sh -c 'ls'",
            "git commit -m x",
        ]
        body = "from carter import gate; " + "; ".join(f"gate.check({c!r})" for c in cmds)
        assert self.loaded(body) == []

    def test_the_entry_point_loads_none_of_them_either(self) -> None:
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
        code = (
            "import sys, json, io; sys.stdin = io.TextIOWrapper(io.BytesIO(b'git status')); "
            "from carter.gate import __main__ as m; m.main(['--json']); "
            f"print(json.dumps([x for x in {self.WATCHED!r} if x in sys.modules]))"
        )
        out = subprocess.run(
            [sys.executable, "-I", "-c", code], capture_output=True, text=True, env=env, timeout=60
        ).stdout
        assert json.loads(out.splitlines()[-1]) == []

    def test_subprocess_is_imported_only_for_a_non_builtin_git_subcommand(self) -> None:
        assert self.loaded("from carter import gate; gate.check('git lfs ls-files', '/tmp')") == [
            "subprocess"
        ]

    def test_importtime_shows_only_the_stdlib_and_carter(self) -> None:
        env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"]}
        done = subprocess.run(
            [sys.executable, "-I", "-X", "importtime", "-m", "carter.gate", "--json"],
            input=b"git status",
            capture_output=True,
            env=env,
            timeout=60,
        )
        names = {
            line.split("|")[-1].strip() for line in done.stderr.decode().splitlines() if "|" in line
        }
        names.discard("imported package")
        extra = {
            n
            for n in names
            if n.split(".")[0] not in sys.stdlib_module_names
            and not n.startswith(("carter", "_"))
            and n not in ("site", "sitecustomize", "usercustomize", "encodings")
        }
        assert extra == set()
        assert "carter.identity" not in names and "importlib.metadata" not in names


class TestLazyPackages:
    def test_importing_carter_is_free_and_the_version_still_works(self) -> None:
        assert "importlib.metadata" not in json.loads(
            run_python("import sys, json, carter; print(json.dumps(list(sys.modules)))")
        )
        assert run_python("import carter; print(carter.__version__)")
        assert run_python("from carter import __version__; print(__version__)")

    def test_importing_a_carter_identity_submodule_does_not_load_the_package_contents(self) -> None:
        mods = json.loads(
            run_python(
                "import sys, json, carter.identity.rules; print(json.dumps(list(sys.modules)))"
            )
        )
        assert not {
            "carter.identity.config",
            "carter.identity.errors",
        } & set(mods)

    def test_the_public_names_still_resolve_and_resolve_is_the_function(self) -> None:
        out = run_python(
            "import carter.identity.migrate, carter.identity.resolve as m; "
            "import carter.identity as p; "
            "from carter.identity import resolve, IdentityConfig, load_identity, ConfigError; "
            "print(callable(resolve) and not hasattr(resolve, 'configured_tier'), "
            "IdentityConfig.__name__, p.resolve is resolve)"
        )
        assert out == "True IdentityConfig True"

    def test_all_matches_the_lazy_table(self) -> None:
        from carter import identity

        assert sorted(identity.__all__) == sorted(identity._SOURCES)
        with pytest.raises(AttributeError):
            identity.nonsense  # noqa: B018
