"""MCP server wiring for OpenCode V2.

Carter servers are written under ``mcp.servers.<name>`` in the global
``opencode.json`` (https://opencode.ai/v2/docs/mcp-servers/). V1 fields are
normalized per https://opencode.ai/v2/docs/migrate-v1/: ``enabled`` becomes the
inverse ``disabled`` and a scalar ``timeout`` becomes ``{catalog, execution}``.
A V1 ``mcp.<carter-name>`` entry left by an older Carter is replaced by the V2
entry, so the two forms never conflict.

The global config may be ``opencode.json`` or ``opencode.jsonc``
(https://opencode.ai/v2/docs/config/#locations). OpenCode 2.1 loads both when
both exist, ``opencode.json`` first and ``opencode.jsonc`` second, so the
``.jsonc`` file wins. Carter writes to ``opencode.jsonc`` whenever it exists
and keeps its servers out of the other file.

Rewriting a file drops its comments. When the original has comments, it is
copied to ``<name>.carter-backup`` next to it first, and a warning is printed.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from carter.home import tilde
from carter.install.console import log_err, log_ok, log_step, log_warn
from carter.install.files import _backup_file
from carter.install.jsonc import _load_jsonc, _write_json, has_comments
from carter.install.paths import REPO_ROOT, _opencode_base

# The MCP servers Carter ships. Single source of truth so the install and
# uninstall paths can never diverge.
MCP_SERVERS = ("github", "terraform", "atlassian")

# Keys under `mcp` that are V2 structure, never V1 server names.
_V2_MCP_KEYS = frozenset({"servers", "timeout"})


def to_v2_server(entry: dict[str, Any]) -> dict[str, Any]:
    """Return ``entry`` in the V2 server shape (``disabled``, timeout object)."""
    out = dict(entry)
    if "enabled" in out:
        enabled = out.pop("enabled")
        if enabled is False:
            out["disabled"] = True
    timeout = out.get("timeout")
    if isinstance(timeout, int) and not isinstance(timeout, bool):
        out["timeout"] = {"catalog": timeout, "execution": timeout}
    return out


BACKUP_SUFFIX = ".carter-backup"


def global_config_files(base_dir: Path | None) -> tuple[Path, Path]:
    """Return the ``(opencode.json, opencode.jsonc)`` paths of the global config."""
    base = _opencode_base(base_dir)
    return base / "opencode.json", base / "opencode.jsonc"


def config_target(base_dir: Path | None) -> Path:
    """The file Carter writes MCP servers to: ``opencode.jsonc`` if it exists."""
    json_path, jsonc_path = global_config_files(base_dir)
    return jsonc_path if jsonc_path.exists() else json_path


def _save_config(file_path: Path, data: dict) -> None:
    """Write ``data``; first keep a sibling copy of an original with comments."""
    if file_path.exists() and has_comments(file_path.read_text()):
        backup = file_path.with_name(file_path.name + BACKUP_SUFFIX)
        shutil.copy2(file_path, backup)
        log_warn(
            f"{file_path.name} had comments; rewriting it does not keep them",
            f"Original saved as {tilde(backup)}",
        )
    _write_json(file_path, data)


def _load_config(file_path: Path) -> dict | None:
    if not file_path.exists():
        return {}
    loaded = _load_jsonc(file_path)
    if loaded is None:
        log_err(f"Could not parse {file_path} — skipping to avoid data loss")
        log_warn(
            "The file may contain syntax errors. Fix them and re-run the installer.",
            f"File: {file_path}",
        )
    return loaded


def merge_mcp_servers(
    file_path: Path, entries: dict[str, dict[str, Any]], backup_root: Path | None = None
) -> bool:
    """Merge ``entries`` into ``mcp.servers`` of an OpenCode config file.

    Unrelated keys (and unrelated servers, V1 or V2) are preserved. A V1
    ``mcp.<name>`` entry with the same name as a Carter entry is removed: the V2
    entry replaces it. Returns False (file untouched) when the file can't be parsed.
    """
    data = _load_config(file_path)
    if data is None:
        return False
    if file_path.exists() and backup_root:
        _backup_file(file_path, backup_root)

    mcp = data.setdefault("mcp", {})
    servers = mcp.setdefault("servers", {})
    for name, entry in entries.items():
        if name in mcp and name not in _V2_MCP_KEYS:
            del mcp[name]
            log_ok(f"Migrated {name} from V1 mcp.{name} to mcp.servers.{name}")
        base_name = name.removeprefix("carter-")
        if base_name in servers or base_name in mcp:
            log_warn(
                f'Existing "{base_name}" server found in {file_path.name}',
                f'Carter will install as "{name}" (separate entry). '
                f'You may want to remove "{base_name}" to avoid duplicate tools.',
            )
        servers[name] = to_v2_server(entry)
    _save_config(file_path, data)
    return True


def remove_carter_servers(file_path: Path) -> list[str]:
    """Remove every ``carter-*`` server (V2 ``mcp.servers`` and V1 ``mcp``)."""
    if not file_path.exists():
        return []
    data = _load_config(file_path)
    if data is None:
        return []
    mcp = data.get("mcp")
    if not isinstance(mcp, dict):
        return []
    removed = [k for k in list(mcp) if k.startswith("carter-")]
    for k in removed:
        del mcp[k]
    servers = mcp.get("servers")
    if isinstance(servers, dict):
        for k in [k for k in list(servers) if k.startswith("carter-")]:
            del servers[k]
            removed.append(k)
    if removed:
        _save_config(file_path, data)
    return removed


def _carter_server_names(file_path: Path) -> set[str]:
    data = _load_jsonc(file_path) if file_path.exists() else None
    mcp = data.get("mcp") if isinstance(data, dict) else None
    if not isinstance(mcp, dict):
        return set()
    names = {k for k in mcp if k.startswith("carter-")}
    servers = mcp.get("servers")
    if isinstance(servers, dict):
        names |= {k for k in servers if k.startswith("carter-")}
    return names


def configure_mcp_servers(
    base_dir: Path | None,
    manifest: dict,
    backup_root: Path | None = None,
    servers: list[str] | None = None,
) -> int:
    """Wire the selected Carter MCP servers into the global OpenCode config.

    ``servers`` is the opt-in subset of ``MCP_SERVERS``; ``None`` means all of
    them. An unknown server name is a ``ValueError``.
    """
    log_step("Configuring MCP servers...")
    if servers is None:
        servers = list(MCP_SERVERS)
    unknown = [s for s in servers if s not in MCP_SERVERS]
    if unknown:
        raise ValueError(
            f"Unknown MCP server(s): {', '.join(unknown)}. Choose from: {', '.join(MCP_SERVERS)}."
        )

    entries: dict[str, dict[str, Any]] = {}
    for server in servers:
        src = REPO_ROOT / "mcp" / "opencode" / f"{server}.json"
        if not src.is_file():
            log_warn(f"carter-{server}: not available for opencode")
            continue
        entries.update(json.loads(src.read_text()))

    json_path, jsonc_path = global_config_files(base_dir)
    target = config_target(base_dir)
    if entries and json_path.exists() and jsonc_path.exists():
        log_warn(
            "Both opencode.json and opencode.jsonc exist; OpenCode loads both",
            "Carter uses opencode.jsonc (loaded last) and keeps its servers out of "
            "opencode.json. Consider merging them into one file.",
        )
        stale = [k for k in entries if k in _carter_server_names(json_path)]
        if stale:
            if backup_root:
                _backup_file(json_path, backup_root)
            for name in remove_carter_servers(json_path):
                log_ok(f"Removed {name} from opencode.json (now in opencode.jsonc)")

    wired: list[str] = []
    if entries and merge_mcp_servers(target, entries, backup_root):
        wired = list(entries)
        for name in wired:
            log_ok(f"{name} → {target.name} (mcp.servers)")
    manifest["mcp_servers"] = wired
    return len(wired)
