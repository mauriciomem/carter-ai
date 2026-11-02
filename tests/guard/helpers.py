"""Plain helpers for the ``carter guard`` tests (fixtures live in ``conftest.py``)."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from pathlib import Path

from carter.identity.policyset import Statement, policy_statements


def tree_hash(root: Path, skip: Iterable[str] = ()) -> dict[str, str]:
    """Relative path → sha256 (or ``link->target``) for every file under ``root``."""
    out: dict[str, str] = {}
    skipped = tuple(skip)
    for path in sorted(root.rglob("*")):
        rel = str(path.relative_to(root))
        if any(part in skipped for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            out[rel] = f"link->{os.readlink(path)}"
        elif path.is_file():
            out[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def debug_config(statements: Iterable[Statement] = (), providers: dict | None = None) -> str:
    """What the fake ``opencode debug config`` prints: providers (with a secret-looking
    value that must never leak) and the resolved policies."""
    items = [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in statements]
    prov = {"example": {"settings": {"apiKey": "sk-SENTINEL"}}} if providers is None else providers
    return json.dumps({"providers": prov, "policies": items})


def agents_json(*ids: str) -> str:
    return json.dumps([{"id": i, "name": i} for i in ids])


def all_live_statements(home: str) -> list[Statement]:
    return list(policy_statements(home=home))
