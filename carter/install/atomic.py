"""Atomic file replacement for files Carter writes into places the user also owns.

Temp file in the *target's* directory (same filesystem, so ``os.replace`` is atomic),
``fsync`` before the swap, mode set before any content lands, temp removed on any error.
A reader sees the old file or the new one, never half of either.
"""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path


def atomic_write_bytes(
    path: Path,
    data: bytes,
    *,
    mode: int = 0o600,
    follow_symlinks: bool = False,
    dir_mode: int = 0o700,
) -> Path:
    """Replace ``path`` with ``data`` atomically and return the file actually written.

    ``follow_symlinks`` writes onto the link's target and leaves the link in place (a
    dotfile-managed config). An existing file keeps its permission bits; a new one gets
    ``mode``. Missing parent directories are created with ``dir_mode``.
    """
    target = Path(os.path.realpath(path)) if follow_symlinks else path
    target.parent.mkdir(parents=True, exist_ok=True, mode=dir_mode)
    with contextlib.suppress(OSError):  # no such file yet: keep the requested mode
        mode = target.stat().st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.")
    try:
        os.fchmod(fd, mode)
        try:
            handle = os.fdopen(fd, "wb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
