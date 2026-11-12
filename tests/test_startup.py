"""Starting the CLI must stay light: importing ``carter.cli`` loads none of the heavy modules.

Deterministic on purpose (no millisecond budget in the default suite: it is flaky on CI);
the timings are measured under ``CARTER_PERF=1`` like the gate budget.
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time

import pytest

HEAVY = ("jinja2", "yaml", "urllib.request", "rich")

# Imports the CLI (and runs `main(args)` when given) in a fresh interpreter, then prints which
# heavy modules got loaded (last line).
CHILD = """
import contextlib, json, sys
from carter.cli import main
args = json.loads(sys.argv[1])
if args is not None:
    with contextlib.suppress(SystemExit):
        main(args=args, standalone_mode=False)
print(json.dumps([m for m in {heavy!r} if m in sys.modules]))
"""


def _loaded_after(argv: list[str] | None) -> list[str]:
    code = CHILD.format(heavy=HEAVY)
    done = subprocess.run(
        [sys.executable, "-c", code, json.dumps(argv)], capture_output=True, text=True, check=True
    )
    return json.loads(done.stdout.splitlines()[-1])  # type: ignore[no-any-return]


def test_importing_the_cli_loads_none_of_the_heavy_modules() -> None:
    assert _loaded_after(None) == []


@pytest.mark.parametrize("argv", [["--help"], ["--version"], ["gate", "--help"]])
def test_help_and_version_load_none_of_the_heavy_modules(argv: list[str]) -> None:
    assert _loaded_after(argv) == []


# `carter --help` is ~35 ms locally (target 40); the CI assertion keeps a 2x margin for shared
# runners. Opt-in like the gate budget: CARTER_PERF=1 (CARTER_GATE_PYTHON = the `uv tool` python).
HELP_BUDGET_MS = 80.0


@pytest.mark.skipif(
    os.environ.get("CARTER_PERF") != "1", reason="perf run is opt-in: CARTER_PERF=1"
)
def test_perf_help_median_is_under_the_budget() -> None:
    python = os.environ.get("CARTER_GATE_PYTHON", sys.executable)
    argv = [python, "-m", "carter.cli", "--help"]
    for _ in range(2):  # warm the file cache
        subprocess.run(argv, capture_output=True, check=True)
    samples = []
    for _ in range(20):
        start = time.perf_counter()
        subprocess.run(argv, capture_output=True, check=True)
        samples.append((time.perf_counter() - start) * 1000)
    median = statistics.median(samples)
    print(f"carter --help: n={len(samples)} p50={median:.1f} ms")
    assert median < HELP_BUDGET_MS
