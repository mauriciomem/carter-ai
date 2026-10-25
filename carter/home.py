"""User-level Carter locations, shared by the installer and ``carter ops``.

Kept dependency-free so ``carter.ops`` can use it without importing the
installer.
"""

from __future__ import annotations

from pathlib import Path


def carter_home() -> Path:
    """Return the user's Carter state directory, ``~/.carter``."""
    return Path.home() / ".carter"


def tilde(path: Path | str) -> str:
    """Render ``path`` for display with the home directory shortened to ``~``."""
    return str(path).replace(str(Path.home()), "~")
