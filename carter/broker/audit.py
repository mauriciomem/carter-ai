"""The audit store (RFC-0007 App C.5 "Audit", freeze B15): one directory, two files.

``~/.carter/state/audit/`` (0700) holds ``b.jsonl`` (one line per B decision) and the ``ops``
``audit.log`` (moved here from ``~/.carter``). Files are 0600 and append-only (``O_APPEND``,
``O_NOFOLLOW``). A B line has **exactly** the fields in ``FIELDS`` and nothing else: never env,
credentialed URLs, tokens, titles or commit messages. Every value is cut to a printable,
bounded string, so a model-chosen branch name cannot forge a second line.

``b.jsonl`` rotates at ``ROTATE_BYTES`` (``b.jsonl.1`` ... ``.3``). The path is resolved when
called, never at import, so tests patch ``HOME`` first. The ops log is migrated once: an
existing ``~/.carter/audit.log`` is moved (``os.replace``) into the directory on first use.
Stdlib only.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from carter.home import carter_home

B_LOG = "b.jsonl"
OPS_LOG = "audit.log"
ROTATE_BYTES = 5 * 1024 * 1024
ROTATE_KEEP = 3
MAX_VALUE = 200
FIELDS = (
    "ts", "root", "session", "agent", "owner_repo", "branch", "range", "commits", "verb",
    "decision", "code", "dwell_ms",
)  # fmt: skip
DECISIONS = ("approved", "rejected", "corrected", "timeout", "aborted", "dwell", "refused", "error")
_INT_FIELDS = ("commits", "dwell_ms")
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


class AuditError(Exception):
    """The audit line could not be written."""


def audit_dir(carter_dir: Path | None = None) -> Path:
    return (carter_dir or carter_home()) / "state" / "audit"


def ops_log_path(carter_dir: Path | None = None) -> Path:
    return audit_dir(carter_dir) / OPS_LOG


def _ensure_dir(carter_dir: Path | None) -> Path:
    base = carter_dir or carter_home()
    for directory in (base, base / "state", audit_dir(carter_dir)):
        directory.mkdir(exist_ok=True, mode=0o700)
    audit_dir(carter_dir).chmod(0o700)
    return audit_dir(carter_dir)


def migrate_ops_log(carter_dir: Path | None = None) -> bool:
    """Move ``~/.carter/audit.log`` into the directory once; keep the new file if both exist."""
    old = (carter_dir or carter_home()) / OPS_LOG
    new = ops_log_path(carter_dir)
    try:
        if not old.is_file() or old.is_symlink() or new.exists():
            return False
        _ensure_dir(carter_dir)
        os.replace(old, new)
        new.chmod(0o600)
    except OSError:
        return False
    return True


def _clean(value: Any) -> Any:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _CONTROL.sub("?", value)[:MAX_VALUE]
    return None


def sanitize(event: dict[str, Any]) -> dict[str, Any]:
    """The whitelisted, bounded form of ``event`` (unknown keys dropped)."""
    out: dict[str, Any] = {}
    for name in FIELDS:
        value = _clean(event.get(name))
        if name in _INT_FIELDS:
            out[name] = value if isinstance(value, int) else None
        else:
            out[name] = value if isinstance(value, str) else ""
    return out


def _rotate(path: Path) -> None:
    for i in range(ROTATE_KEEP, 0, -1):
        source = path if i == 1 else path.with_name(f"{path.name}.{i - 1}")
        target = path.with_name(f"{path.name}.{i}")
        with contextlib.suppress(FileNotFoundError):
            os.replace(source, target)
    for stale in path.parent.glob(f"{path.name}.*"):
        if stale.suffix.lstrip(".").isdigit() and int(stale.suffix.lstrip(".")) > ROTATE_KEEP:
            stale.unlink(missing_ok=True)


def append_line(path: Path, line: str, *, rotate: bool) -> None:
    """Append one line to ``path`` (0600); rotate first when it is large."""
    lock = path.with_name(f".{path.name}.lock")
    try:
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    except OSError as exc:
        raise AuditError(f"cannot open the audit lock ({type(exc).__name__})") from exc
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if rotate:
            with contextlib.suppress(OSError):
                if path.stat().st_size >= ROTATE_BYTES:
                    _rotate(path)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            os.write(fd, (line + "\n").encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        raise AuditError(f"cannot write the audit file ({type(exc).__name__})") from exc
    finally:
        os.close(lock_fd)


def record(event: dict[str, Any], carter_dir: Path | None = None) -> None:
    """Write one B decision. Raises ``AuditError``; the caller decides whether that blocks."""
    if event.get("decision") not in DECISIONS:
        raise AuditError("unknown decision")
    directory = _ensure_dir(carter_dir)
    line = sanitize({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **event})
    append_line(directory / B_LOG, json.dumps(line, sort_keys=True, ensure_ascii=True), rotate=True)


def append_ops(entry: dict[str, Any], carter_dir: Path | None = None) -> None:
    """Append one ops entry (free-form JSON, as before) to the moved ``audit.log``."""
    migrate_ops_log(carter_dir)
    directory = _ensure_dir(carter_dir)
    append_line(directory / OPS_LOG, json.dumps(entry), rotate=False)


def read_b(carter_dir: Path | None = None, *, limit: int = 1000) -> list[dict[str, Any]]:
    """The last ``limit`` readable B lines; a corrupt line is skipped, never an error."""
    path = audit_dir(carter_dir) / B_LOG
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    except OSError:
        return []
    out: list[dict[str, Any]] = []
    for text in lines:
        with contextlib.suppress(ValueError):
            item = json.loads(text)
            if isinstance(item, dict):
                out.append(item)
    return out
