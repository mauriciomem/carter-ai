"""File hashing, backup and file installation primitives."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path

from carter.home import tilde
from carter.install.console import log_debug, log_ok, log_skip
from carter.install.ownership import sha256_bytes


def _sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _mirror(path: Path) -> Path:
    """Where a backup of ``path`` goes under ``backups/<stamp>/``: its own location, so two
    ``SKILL.md`` never share a name. Relative to ``$HOME``; outside it, without the anchor.
    The path is normalised first, so a ``..`` cannot climb out of the backup root."""
    p = Path(os.path.abspath(path))
    try:
        return p.relative_to(Path.home())
    except ValueError:
        return p.relative_to(p.anchor)


def _backup_file(path: Path, backup_root: Path) -> None:
    if not path.exists():
        return
    dest = backup_root / _mirror(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    log_debug(f"Backed up {path} → {dest}")


def _install_content(
    dst: Path,
    content_hash: str,
    write: Callable[[], object],
    manifest: dict,
    backup_root: Path,
) -> str:
    """Install ``dst`` via ``write`` unless it already has ``content_hash``.

    A differing existing file is backed up first, unless it is the output Carter recorded
    last time (``manifest["file_hashes"]`` is seeded with the previous install's hashes):
    that is reproducible, so only an edit or a file Carter never wrote is copied. ``dst`` is
    always recorded in the manifest with ``content_hash``. Returns ``created``, ``updated``
    or ``unchanged``.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        current = _sha256(dst)
        if current == content_hash:
            log_skip(tilde(dst))
            status = "unchanged"
        else:
            if current != manifest["file_hashes"].get(str(dst)):
                _backup_file(dst, backup_root)
            write()
            log_ok(tilde(dst), "updated")
            status = "updated"
    else:
        write()
        log_ok(tilde(dst))
        status = "created"
    manifest["files"].append(str(dst))
    manifest["file_hashes"][str(dst)] = content_hash
    return status


def _install_rendered_file(
    content: str,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Write already-rendered ``content`` to ``dst`` (no source file to copy).

    Used to install rendered output, e.g. agents rendered from ``templates/``
    with OpenCode V2 ``permissions:`` frontmatter. Same backup/manifest/hash
    semantics as ``_install_file``.
    """
    return _install_content(
        dst,
        sha256_bytes(content.encode()),
        lambda: dst.write_text(content, encoding="utf-8"),
        manifest,
        backup_root,
    )


def _install_file(
    src: Path,
    dst: Path,
    manifest: dict,
    backup_root: Path,
) -> str:
    """Copy src to dst. Returns status: 'created', 'updated', or 'unchanged'."""
    return _install_content(
        dst, _sha256(src), lambda: shutil.copy2(src, dst), manifest, backup_root
    )
