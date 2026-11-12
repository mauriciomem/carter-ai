"""User-level Carter locations, shared by the installer and ``carter ops``.

Kept dependency-free so ``carter.ops`` can use it without importing the
installer.
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path


def carter_home() -> Path:
    """Return the user's Carter state directory, ``~/.carter``."""
    return Path.home() / ".carter"


def tilde(path: Path | str) -> str:
    """Render ``path`` for display with the home directory shortened to ``~``."""
    return str(path).replace(str(Path.home()), "~")


WORKSPACES_FILE = "workspaces"


def remember_workspace(target: Path | str) -> None:
    """Append ``target`` to ``~/.carter/workspaces`` once: one absolute path per line, 0600.

    ``uninstall`` reads the file to say where Carter left files. Best effort: it never fails a
    command. A path with a control character (a newline would be two entries) is not written."""
    if not str(target).isprintable():
        return
    path = os.path.abspath(target)
    file = carter_home() / WORKSPACES_FILE
    with contextlib.suppress(OSError, ValueError):  # unwritable or not UTF-8: no failure for this
        known = file.read_text(encoding="utf-8") if file.exists() else ""
        if path in known.splitlines():
            return
        file.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        with os.fdopen(os.open(file, flags, 0o600), "a", encoding="utf-8") as fh:
            fh.write(("\n" if known and not known.endswith("\n") else "") + path + "\n")
        file.chmod(0o600)
