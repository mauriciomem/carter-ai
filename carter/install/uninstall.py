"""Carter uninstall — manifest-driven removal with a by-convention fallback."""

from __future__ import annotations

import shutil
from pathlib import Path

from carter.install.components import read_manifest, remove_legacy_opencode_instructions
from carter.install.console import _log, bold, green, log_ok, log_step
from carter.install.mcp import remove_carter_servers
from carter.install.paths import (
    _carter_base,
    _copilot_base,
    _home,
    _local_bin,
    _opencode_base,
)


def uninstall(base_dir: Path | None) -> None:
    """Remove the OpenCode install. Copilot/VS Code leftovers are not touched (D7)."""
    log_step("Uninstalling Carter...")
    manifest = read_manifest(base_dir)
    opencode_base = _opencode_base(base_dir)
    # The knowledge base is still Carter-managed under ~/.copilot (ADR-0014 phase 4).
    managed_roots = (str(opencode_base), str(_copilot_base(base_dir) / "knowledge"))

    if manifest:
        for f in manifest.get("files", []):
            p = Path(f)
            if p.is_file() and f.startswith(managed_roots):
                p.unlink()
                log_ok(f"Removed {f.replace(str(_home()), '~')}")
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
    manifest_path = _copilot_base(base_dir) / ".carter-manifest.json"
    if manifest_path.exists():
        manifest_path.unlink()
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
