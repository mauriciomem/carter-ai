"""D52: the per-workspace opt-out from the project-config edit deny (RFC-0007 §4.5, C.6.2).

``[workspaces."<abs path>"] allow_project_opencode_edit = true`` in ``~/.carter/config.toml``
becomes exact-path ``allow`` statements for ``<ws>/opencode.json``, ``<ws>/opencode.jsonc``
and ``<ws>/.opencode/*``, placed after the denies in Carter's block. Only a human may turn
that into a policy: ``carter guard install`` and ``carter update`` run this, show every
active opt-out and ask for confirmation (``--yes`` skips only the question, never the
listing). A shell write to ``config.toml`` is a residual risk, so the human must see it.
Runtime readers (the plugin, ``carter ops``, ``carter identity``) never import this module.

A worktree outside the workspace path gets nothing: the statements name the workspace's
real path and nothing else.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from carter.guard import consent, policies
from carter.guard.configwrite import Reader
from carter.guard.state import GuardState, load_or_empty_readonly, save
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


def refresh_from_update(
    base_dir: Path | None,
    state_path: Path,
    cfg: IdentityConfig,
    *,
    home: str,
    backup_root: Path,
    assume_yes: bool,
    dry_run: bool,
    interactive: bool,
    agent: bool,
    confirm: Callable[[str], bool],
    echo: Echo,
    reader: Reader | None = None,
) -> None:
    """The D52 step of ``carter update``. Silent unless something would change."""
    read = load_or_empty_readonly(state_path)
    if read.status in ("corrupt", "newer"):
        echo(
            "ℹ  guard state is unreadable; D52 opt-outs not refreshed (see `carter guard status`)."
        )
        return
    state: GuardState = read.state
    if consent.CONFIG_EDIT not in consent.accepted_groups(state):
        return  # no policies installed with consent: update never creates them
    optouts = active_optouts(cfg)
    wanted = consent.desired_statements(state, home=home, optouts=optouts.statements())
    preview = policies.apply(base_dir, state, wanted, backup_root=backup_root, dry_run=True)
    if not preview.changed:
        for line in describe(Optouts(refused=optouts.refused)):
            echo(line)
        return
    echo("Policies change (D52 opt-outs and consented statements):")
    if optouts.workspaces or optouts.refused:
        echo("Active opt-outs (agents may edit these project files):")
        for line in describe(optouts):
            echo(line)
    for ident in preview.added:
        echo(f"  + {ident}")
    for ident in preview.removed:
        echo(f"  - {ident}")
    if dry_run:
        echo("Dry run: no policy was written.")
        return
    if agent:
        echo("Policies are applied only from your own terminal (agent shell detected); skipped.")
        return
    if preview.added and not assume_yes:
        if not interactive:
            echo("Not applied: run `carter update` in a terminal, or pass --yes.")
            return
        if not confirm("Apply these policy changes to the OpenCode config?"):
            echo("Not applied.")
            return
    result = policies.apply(base_dir, state, wanted, backup_root=backup_root, reader=reader)
    save(state, state_path)
    echo(f"Policies updated in {result.target}.")
    for warning in result.warnings:
        echo(f"⚠  {warning}")
