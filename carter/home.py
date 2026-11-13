"""User-level Carter locations, shared by the installer and ``carter ops``.

Kept dependency-free so ``carter.ops`` can use it without importing the
installer.
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path


def carter_home() -> Path:
    """Return the user's Carter state directory, ``~/.carter``."""
    return Path.home() / ".carter"


def tilde(path: Path | str) -> str:
    """Render ``path`` for display with the home directory shortened to ``~``: only a leading
    ``<home>/`` (or ``<home>`` itself), so ``/home/u2/x`` is not ``~2/x`` under ``/home/u``."""
    text, home = str(path), str(Path.home())
    return "~" + text[len(home) :] if text == home or text.startswith(home + os.sep) else text


WORKSPACES_FILE = "workspaces"
MAX_WORKSPACES_BYTES = 64 * 1024  # a longer file is read only up to here


def remember_workspace(target: Path | str) -> None:
    """Append ``target`` to ``~/.carter/workspaces`` once: one absolute path per line, 0600.

    ``uninstall`` reads the file to say where Carter left files. Best effort: it never fails a
    command. A path with a control character (a newline would be two entries) is not written."""
    if not str(target).isprintable():
        return
    path = os.path.abspath(target)
    file = carter_home() / WORKSPACES_FILE
    with contextlib.suppress(OSError, ValueError):  # unwritable or not UTF-8: no failure for this
        file.parent.mkdir(parents=True, exist_ok=True)
        # One descriptor for the read, the mode and the append: a link swapped in meanwhile is
        # never followed (O_NOFOLLOW) and the mode is set on the file, not on a path.
        flags = os.O_RDWR | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(file, flags, 0o600), "a+", encoding="utf-8") as fh:
            if not stat.S_ISREG(os.fstat(fh.fileno()).st_mode):
                return
            os.fchmod(fh.fileno(), 0o600)
            fh.seek(0)
            known = fh.read(MAX_WORKSPACES_BYTES)
            if path in known.splitlines():
                return
            fh.write(("\n" if known and not known.endswith("\n") else "") + path + "\n")
