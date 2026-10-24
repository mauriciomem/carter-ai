"""Carter uninstall — manifest-driven removal with a by-convention fallback."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from carter.install.components import read_manifest, remove_legacy_opencode_instructions
from carter.install.console import _log, bold, green, log_err, log_ok, log_skip, log_step
from carter.install.jsonc import _load_jsonc, _write_json_preserving
from carter.install.mcp import MCP_SERVERS
from carter.install.paths import (
    _carter_base,
    _copilot_base,
    _home,
    _local_bin,
    _opencode_base,
)


def uninstall(targets: list[str], base_dir: Path | None, prereqs: dict[str, bool]) -> None:
    # Resolved lazily: _vscode_settings_path is defined in carter.installer (it
    # resolves _vscode_user_dirs through that namespace for test monkeypatching),
    # and importing it at module scope would be circular.
    from carter.installer import _vscode_settings_path

    log_step("Uninstalling Carter...")
    manifest = read_manifest(base_dir)

    if manifest:
        # Remove files from manifest
        for f in manifest.get("files", []):
            p = Path(f)
            if p.exists():
                # Check if this file belongs to a requested target
                copilot_base = str(_copilot_base(base_dir))
                opencode_base = str(_opencode_base(base_dir))

                if (
                    "copilot" in targets
                    and f.startswith(copilot_base)
                    or "opencode" in targets
                    and f.startswith(opencode_base)
                ):
                    p.unlink()
                    log_ok(f"Removed {f.replace(str(_home()), '~')}")
    else:
        # No manifest — remove by convention
        if "copilot" in targets:
            base = _copilot_base(base_dir)
            for pattern_dir in ["agents", "skills"]:
                d = base / pattern_dir
                if d.exists():
                    for f in d.glob("carter-*"):
                        if f.is_file():
                            f.unlink()
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}")
                        elif f.is_dir():
                            shutil.rmtree(f)
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}/")

        if "opencode" in targets:
            base = _opencode_base(base_dir)
            # Written by Carter versions that copied instructions for OpenCode.
            remove_legacy_opencode_instructions(base_dir, backup_root=None)
            for pattern_dir in ["agents", "skills"]:
                d = base / pattern_dir
                if d.exists():
                    for f in d.glob("carter-*"):
                        if f.is_file():
                            f.unlink()
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}")
                        elif f.is_dir():
                            shutil.rmtree(f)
                            log_ok(f"Removed {str(f).replace(str(_home()), '~')}/")

    # Remove MCP server entries
    if "copilot" in targets:
        log_step("Removing MCP servers (VS Code)...")
        vscode_settings = _vscode_settings_path(base_dir)
        if vscode_settings.exists():
            data = _load_jsonc(vscode_settings)
            if data is not None:
                mcp = data.get("mcp.servers", {})
                removed = [k for k in list(mcp.keys()) if k.startswith("carter-")]
                for k in removed:
                    del mcp[k]
                    log_ok(f"Removed {k} from settings.json")
                data["mcp.servers"] = mcp
                _write_json_preserving(vscode_settings, data)
            else:
                log_err("Could not parse VS Code settings.json — skipping to avoid data loss")

        # Copilot CLI
        if prereqs.get("copilot", False) and not base_dir:
            log_step("Removing MCP servers (Copilot CLI)...")
            for server in MCP_SERVERS:
                name = f"carter-{server}"
                try:
                    subprocess.run(
                        ["copilot", "mcp", "remove", name],
                        capture_output=True,
                        timeout=10,
                    )
                    log_ok(f"Removed {name} from Copilot CLI")
                except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    log_skip(f"{name} not found in Copilot CLI")

    if "opencode" in targets:
        log_step("Removing MCP servers (OpenCode)...")
        opencode_config = _opencode_base(base_dir) / "opencode.json"
        if opencode_config.exists():
            data = _load_jsonc(opencode_config)
            if data is not None:
                mcp = data.get("mcp", {})
                removed = [k for k in list(mcp.keys()) if k.startswith("carter-")]
                for k in removed:
                    del mcp[k]
                    log_ok(f"Removed {k} from opencode.json")
                data["mcp"] = mcp
                _write_json_preserving(opencode_config, data)
            else:
                log_err("Could not parse opencode.json — skipping to avoid data loss")

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
