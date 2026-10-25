"""Carter uninstall — manifest-driven removal with a by-convention fallback."""

from __future__ import annotations

import shutil
from pathlib import Path

from carter.home import tilde
from carter.install.components import read_manifest
from carter.install.console import _log, bold, green, log_ok, log_step, log_warn
from carter.install.legacy import remove_legacy_opencode_instructions
from carter.install.mcp import remove_carter_servers
from carter.install.ownership import _hash_matches, _within
from carter.install.paths import (
    _opencode_base,
    knowledge_dir,
    manifest_path,
)


def _remove_if_owned(
    path: Path, recorded: str | None, roots: tuple[Path, ...], opencode_base: Path
) -> None:
    """Delete a manifest file only if Carter still owns it.

    * Outside the managed roots (path-component check, not string prefix) → ignored.
    * Recorded hash → delete only if the content still matches; else keep + warn.
    * No recorded hash (manifests from older versions) → delete only ``carter-*``
      agent/skill files, which are Carter-owned by name. Knowledge files and
      ``AGENTS.md`` are user data and are kept.
    """
    resolved = path.resolve()
    if not path.is_file() or not _within(resolved, roots):
        return
    if recorded is not None:
        if not _hash_matches(path, recorded):
            log_warn(f"Kept {tilde(path)}: edited since install")
            return
    else:
        base = opencode_base.resolve()
        owned_by_name = _within(resolved, (base / "agents", base / "skills")) and any(
            part.startswith("carter-") for part in resolved.relative_to(base).parts
        )
        if not owned_by_name:
            log_warn(f"Kept {tilde(path)}: no recorded hash to prove it is unmodified")
            return
    path.unlink()
    log_ok(f"Removed {tilde(path)}")
    # Drop now-empty carter-* skill directories (never agents/, skills/ or the roots).
    base = opencode_base.resolve()
    keep = (*roots, base / "agents", base / "skills")
    parent = resolved.parent
    while parent not in keep and _within(parent, roots) and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def uninstall(base_dir: Path | None) -> None:
    """Remove the OpenCode install.

    Leftovers of the old Copilot-era install are not touched here; that is
    ``carter uninstall --legacy``.
    """
    log_step("Uninstalling Carter...")
    manifest = read_manifest(base_dir)
    opencode_base = _opencode_base(base_dir)
    managed_roots = (opencode_base.resolve(), knowledge_dir(base_dir).resolve())

    if manifest:
        hashes: dict[str, str] = manifest.get("file_hashes") or {}
        for f in manifest.get("files", []):
            _remove_if_owned(Path(f), hashes.get(f), managed_roots, opencode_base)
    else:
        # No manifest — remove by convention
        # Written by Carter versions that copied instructions for OpenCode.
        remove_legacy_opencode_instructions(base_dir, backup_root=None)
        for pattern_dir in ["agents", "skills"]:
            d = opencode_base / pattern_dir
            if d.exists():
                for f in d.glob("carter-*"):
                    if f.is_file():
                        f.unlink()
                        log_ok(f"Removed {tilde(f)}")
                    elif f.is_dir():
                        shutil.rmtree(f)
                        log_ok(f"Removed {tilde(f)}/")

    log_step("Removing MCP servers (OpenCode)...")
    for name in remove_carter_servers(opencode_base / "opencode.json"):
        log_ok(f"Removed {name} from opencode.json")

    # Remove manifest
    path = manifest_path(base_dir)
    if path.exists():
        path.unlink()
        log_ok("Removed manifest")

    _log(f"\n{green('✓')} {bold('Uninstall complete')}")
