"""Pruning of ``~/.carter/backups/<UTC stamp>/``: the directory name is the clock."""

from __future__ import annotations

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

RETENTION_DAYS = 15
STAMP_FORMAT = "%Y%m%dT%H%M%S"


def prune(root: Path, now: datetime | None = None) -> int:
    """Delete the ``<stamp>`` directories under ``root`` older than ``RETENTION_DAYS``.

    The age comes from the name, not the mtime: ``shutil.copy2`` keeps the original's mtime,
    so a fresh backup of an old file would look expired. Anything whose name is not exactly a
    stamp (the legacy ``agents/``, stray files) and every symlink is left alone. Returns how
    many directories went."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    gone = 0
    for entry in sorted(root.iterdir()) if root.is_dir() else ():
        try:
            when = datetime.strptime(entry.name, STAMP_FORMAT).replace(tzinfo=UTC)
        except ValueError:
            continue
        if when.strftime(STAMP_FORMAT) != entry.name or entry.is_symlink() or not entry.is_dir():
            continue
        if when < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            gone += not entry.exists()
    return gone
