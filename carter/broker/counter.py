"""The rejection counter.

Rejections, timeouts, aborts and dwell refusals are counted per **root session family** (the
plugin walks ``parentID`` to the root and sends its id), across repos. At ``MAX_REJECTIONS`` B
refuses (``E-B-REJECTED``) until a new root session starts or a human runs
``carter guard status --reset-b``. Nothing an agent can call resets it.

State: ``~/.carter/run/b-rejections.json`` (0600, in the 0700 ``run/`` directory), guarded by
``fcntl.flock`` on a sibling lock file. Entries older than ``TTL_S`` are dropped on write. A
file that cannot be read or does not parse **fails closed**: the broker refuses and says why; only
``reset`` (the human command) replaces it. Stdlib only.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

from carter.home import carter_home

MAX_REJECTIONS = 3
TTL_S = 24 * 3600
FILE = "b-rejections.json"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


class CounterError(Exception):
    """The counter file is unreadable or invalid (B fails closed)."""


def path(carter_dir: Path | None = None) -> Path:
    return (carter_dir or carter_home()) / "run" / FILE


def valid_id(value: str) -> bool:
    return bool(_ID.fullmatch(value))


@contextlib.contextmanager
def _locked(carter_dir: Path | None) -> Iterator[None]:
    target = path(carter_dir)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(target.with_name(f".{FILE}.lock"), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def _load(carter_dir: Path | None) -> dict[str, dict[str, int]]:
    try:
        text = path(carter_dir).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeDecodeError) as exc:
        raise CounterError(f"cannot read {FILE} ({type(exc).__name__})") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CounterError(f"{FILE} is not valid JSON") from exc
    ok = isinstance(data, dict) and all(
        isinstance(k, str)
        and isinstance(v, dict)
        and isinstance(v.get("n"), int)
        and not isinstance(v.get("n"), bool)
        and isinstance(v.get("last"), int)
        for k, v in data.items()
    )
    if not ok:
        raise CounterError(f"{FILE} has an unexpected shape")
    return data


def _save(data: dict[str, dict[str, int]], carter_dir: Path | None) -> None:
    target = path(carter_dir)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{FILE}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def count(root: str, carter_dir: Path | None = None) -> int:
    """Rejections recorded for ``root`` (0 when none or expired). Raises ``CounterError``."""
    with _locked(carter_dir):
        entry = _load(carter_dir).get(root)
    if not entry or time.time() - entry["last"] > TTL_S:
        return 0
    return entry["n"]


def stopped(root: str, carter_dir: Path | None = None) -> bool:
    return count(root, carter_dir) >= MAX_REJECTIONS


def add(root: str, carter_dir: Path | None = None, *, now: float | None = None) -> int:
    """Count one more rejection for ``root``; returns the new total."""
    if not valid_id(root):
        raise CounterError("the root session id is not a plain identifier")
    stamp = int(now if now is not None else time.time())
    with _locked(carter_dir):
        data = {k: v for k, v in _load(carter_dir).items() if stamp - v["last"] <= TTL_S}
        entry = data.get(root, {"n": 0, "last": stamp})
        data[root] = {"n": entry["n"] + 1, "last": stamp}
        _save(data, carter_dir)
    return data[root]["n"]


def reset(carter_dir: Path | None = None) -> int:
    """The human reset: forget every family, replacing even a corrupt file. Returns how many."""
    with _locked(carter_dir):
        try:
            cleared = len(_load(carter_dir))
        except CounterError:
            cleared = 0
        _save({}, carter_dir)
    return cleared


def summary(carter_dir: Path | None = None) -> tuple[int, int]:
    """``(families recorded, families stopped)`` for ``check --host`` (counts only)."""
    with _locked(carter_dir):
        data = _load(carter_dir)
    live = [v for v in data.values() if time.time() - v["last"] <= TTL_S]
    return len(live), sum(1 for v in live if v["n"] >= MAX_REJECTIONS)
