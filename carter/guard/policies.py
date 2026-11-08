"""The OpenCode config writes of ``carter guard`` (RFC-0007 App C.6.3, amended by D71).

Since D71 Carter writes no global ``policies``: G2's deny set lives in the Carter agents' own
``permissions:`` (``agent_rules``). ``apply`` is kept for what remains: it takes out the
statements an earlier Carter recorded (owned tuples only; a statement the user already had
verbatim was recorded ``preexisting`` and is never touched, and a recorded statement the user
edited is no longer ours) and converges the per-agent ``carter_push`` denies of the built-in
agents (D46), all in one verified write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from carter.guard import permissions
from carter.guard.configwrite import (
    Commit,
    PolicyWriteError,
    Reader,
    TxResult,
    missing_statements,
    target_path,
    transact,
)
from carter.guard.state import GuardState
from carter.identity.policyset import Statement, agent_permission_denies, render_policies

__all__ = [
    "ApplyResult",
    "PolicyWriteError",
    "RemoveResult",
    "apply",
    "missing_statements",
    "remove",
    "target_path",
]

Key = tuple[Any, Any, Any]


def _key(item: dict[str, Any] | Statement) -> Key:
    if isinstance(item, Statement):
        return (item.action, item.resource, item.effect)
    return (item.get("action"), item.get("resource"), item.get("effect"))


@dataclass
class ApplyResult:
    changed: bool = False
    target: Path | None = None
    backup: Path | None = None
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    preexisting: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    perms: permissions.PermDiff = field(default_factory=permissions.PermDiff)
    tx: TxResult | None = None  # for `configwrite.restore` if a later install part fails


@dataclass
class RemoveResult:
    changed: bool = False
    removed: list[str] = field(default_factory=list)
    kept_edited: list[str] = field(default_factory=list)  # recorded, but no longer as written
    perms: permissions.PermDiff = field(default_factory=permissions.PermDiff)


def _policies_list(config: dict[str, Any]) -> list[dict[str, Any]]:
    block = config.get("policies", [])
    if not isinstance(block, list) or not all(isinstance(s, dict) for s in block):
        raise PolicyWriteError(
            "`policies` in the OpenCode config is not a list of statements; nothing was written"
        )
    return list(block)


def _take_last(items: list[dict[str, Any]], key: Key) -> bool:
    for i in range(len(items) - 1, -1, -1):
        if _key(items[i]) == key:
            del items[i]
            return True
    return False


def _store(config: dict[str, Any], items: list[dict[str, Any]]) -> None:
    if items:
        config["policies"] = items
    else:
        config.pop("policies", None)


def apply(
    base_dir: Path | None,
    state: GuardState,
    statements: Sequence[Statement],
    *,
    backup_root: Path,
    dry_run: bool = False,
    reader: Reader | None = None,
    agents: Sequence[str] = (),
) -> ApplyResult:
    """Converge the config onto ``statements`` (ordered: denies, then allows) and onto the
    per-agent ``carter_push`` denies for ``agents`` (built-ins; D46), in ONE
    atomic, verified write. Agents recorded earlier but not listed any more are un-denied.

    Raises ``PolicyWriteError`` (nothing or the original restored) or ``IdentityError``
    (``E-POLICIES-MISSING``: rolled back because a provider or statement was lost). Guard
    state is updated in memory only after the write verified; the caller saves it."""
    out = ApplyResult()

    def mutate(config: dict[str, Any]) -> Commit:
        kept = _policies_list(config)
        old_keys = {
            r["id"]: (r["action"], r["resource"], r["effect"]) for r in state.owned_policies()
        }
        for key in old_keys.values():
            _take_last(kept, key)
        block: list[dict[str, Any]] = []
        owned_flags: dict[str, bool] = {}
        for s in statements:
            present = any(_key(k) == _key(s) for k in kept)
            owned_flags[s.id] = not present
            if not present:
                block.append(render_policies([s])[0])
        _store(config, kept + block)
        out.perms = permissions.converge(config, state, agents, agent_permission_denies())
        new_keys = {s.id: _key(s) for s in statements if owned_flags[s.id]}
        out.removed = [i for i, k in old_keys.items() if new_keys.get(i) != k]
        out.added = [i for i, k in new_keys.items() if old_keys.get(i) != k]
        out.preexisting = [s.id for s in statements if not owned_flags[s.id]]

        def commit(target: Path) -> None:
            state.opencode_policies = []
            for s in statements:
                state.record_policy(
                    s.id, s.action, s.resource, s.effect, preexisting=not owned_flags[s.id]
                )
            state.agent_permissions = list(out.perms.records)
            owns = state.opencode_policies or state.agent_permissions
            state.opencode_config = str(target) if owns else None

        return commit

    tx = transact(
        base_dir,
        mutate,
        expected=statements,
        backup_root=backup_root,
        dry_run=dry_run,
        reader=reader,
    )
    out.changed, out.target, out.backup, out.warnings, out.tx = (
        tx.changed,
        tx.target,
        tx.backup,
        tx.warnings,
        tx,
    )
    return out


def remove(
    base_dir: Path | None,
    state: GuardState,
    *,
    backup_root: Path,
    dry_run: bool = False,
    reader: Reader | None = None,
) -> RemoveResult:
    """Delete the statements and per-agent denies Carter owns and still finds as recorded.

    Preexisting entries are never touched; an edited one is kept and reported."""
    out = RemoveResult()
    owned = state.owned_policies()
    if not state.opencode_policies and not state.agent_permissions:
        return out

    def mutate(config: dict[str, Any]) -> Commit:
        kept = _policies_list(config)
        for rec in owned:
            gone = _take_last(kept, (rec["action"], rec["resource"], rec["effect"]))
            (out.removed if gone else out.kept_edited).append(rec["id"])
        _store(config, kept)
        permissions.remove_owned(config, state, out.perms)

        def commit(_target: Path) -> None:
            state.opencode_policies = []
            state.agent_permissions = []
            state.opencode_config = None

        return commit

    tx = transact(base_dir, mutate, backup_root=backup_root, dry_run=dry_run, reader=reader)
    out.changed = tx.changed
    return out
