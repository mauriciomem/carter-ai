"""The ``carter.*`` git keys and the D64 cap mirror (RFC-0007 §4.4, freeze H5/H6).

The guard (shell, no Python) learns the tier from Carter's own git file ``~/.carter/gitconfig``:
the base ``carter.tier`` / ``carter.llmEmail`` / ``carter.llmFingerprint``, then one
``[includeIf "gitdir:<realpath(workspace)>/"] path = <carter>/gitconfig.d/<sha256[:16]>`` per
workspace with a ``max_tier``. Each fragment holds only ``[carter] tier = <min(tier, cap)>`` and is
included **after** the base value, so it wins. The pattern is the *real* path with a trailing ``/``
(spike B: a symlinked pattern matches nothing, no trailing slash matches nothing) and may not hold
glob characters. The guard reads the file directly (``git config --file ... --includes``), which
evaluates ``includeIf`` for the repo it runs in, a subdirectory and a linked worktree (step 13).

Everything here is pure data or ``lstat``/``open`` of ``.git`` pointers; the writing is
``carter.guard.mirror_io``. A cap below the pinned ``require_tier`` is refused (``MirrorError``).

Stdlib-only (see ``test_stdlib_only``). ``carter_dir`` is ``~/.carter``.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from carter.identity.errors import E_ROLE_B_TIER, E_TIER_REQUIRED
from carter.identity.resolve import configured_tier, effective_tier
from carter.identity.schema import TIERS, IdentityConfig
from carter.identity.trailer import noreply_email

Entry = tuple[str, str]
CARTER_KEYS = ("carter.tier", "carter.llmEmail", "carter.llmFingerprint")
INCLUDEIF = "includeIf"
GLOB_CHARS = "*?[]\\"
FRAGMENTS_DIR = "gitconfig.d"


class MirrorError(Exception):
    """The mirror cannot be rendered; nothing is written."""


def real_workspace(key: str) -> str:
    """``realpath`` of a workspace key without a trailing slash; glob characters are refused."""
    real = os.path.realpath(key).rstrip("/") or "/"
    if any(c in real for c in GLOB_CHARS):
        raise MirrorError(f"workspace path {real!r} holds a glob character; it cannot be mirrored")
    return real


def fragment_name(key: str) -> str:
    return hashlib.sha256(real_workspace(key).encode()).hexdigest()[:16]


def fragment_path(carter_dir: Path, key: str) -> Path:
    return carter_dir / FRAGMENTS_DIR / fragment_name(key)


def includeif_key(key: str) -> str:
    return f"{INCLUDEIF}.gitdir:{real_workspace(key)}/.path"


def base_entries(cfg: IdentityConfig) -> list[Entry]:
    """``carter.tier`` (absent = t0), then the email and fingerprint where they exist."""
    tier = configured_tier(cfg)
    if tier == "t0":
        return []
    out: list[Entry] = [("carter.tier", tier), ("carter.llmEmail", noreply_email(cfg))]
    if tier == "t2" and cfg.signing.fingerprint:
        out.append(("carter.llmFingerprint", cfg.signing.fingerprint))
    return out


def check_caps(cfg: IdentityConfig) -> None:
    """Refuse a ``max_tier`` below the pinned ``require_tier`` (E-TIER-REQUIRED), and a cap on a
    workspace that pins role ``author`` (E-ROLE-B-TIER: role b needs T2, every cap is below it)."""
    role_b = [key for key, ws in cfg.workspaces.items() if ws.max_tier and ws.role == "author"]
    if role_b:
        raise MirrorError(
            f"{E_ROLE_B_TIER}: role `author` is pinned together with a max_tier cap, and role b "
            "needs T2 (no downgrade): " + ", ".join(role_b)
        )
    bad = [
        key
        for key, ws in cfg.workspaces.items()
        if ws.max_tier
        and ws.require_tier
        and TIERS.index(ws.max_tier) < TIERS.index(ws.require_tier)
    ]
    if bad:
        raise MirrorError(
            f"{E_TIER_REQUIRED}: this workspace requires a higher tier than its max_tier allows: "
            + ", ".join(bad)
        )


def fragments(cfg: IdentityConfig, carter_dir: Path) -> dict[Path, str]:
    """Fragment file -> content, for every workspace with a cap."""
    tier = configured_tier(cfg)
    out: dict[Path, str] = {}
    for key, ws in cfg.workspaces.items():
        if ws.max_tier:
            out[fragment_path(carter_dir, key)] = (
                f"[carter]\n\ttier = {effective_tier(tier, ws.max_tier)}\n"
            )
    return out


def mirror_entries(cfg: IdentityConfig, carter_dir: Path) -> list[Entry]:
    """The entries for ``~/.carter/gitconfig``: base keys first, then the includeIf sections."""
    check_caps(cfg)
    out = base_entries(cfg)
    for path in sorted(fragments(cfg, carter_dir)):
        key = next(k for k in cfg.workspaces if fragment_path(carter_dir, k) == path)
        out.append((includeif_key(key), str(path)))
    return sorted_includes(out)


def sorted_includes(entries: list[Entry]) -> list[Entry]:
    base = [e for e in entries if not e[0].startswith(INCLUDEIF)]
    return base + sorted(e for e in entries if e[0].startswith(INCLUDEIF))


def is_mirror_key(key: str) -> bool:
    return key.lower().startswith(("carter.", INCLUDEIF.lower() + "."))


def canonical_key(key: str) -> str:
    """git lists section and variable names lower-case; restore Carter's spelling."""
    lowered = {k.lower(): k for k in CARTER_KEYS}
    if key.lower() in lowered:
        return lowered[key.lower()]
    if key.lower().startswith(INCLUDEIF.lower() + "."):
        return INCLUDEIF + key[len(INCLUDEIF) :]
    return key


def mirror_state(
    cfg: IdentityConfig, observed: Mapping[str, str | None], workspace: str | None = None
) -> str:
    """``in-sync``, ``stale-added`` or ``stale-removed`` for ``check --host`` and the hooks.

    ``observed`` holds what the guard read in that workspace (``tier``; absent or empty = t0).
    ``stale-added``: the mirror is above what ``config.toml`` allows (a cap was added without
    ``carter update``). ``stale-removed``: it is below (a cap was removed, or the tier raised)."""
    ws = cfg.workspaces.get(workspace) if workspace else None
    expected = effective_tier(configured_tier(cfg), ws.max_tier if ws else "")
    seen = observed.get("tier") or "t0"
    if seen not in TIERS or seen == expected:
        return "in-sync" if seen == expected else "stale-removed"
    return "stale-added" if TIERS.index(seen) > TIERS.index(expected) else "stale-removed"


@dataclass
class WorktreeGaps:
    fail_open: list[str] = field(default_factory=list)  # inside the workspace, main repo outside
    capped_outside: list[str] = field(default_factory=list)  # outside, main repo inside: capped


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip("/") + "/")


def worktree_cap_gaps(workspace: str, depth: int = 3) -> WorktreeGaps:
    """Linked worktrees where the cap does not follow the path (the main repo's git dir decides).

    A ``.git`` *file* under the workspace points at ``<main>/.git/worktrees/<n>``; a ``.git``
    *directory* lists its own worktrees in ``worktrees/*/gitdir``. Nothing is executed."""
    root = os.path.realpath(workspace)
    gaps = WorktreeGaps()
    for current, dirs, files in os.walk(root):
        if current[len(root) :].count("/") >= depth:
            dirs[:] = []
        if ".git" in files:
            pointer = _read(os.path.join(current, ".git")).removeprefix("gitdir:").strip()
            main = (
                os.path.realpath(pointer.split("/worktrees/")[0])
                if "/worktrees/" in pointer
                else ""
            )
            if main and not _inside(main, root):
                gaps.fail_open.append(os.path.realpath(current))
        if ".git" in dirs:
            base = os.path.join(current, ".git", "worktrees")
            for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
                target = _read(os.path.join(base, name, "gitdir"))
                path = os.path.dirname(os.path.realpath(target)) if target else ""
                if path and not _inside(path, root):
                    gaps.capped_outside.append(path)
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
    return gaps


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


__all__ = [
    "CARTER_KEYS", "MirrorError", "WorktreeGaps", "base_entries", "canonical_key", "check_caps",
    "fragment_name", "fragment_path", "fragments", "includeif_key", "is_mirror_key",
    "mirror_entries", "mirror_state", "real_workspace", "worktree_cap_gaps",
]  # fmt: skip
