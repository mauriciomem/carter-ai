"""One safe edit of the user's live OpenCode config (RFC-0007 App C.6.3).

A broken config drops *all* policies and the providers, so every edit follows the same
transaction: parse → mutate a copy → (if it changed) read ``opencode debug config`` →
back up → atomic write → read ``debug config`` again → restore the backup if a provider or
a statement was lost. ``debug config`` output holds provider settings: it stays in memory
and is never logged, written to a backup or put in an error.

The target is ``opencode.jsonc`` if it exists, else ``opencode.json`` (the same rule the
MCP installer uses). Nothing here knows what is being edited; ``policies`` and
``permissions`` pass a ``mutate`` function.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from carter.harness import DebugConfigError, policy_statements, provider_ids, read_debug_config
from carter.identity.errors import E_POLICIES_MISSING, IdentityError, registry
from carter.identity.policyset import Statement
from carter.install.atomic import atomic_write_bytes
from carter.install.jsonc import _load_jsonc, _write_json_atomic, has_comments
from carter.install.mcp import BACKUP_SUFFIX, config_target

Reader = Callable[[], dict[str, Any]]
Commit = Callable[[Path], None]  # runs after a successful write (or when nothing changed)


class PolicyWriteError(Exception):
    """The config was not (or could not safely be) changed. The message says why."""


@dataclass
class TxResult:
    changed: bool
    target: Path
    backup: Path | None = None
    warnings: list[str] = field(default_factory=list)
    existed: bool = True  # False: Carter created the file (a rollback deletes it)


def target_path(base_dir: Path | None) -> Path:
    return config_target(base_dir)


def missing_statements(
    debug_config: dict[str, Any], expected: Sequence[Statement]
) -> list[Statement]:
    """The expected statements OpenCode did not load. Per statement: an invalid one is
    dropped alone by OpenCode, so the others may still be present."""
    loaded = {
        (s.get("action"), s.get("resource"), s.get("effect"))
        for s in policy_statements(debug_config)
    }
    return [s for s in expected if (s.action, s.resource, s.effect) not in loaded]


def _writable(real: Path) -> bool:
    probe = real if real.exists() else next(p for p in real.parents if p.exists())
    return os.access(probe, os.W_OK) and (not real.exists() or os.access(real.parent, os.W_OK))


def _lost(message: str, items: list[str]) -> IdentityError:
    template = registry()[E_POLICIES_MISSING].message
    shown = ", ".join(f"`{i}`" for i in items)
    return IdentityError(
        E_POLICIES_MISSING, template.replace("`<statement>`", shown), detail=message
    )


def transact(
    base_dir: Path | None,
    mutate: Callable[[dict[str, Any]], Commit],
    *,
    expected: Sequence[Statement] = (),
    backup_root: Path,
    dry_run: bool = False,
    reader: Reader | None = None,
) -> TxResult:
    """Apply ``mutate`` to the config atomically, verified and reversible.

    ``mutate`` edits the parsed config in place and returns a ``Commit`` that records the
    outcome (guard state); it runs only after the write is verified, or when nothing
    changed. ``dry_run`` runs ``mutate`` for its diff and touches nothing else."""
    read = reader or read_debug_config
    target = target_path(base_dir)
    real = Path(os.path.realpath(target))
    result = TxResult(changed=False, target=target)
    original = real.read_bytes() if real.exists() else None
    data: dict[str, Any] = {}
    if original is not None:
        loaded = _load_jsonc(real)
        if not isinstance(loaded, dict):
            raise PolicyWriteError(
                f"cannot parse {target.name} (fix it first); nothing was written"
            )
        data = loaded
    result.existed = original is not None
    edited = copy.deepcopy(data)
    commit = mutate(edited)
    result.changed = edited != data
    commented = original is not None and has_comments(original.decode(errors="replace"))
    if commented and result.changed:
        result.warnings.append(
            f"{target.name} has comments and rewriting drops them (the original is kept as "
            f"{target.name}{BACKUP_SUFFIX}); to paste by hand instead, use --print-policies"
        )
    if dry_run:
        return result
    if not result.changed:
        commit(target)
        return result

    if not _writable(real):
        raise PolicyWriteError(f"{target} is read-only; nothing was written")
    try:
        providers_before = provider_ids(read())
    except DebugConfigError as exc:
        raise PolicyWriteError(
            f"cannot verify the OpenCode config ({exc}); nothing was written"
        ) from exc

    if original is not None:
        result.backup = backup_root / target.name
        atomic_write_bytes(result.backup, original)
        if commented:
            atomic_write_bytes(real.with_name(real.name + BACKUP_SUFFIX), original, mode=0o600)
    _write_json_atomic(target, edited)
    try:
        after = read()
    except DebugConfigError as exc:
        _rollback(real, original, result.backup)
        raise PolicyWriteError(f"rolled back: cannot verify the written config ({exc})") from exc
    lost = sorted(providers_before - provider_ids(after))
    missing = [s.id for s in missing_statements(after, expected)]
    if lost or missing:
        _rollback(real, original, result.backup)
        what = missing + [f"provider {p}" for p in lost]
        raise _lost("rolled back to the backup", what)
    commit(target)
    return result


def restore(target: Path, result: TxResult) -> None:
    """Undo a verified write from the backup (used when a LATER part of an install fails)."""
    real = Path(os.path.realpath(target))
    original = result.backup.read_bytes() if result.backup else None
    if result.changed:
        _rollback(real, original if result.existed else None, result.backup)


def _rollback(real: Path, original: bytes | None, backup: Path | None) -> None:
    try:
        if original is None:
            real.unlink(missing_ok=True)
        else:
            atomic_write_bytes(real, original, follow_symlinks=True)
    except OSError as exc:
        where = f" The original is at {backup}." if backup else ""
        raise PolicyWriteError(f"ROLLBACK FAILED ({type(exc).__name__}).{where}") from exc
