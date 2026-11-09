"""Runs the TypeScript plugin tests (``tests/plugin/*.test.ts``) with plain ``node --test``.

no npm dependencies and no build step. Node >= 22.18 strips types by
default (Node 24 in CI), so ``node:test`` runs the ``.ts`` sources as they are. Skipped, with
the reason, when Node is missing or older. The CI job ``plugin`` runs the same command on
Linux and macOS; this wrapper keeps ``pytest`` honest on developer machines that have Node.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MIN_NODE = (22, 18)


def node_version(binary: str) -> tuple[int, ...]:
    out = subprocess.run([binary, "--version"], capture_output=True, text=True, timeout=30).stdout
    match = re.match(r"v(\d+)\.(\d+)", out.strip())
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


NODE = shutil.which("node")


def test_the_plugin_test_files_exist() -> None:
    assert sorted((REPO / "tests" / "plugin").glob("*.test.ts"))


@pytest.mark.skipif(NODE is None, reason="node is not installed")
def test_node_tests_pass() -> None:
    assert NODE is not None
    if node_version(NODE) < MIN_NODE:
        pytest.skip(f"node >= {MIN_NODE[0]}.{MIN_NODE[1]} is needed (built-in type stripping)")
    done = subprocess.run(
        [NODE, "--test", "tests/plugin/*.test.ts"],  # node expands the glob itself (>= 21)
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-1500:]
    assert re.search(r"^ℹ fail 0$", done.stdout, re.M), done.stdout[-1500:]
