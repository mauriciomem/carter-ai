"""Detect Copilot/VS Code leftovers from earlier Carter installs (ADR-0014 D7).

Carter no longer installs into Copilot or VS Code locations. Leftovers are never
deleted by ``carter install``; it only warns once per run. Detection is read-only.
"""

from __future__ import annotations

import platform
from pathlib import Path

from carter.install.console import log_warn
from carter.install.jsonc import _load_jsonc
from carter.install.paths import _copilot_base, _home


def _vscode_settings_files(base_dir: Path | None) -> list[Path]:
    """Candidate VS Code ``settings.json`` files (stable, Insiders, VSCodium, Flatpak)."""
    if base_dir:
        return [base_dir / "vscode" / "settings.json"]
    home = _home()
    if platform.system() == "Darwin":
        root = home / "Library" / "Application Support"
        dirs = [root / "Code", root / "Code - Insiders", root / "VSCodium"]
    else:
        root = home / ".config"
        dirs = [
            root / "Code",
            root / "Code - Insiders",
            root / "VSCodium",
            home / ".var" / "app" / "com.visualstudio.code" / "config" / "Code",
        ]
    return [d / "User" / "settings.json" for d in dirs]


def _has_carter_key(path: Path, key: str) -> bool:
    if not path.is_file():
        return False
    data = _load_jsonc(path)
    section = data.get(key) if isinstance(data, dict) else None
    return isinstance(section, dict) and any(k.startswith("carter-") for k in section)


def find_legacy_copilot(base_dir: Path | None) -> list[Path]:
    """Return Copilot/VS Code locations that still hold Carter-installed content."""
    copilot = _copilot_base(base_dir)
    found: list[Path] = []
    for sub in ("agents", "skills"):
        d = copilot / sub
        if d.is_dir() and any(d.glob("carter-*")):
            found.append(d)
    instructions = copilot / "instructions" / "copilot-instructions.md"
    if instructions.is_file():
        found.append(instructions)
    # Copilot CLI MCP config (written by `copilot mcp add`).
    copilot_mcp = copilot / "mcp-config.json"
    if _has_carter_key(copilot_mcp, "mcpServers"):
        found.append(copilot_mcp)
    found.extend(p for p in _vscode_settings_files(base_dir) if _has_carter_key(p, "mcp.servers"))
    return found


def warn_legacy_copilot(base_dir: Path | None) -> list[Path]:
    """Warn (once) about Copilot/VS Code leftovers. Never deletes anything."""
    found = find_legacy_copilot(base_dir)
    if found:
        shown = ", ".join(str(p).replace(str(_home()), "~") for p in found)
        log_warn(
            f"Copilot/VS Code files from an earlier Carter install are no longer managed: {shown}",
            "They were left in place. Remove them by hand, or with "
            "`carter uninstall --legacy` once a future release ships it.",
        )
    return found
