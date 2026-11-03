"""Gate start-up budget (RFC-0007 App C.4.2): p95 < 100 ms per command, start-up included.

Skeleton from plan 004 step 7 (spike F); step 21 fills the corpus run. What the spike measured
(Linux, uv tool venv, Python 3.14.8; numbers in ``notes.md``):

- a bare ``python -I`` is ~12 ms; the stdlib imports the gate needs add ~4 ms (``subprocess`` alone
  6 ms, so import it lazily);
- ``python -m carter.gate`` pays for ``carter/__init__.py`` first. Today that file runs
  ``importlib.metadata.version()`` at import, which costs ~25 ms warm and ~45 ms cold; and
  ``carter.identity/__init__`` pulls ``config``, ``errors``, ``importlib.resources`` (+25 ms).
  Together: p95 42 ms warm / 80-96 ms cold, against 16 / 33 ms when both are lazy.

Step 21 made both imports lazy; ``TestStartupFloor`` pins it (``import carter`` must not load
``importlib.metadata``, and the gate must not load ``carter.identity``, ``importlib.resources``,
``importlib.metadata``, ``pathlib`` or ``subprocess``).

The corpus run is opt-in (``CARTER_PERF=1``) and skips until ``tests/data/gate_corpus.yaml`` exists
(step 17). ``CARTER_GATE_PYTHON`` points it at the ``uv tool`` interpreter (CI does this).
"""

from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

BUDGET_MS = 100.0
RUNS = int(os.environ.get("CARTER_PERF_RUNS", "200"))
CORPUS = Path(__file__).resolve().parent.parent / "data" / "gate_corpus.yaml"


def percentile(samples: Sequence[float], p: float) -> float:
    """Linear-interpolated percentile (the ``quantiles(method="inclusive")`` convention)."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = (len(ordered) - 1) * p / 100
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def measure(
    argv: Sequence[str],
    payloads: Sequence[bytes],
    runs: int,
    env: dict[str, str],
    before: Callable[[], None] | None = None,
) -> list[float]:
    """Wall time in ms of ``runs`` spawns of ``argv``, cycling through ``payloads`` on stdin.

    Exit codes 0 (allow) and 1 (deny) are both normal answers; ``before`` runs untimed."""
    samples: list[float] = []
    for i in range(runs):
        if before:
            before()
        start = time.perf_counter()
        done = subprocess.run(argv, input=payloads[i % len(payloads)], env=env, capture_output=True)
        samples.append((time.perf_counter() - start) * 1000)
        assert done.returncode in (0, 1), done.stderr[-300:]
    return samples


def drop_file_cache(python: str) -> Callable[[], None]:
    """``posix_fadvise(DONTNEED)`` over the interpreter's tree and the stdlib: a cold-cache run
    without root (Linux; elsewhere the cold figure is simply not measured)."""
    roots = {
        os.path.dirname(os.path.dirname(os.path.realpath(python))),
        os.path.dirname(os.__file__),
    }
    roots.add(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def drop() -> None:
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for name in files:
                    try:
                        fd = os.open(os.path.join(dirpath, name), os.O_RDONLY)
                        os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
                        os.close(fd)
                    except OSError:
                        pass

    return drop


class TestMeasurementHelpers:
    def test_percentile_interpolates(self) -> None:
        assert percentile([1, 2, 3, 4, 5], 50) == 3
        assert percentile([10, 20], 95) == pytest.approx(19.5)
        assert percentile([7], 95) == 7

    def test_percentile_of_nothing_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            percentile([], 95)

    def test_measure_times_real_spawns(self) -> None:
        env = {"PATH": os.environ["PATH"]}
        samples = measure([sys.executable, "-I", "-c", "pass"], [b"{}"], 3, env)
        assert len(samples) == 3 and all(0 < s < 5000 for s in samples)
        assert statistics.median(samples) == percentile(samples, 50)


WATCHED = ("importlib.metadata", "carter.identity", "subprocess")


def _watched_modules_after(statement: str) -> set[str]:
    """Which of ``WATCHED`` are in ``sys.modules`` after ``statement`` in a fresh ``python -I``."""
    show = f"print(json.dumps([m for m in {WATCHED!r} if m in sys.modules]))"
    code = f"import json, sys; {statement}; {show}"
    out = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True, timeout=60
    ).stdout
    return set(json.loads(out))


class TestStartupFloor:
    """Design requirements for step 21 (see the module docstring)."""

    def test_importing_carter_does_not_import_importlib_metadata(self) -> None:
        assert "importlib.metadata" not in _watched_modules_after("import carter")

    def test_the_version_is_still_available(self) -> None:
        out = subprocess.run(
            [sys.executable, "-I", "-c", "import carter; print(carter.__version__)"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert out  # eager today, lazy (PEP 562 module __getattr__) after step 21: same value


def corpus_payloads() -> list[bytes]:
    """Every corpus command that needs no fixture, as the plugin would send it (UTF-8 stdin)."""
    import yaml  # noqa: PLC0415 - test-only

    cases = yaml.safe_load(CORPUS.read_text(encoding="utf-8"))["cases"]
    return [
        c["command"].encode() for c in cases if "setup" not in c and "{tmp}" not in c["command"]
    ]


@pytest.mark.skipif(
    os.environ.get("CARTER_PERF") != "1", reason="perf run is opt-in: CARTER_PERF=1"
)
@pytest.mark.parametrize("cold", [False, True], ids=["warm", "cold"])
def test_gate_p95_is_under_the_budget_including_interpreter_startup(cold: bool) -> None:
    """RFC C.4.2: p95 < 100 ms per command over the whole corpus, interpreter start-up included.

    ``CARTER_GATE_PYTHON`` points at a ``uv tool`` interpreter (CI does this); the default is the
    test interpreter. Prints p50/p95/max for the PR description."""
    if cold and not hasattr(os, "posix_fadvise"):
        pytest.skip("cold-cache runs need posix_fadvise (Linux)")
    python = os.environ.get("CARTER_GATE_PYTHON", sys.executable)
    payloads = corpus_payloads()
    env = {"PATH": os.environ["PATH"], "HOME": os.environ.get("HOME", "/tmp")}
    runs = 40 if cold else max(RUNS, len(payloads))
    before = drop_file_cache(python) if cold else None
    samples = measure([python, "-I", "-m", "carter.gate", "--json"], payloads, runs, env, before)
    p50, p95 = statistics.median(samples), percentile(samples, 95)
    label = "cold" if cold else "warm"
    print(f"gate {label}: n={len(samples)} p50={p50:.1f} p95={p95:.1f} max={max(samples):.1f} ms")
    assert p95 < BUDGET_MS
