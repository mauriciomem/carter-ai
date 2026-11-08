"""D52: the per-workspace opt-out from the project-config edit deny (RFC-0007 §4.5, C.6.2).

``[workspaces."<abs path>"] allow_project_opencode_edit = true`` in ``~/.carter/config.toml``
becomes exact-path ``allow`` rules for ``<ws>/opencode.json``, ``<ws>/opencode.jsonc``
and ``<ws>/.opencode/*``, placed after the denies in the Carter agents' ``permissions:`` (D71).
``carter guard install`` lists every active opt-out; ``carter update`` re-renders the agent
files from ``config.toml``. A shell write to ``config.toml`` is a residual risk, so the human
must see them.
Runtime readers (the plugin, ``carter ops``, ``carter identity``) never import this module.

A worktree outside the workspace path gets nothing: the statements name the workspace's
real path and nothing else.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from carter.guard import consent
from carter.identity.policyset import Statement
from carter.identity.schema import IdentityConfig

SUFFIXES = (("json", "opencode.json"), ("jsonc", "opencode.jsonc"), ("dir", ".opencode/*"))
Echo = Callable[[str], None]


def workspace_id(real_path: str) -> str:
    return hashlib.sha256(real_path.encode()).hexdigest()[:8]


@dataclass
class Optouts:
    workspaces: list[str] = field(default_factory=list)  # real paths, sorted
    refused: list[str] = field(
        default_factory=list
    )  # human-readable reasons (no values of secrets)

    def statements(self) -> list[Statement]:
        return optout_statements(self.workspaces)


def active_optouts(cfg: IdentityConfig) -> Optouts:
    """Workspaces with the flag set, as resolved real paths (the same normalisation the
    ``carter update`` pinning uses). Missing directories and paths holding a glob
    character are refused: an ``allow`` must never be wider than one project."""
    out = Optouts()
    for key, ws in cfg.workspaces.items():
        if not ws.allow_project_opencode_edit:
            continue
        real = Path(key).resolve()
        if "*" in str(real) or "?" in str(real):
            out.refused.append(f"{key}: path holds a glob character (* or ?)")
        elif not real.is_dir():
            out.refused.append(f"{key}: directory not found")
        else:
            out.workspaces.append(str(real))
    out.workspaces = sorted(set(out.workspaces))
    return out


def optout_statements(workspaces: Iterable[str]) -> list[Statement]:
    return [
        Statement(
            f"optout-{workspace_id(ws)}-{slug}",
            consent.CONFIG_EDIT,
            "tool.use",
            f"edit:{ws}/{tail}",
            "allow",
            "4.5 D48 opt-out (D52)",
        )
        for ws in workspaces
        for slug, tail in SUFFIXES
    ]


def describe(optouts: Optouts) -> list[str]:
    lines = [f"  {ws}/{{opencode.json, opencode.jsonc, .opencode/*}}" for ws in optouts.workspaces]
    return [f"  not applied, {why}" for why in optouts.refused] + lines
