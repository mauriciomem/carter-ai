"""One-shot migration of Carter state from ``~/.copilot`` to ``~/.carter`` (ADR-0014 D3).

Copied (never moved — sources stay in place):

* ``~/.copilot/knowledge/``            → ``~/.carter/knowledge/``
* ``~/.copilot/.carter-manifest.json`` → ``~/.carter/manifest.json``
* ``~/.copilot/backup/<timestamp>/``   → ``~/.carter/backups/<timestamp>/``

Per file: missing at the destination → copied; identical content → skipped;
different content → the destination is kept and a warning names the file. The
manifest is the exception: if ``~/.carter/manifest.json`` already exists it was
written by a current install and supersedes the old one, so it is skipped silently.
The old manifest is copied as-is; :func:`carter.install.components.read_manifest`
accepts both shapes.

The single entry point is ``carter install``. After the first run a marker file is
written so later runs are silent no-ops — otherwise every knowledge file the agents
edit in ``~/.carter`` would be reported as a "conflict" on each install. Delete the
marker to re-run the migration.
"""

from __future__ import annotations

import filecmp
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from carter.home import tilde
from carter.install.console import log_ok, log_step, log_warn
from carter.install.paths import (
    _carter_base,
    _copilot_base,
    backups_dir,
    knowledge_dir,
    legacy_manifest_path,
    manifest_path,
)

MARKER_NAME = ".migrated-from-copilot"


@dataclass
class MigrationResult:
    copied: list[Path] = field(default_factory=list)
    conflicts: list[Path] = field(default_factory=list)


def _pairs(base_dir: Path | None) -> list[tuple[Path, Path]]:
    """(source, destination) file pairs to consider, knowledge and backups only."""
    copilot = _copilot_base(base_dir)
    pairs: list[tuple[Path, Path]] = []
    for src_root, dst_root in (
        (copilot / "knowledge", knowledge_dir(base_dir)),
        (copilot / "backup", backups_dir(base_dir)),
    ):
        if not src_root.is_dir():
            continue
        for src in sorted(src_root.rglob("*")):
            if src.is_file() and not src.is_symlink():
                pairs.append((src, dst_root / src.relative_to(src_root)))
    return pairs


def migrate_copilot_state(base_dir: Path | None) -> MigrationResult:
    """Copy Carter state out of ``~/.copilot`` once. Never deletes or overwrites."""
    result = MigrationResult()
    marker = _carter_base(base_dir) / MARKER_NAME
    old_manifest = legacy_manifest_path(base_dir)
    pairs = _pairs(base_dir)
    if marker.exists() or (not pairs and not old_manifest.is_file()):
        return result

    for src, dst in pairs:
        if not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            result.copied.append(dst)
        elif not filecmp.cmp(src, dst, shallow=False):
            result.conflicts.append(dst)

    new_manifest = manifest_path(base_dir)
    if old_manifest.is_file() and not new_manifest.exists():
        new_manifest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(old_manifest, new_manifest)
        result.copied.append(new_manifest)

    if result.copied or result.conflicts:
        log_step("Migrating Carter state from ~/.copilot to ~/.carter...")
    if result.copied:
        log_ok(f"Migrated {len(result.copied)} file(s) to {tilde(_carter_base(base_dir))}")
    for dst in result.conflicts:
        log_warn(
            f"{tilde(dst)} differs from its ~/.copilot copy — not overwritten",
            "Merge the two by hand if you need the old content; the ~/.copilot copy is kept.",
        )

    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(f"{datetime.now(UTC).isoformat()}\n")
    return result
