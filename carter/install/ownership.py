"""Ownership checks shared by uninstall paths: delete only what Carter still owns."""

from __future__ import annotations

import hashlib
from pathlib import Path


def _hash_matches(path: Path, recorded: str) -> bool:
    """True if ``path``'s content still has the ``sha256:``-prefixed hash ``recorded``."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return recorded.removeprefix("sha256:") == digest


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    """Path-component containment (not string prefix): ``opencode-foo`` is not in ``opencode``."""
    return any(path.is_relative_to(r) for r in roots)
