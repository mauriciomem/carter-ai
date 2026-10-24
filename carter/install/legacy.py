"""Detect Copilot/VS Code leftovers from earlier Carter installs (ADR-0014 D7).

Carter no longer installs into Copilot or VS Code locations. Leftovers are never
deleted by ``carter install``; it only warns once per run. ``carter uninstall
--legacy`` removes only what the old install manifest lists.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

from carter.install.console import _log, log_err, log_ok, log_step, log_warn
from carter.install.jsonc import _load_jsonc, _write_json_preserving
from carter.install.paths import _copilot_base, _home, legacy_manifest_path


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
            "They were left in place. Run `carter uninstall --legacy` to remove the "
            "Carter-installed ones (only files listed in the old install manifest).",
        )
    return found


def _hash_matches(path: Path, recorded: str) -> bool:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return recorded.removeprefix("sha256:") == digest


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path.is_relative_to(r) for r in roots)


def _remove_json_entries(path: Path, key: str, names: list[str]) -> None:
    if not path.is_file():
        return
    data = _load_jsonc(path)
    if data is None:
        log_err(f"Could not parse {_tilde(path)} — skipped to avoid data loss")
        return
    section = data.get(key)
    if not isinstance(section, dict):
        return
    removed = [n for n in names if n in section]
    if not removed:
        return
    for n in removed:
        del section[n]
    _write_json_preserving(path, data)
    for n in removed:
        log_ok(f"Removed {n} from {_tilde(path)}")


def _tilde(p: Path) -> str:
    return str(p).replace(str(_home()), "~")


def uninstall_legacy(base_dir: Path | None) -> None:
    """Remove Carter files an old install put in Copilot/VS Code locations (D7).

    Only entries listed in the old ``~/.copilot/.carter-manifest.json`` are touched.
    Files whose content no longer matches the recorded hash were edited by the user
    and are kept. Old manifests without hashes restrict deletion to ``carter-*``
    names. Without an old manifest nothing is deleted; leftovers are only listed.
    """
    log_step("Removing Copilot/VS Code leftovers from an earlier Carter install...")
    manifest_file = legacy_manifest_path(base_dir)
    if not manifest_file.is_file():
        found = find_legacy_copilot(base_dir)
        log_warn(
            f"No old install manifest at {_tilde(manifest_file)}. Nothing was deleted.",
            "Carter only removes files it can prove it installed.",
        )
        if found:
            _log("  Remove these by hand if they hold Carter content:")
            for p in found:
                _log(f"    {_tilde(p)}")
        return

    from carter.install.components import normalize_manifest

    manifest = normalize_manifest(json.loads(manifest_file.read_text()))
    copilot = _copilot_base(base_dir)
    roots = (copilot / "agents", copilot / "skills", copilot / "instructions")
    hashes: dict[str, str] = manifest["file_hashes"]
    if not hashes:
        log_warn(
            "The old manifest has no content hashes: only carter-* files it lists are removed.",
            "Other listed files are left in place.",
        )

    removed_any = False
    for entry in manifest["files"]:
        path = Path(entry)
        if not _within(path, roots) or not path.is_file():
            continue
        recorded = hashes.get(entry)
        if hashes:
            if recorded is None or not _hash_matches(path, recorded):
                log_warn(f"Kept {_tilde(path)}: edited since install (or no recorded hash)")
                continue
        elif not any(part.startswith("carter-") for part in path.relative_to(copilot).parts):
            log_warn(f"Kept {_tilde(path)}: not carter-* named and no hash to verify it")
            continue
        path.unlink()
        removed_any = True
        log_ok(f"Removed {_tilde(path)}")
        # Drop now-empty carter-* skill directories (never the roots themselves).
        parent = path.parent
        while parent not in roots and _within(parent, roots) and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent

    names = [n for n in manifest["mcp_servers"] if n.startswith("carter-")]
    if names:
        _remove_json_entries(copilot / "mcp-config.json", "mcpServers", names)
        for settings in _vscode_settings_files(base_dir):
            _remove_json_entries(settings, "mcp.servers", names)

    if not removed_any and not names:
        log_ok("Nothing to remove")
    _log(
        f"  The old manifest and {_tilde(copilot / 'knowledge')} are kept "
        "(knowledge was copied to ~/.carter)."
    )
