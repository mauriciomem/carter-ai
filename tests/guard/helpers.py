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


def denies() -> list[dict]:
    return [{"action": a, "resource": "*", "effect": "deny"} for a in ("carter_push", "carter_pr")]


def agents_json(*ids: str, denied: bool = True) -> str:
    """What the fake ``opencode debug agents`` prints; by default every agent carries the denies."""
    return json.dumps(
        [{"id": i, "name": i, "permissions": denies() if denied else []} for i in ids]
    )


def all_live_statements(home: str) -> list[Statement]:
    return list(policy_statements(home=home))


OLD_GIT = """#!/bin/sh
# A git that predates config-based hooks: `git hook ...` is unknown (usage error 129).
for arg in "$@"; do
  case "$arg" in
    -*) ;;
    hook) echo "usage: git hook run <hook-name> [-- <hook-args>]" >&2; exit 129 ;;
    *) break ;;
  esac
done
exec {real} "$@"
"""


def install_old_git(bindir: Path, real_git: str) -> None:
    """Put a ``git`` into ``bindir`` that behaves like git < 2.54 for the probe (6)."""
    wrapper = bindir / "git"
    wrapper.unlink(missing_ok=True)
    wrapper.write_text(OLD_GIT.replace("{real}", real_git))
    wrapper.chmod(0o755)


def STAND_IN(*_a: object, **_k: object) -> list[tuple[str, str]]:  # noqa: N802
    """A stand-in for ``carter_git_entries``: one Carter-owned git key that is not a ``carter.*``
    mirror key (those belong to the hook tier and survive ``guard remove``)."""
    return [("alias.ai-commit", "!true")]


def verbose(args: tuple[str, ...]) -> tuple[str, ...]:
    """``guard install, remove, status`` show details with ``-v`` (); these tests read them."""
    if args and args[0] in ("install", "remove", "status"):
        return (args[0], "-v", *args[1:])
    return tuple(args)


def decline(*groups: str) -> None:
    """Record these groups as declined in the guard state (a TTY could once decline one by one;
    made the install one question, so the state is the way to get a declined group)."""
    from carter.guard.state import load_or_empty_readonly, save
    from carter.identity.policyset import consent_groups
    from carter.install.paths import guard_state_path

    path = guard_state_path(None)
    state = load_or_empty_readonly(path).state
    revs = {g.id: g.rev for g in consent_groups()}
    for name in groups:
        state.consent(name, "declined", "2026-01-01", revs[name])
    path.parent.mkdir(parents=True, exist_ok=True)
    save(state, path)


def replace_others(base_dir, state, others):  # type: ignore[no-untyped-def]
    """Rewrite Carter's git file with new hook/alias entries, keeping the mirror and fragments."""
    from carter.guard import mirror_io
    from carter.identity import mirror

    mine, _ = mirror_io.split(mirror_io.read_entries(mirror_io.carter_gitconfig_path(base_dir)))
    carter = mirror_io.carter_dir(base_dir)
    frags = {p: p.read_text() for p in (carter / mirror.FRAGMENTS_DIR).glob("*")} if mine else {}
    return mirror_io.write_entries(base_dir, state, mine, others, frags)
