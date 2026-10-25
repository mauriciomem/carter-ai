"""MCP server wiring for OpenCode V2.

Carter servers are written under ``mcp.servers.<name>`` in the global
``opencode.json`` (https://opencode.ai/v2/docs/mcp-servers/). V1 fields are
normalized per https://opencode.ai/v2/docs/migrate-v1/: ``enabled`` becomes the
inverse ``disabled`` and a scalar ``timeout`` becomes ``{catalog, execution}``.
A V1 ``mcp.<carter-name>`` entry left by an older Carter is replaced by the V2
entry, so the two forms never conflict.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from carter.install.console import log_err, log_ok, log_step, log_warn
from carter.install.files import _backup_file
from carter.install.jsonc import _load_jsonc, _write_json
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
    _write_json(file_path, data)
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
        _write_json(file_path, data)
    return removed


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

    wired: list[str] = []
    if entries and merge_mcp_servers(
        _opencode_base(base_dir) / "opencode.json", entries, backup_root
    ):
        wired = list(entries)
        for name in wired:
            log_ok(f"{name} → opencode.json (mcp.servers)")
    manifest["mcp_servers"] = wired
    return len(wired)
