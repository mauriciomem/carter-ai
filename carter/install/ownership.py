"""Content hashing and ownership checks: delete only what Carter still owns."""

from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    """Return the ``sha256:``-prefixed hex digest Carter records in its manifest."""
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _hash_matches(path: Path, recorded: str) -> bool:
    """True if ``path``'s content still has the hash ``recorded`` (prefix optional)."""
    digest = sha256_bytes(path.read_bytes()).removeprefix("sha256:")
    return recorded.removeprefix("sha256:") == digest


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    """Path-component containment (not string prefix): ``opencode-foo`` is not in ``opencode``."""
    return any(path.is_relative_to(r) for r in roots)
