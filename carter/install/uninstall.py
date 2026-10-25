"""Carter uninstall — manifest-driven removal with a by-convention fallback."""

from __future__ import annotations

import shutil
from pathlib import Path

from carter.install.components import read_manifest
from carter.install.console import _log, bold, green, log_ok, log_step, log_warn
from carter.install.legacy import remove_legacy_opencode_instructions
from carter.install.mcp import remove_carter_servers
from carter.install.ownership import _hash_matches, _within
from carter.install.paths import (
    _carter_base,
    _home,
    _local_bin,
    _opencode_base,
    knowledge_dir,
    manifest_path,
)


def _tilde(p: Path) -> str:
    return str(p).replace(str(_home()), "~")


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
            log_warn(f"Kept {_tilde(path)}: edited since install")
            return
    else:
        base = opencode_base.resolve()
        owned_by_name = _within(resolved, (base / "agents", base / "skills")) and any(
            part.startswith("carter-") for part in resolved.relative_to(base).parts
        )
        if not owned_by_name:
            log_warn(f"Kept {_tilde(path)}: no recorded hash to prove it is unmodified")
            return
    path.unlink()
    log_ok(f"Removed {_tilde(path)}")
    # Drop now-empty carter-* skill directories (never agents/, skills/ or the roots).
    base = opencode_base.resolve()
    keep = (*roots, base / "agents", base / "skills")
    parent = resolved.parent
    while parent not in keep and _within(parent, roots) and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def uninstall(base_dir: Path | None) -> None:
    """Remove the OpenCode install. Pre-ADR-0014 leftovers are not touched (D7)."""
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
                        log_ok(f"Removed {str(f).replace(str(_home()), '~')}")
                    elif f.is_dir():
                        shutil.rmtree(f)
                        log_ok(f"Removed {str(f).replace(str(_home()), '~')}/")

    log_step("Removing MCP servers (OpenCode)...")
    for name in remove_carter_servers(opencode_base / "opencode.json"):
        log_ok(f"Removed {name} from opencode.json")

    # Remove manifest
    path = manifest_path(base_dir)
    if path.exists():
        path.unlink()
        log_ok("Removed manifest")

    # Remove carter-ops
    ops_dir = _carter_base(base_dir) / "ops"
    if ops_dir.exists():
        shutil.rmtree(ops_dir)
        log_ok(f"Removed {str(ops_dir).replace(str(_home()), '~')}/")

    wrapper = _local_bin(base_dir) / "carter-ops"
    if wrapper.exists():
        wrapper.unlink()
        log_ok(f"Removed {str(wrapper).replace(str(_home()), '~')}")

    _log(f"\n{green('✓')} {bold('Uninstall complete')}")
