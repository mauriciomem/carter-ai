"""``~/.carter/backups/<UTC stamp>/``: where a copy goes before Carter replaces a file, and the
pruning of old ones. The directory name is the clock."""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from carter.home import STAMP_FORMAT

RETENTION_DAYS = 15


class BackupRoot:
    """One stamp folder, created the first time something is copied into it.

    It is always a new directory (mode 0700): a name that is taken, by an earlier run in the same
    second or by something planted ahead of time, moves to the next second. So a copy can never
    land through a link or in a folder somebody else prepared. ``path`` is where it is, or will
    be."""

    def __init__(self, parent: Path, now: datetime | None = None) -> None:
        self.parent = parent
        self._when = now or datetime.now(UTC)
        self.path = parent / self._when.strftime(STAMP_FORMAT)
        self.copied = 0  # files copied into it by this run
        self._made = False

    def make(self) -> Path:
        """Create the folder if this is the first use; return it."""
        if self._made:
            return self.path
        if self.parent.is_symlink():
            raise OSError(f"{self.parent} is a symlink; refusing to write backups through it")
        self.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        for _ in range(100):
            try:
                os.mkdir(self.path, 0o700)
            except FileExistsError:
                self._when += timedelta(seconds=1)
                self.path = self.parent / self._when.strftime(STAMP_FORMAT)
            else:
                self._made = True
                return self.path
        raise FileExistsError(f"no free backup folder name under {self.parent}")


def prune(root: Path, now: datetime | None = None) -> int:
    """Delete the ``<stamp>`` directories under ``root`` older than ``RETENTION_DAYS``.

    The age comes from the name, not the mtime: a copy keeps the original's mtime, so a fresh
    backup of an old file would look expired. Anything whose name is not exactly a stamp (the
    legacy ``agents/``, stray files) and every symlink is left alone, a symlinked ``root``
    included. Best effort: an unreadable ``root`` prunes nothing, it never fails an install.
    Returns how many directories went."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=RETENTION_DAYS)
    gone = 0
    try:
        entries = sorted(root.iterdir()) if root.is_dir() and not root.is_symlink() else ()
    except OSError:
        return 0
    for entry in entries:
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
