"""MCP server config constants + JSON merge.

The actual wiring (``configure_mcp_servers``) lives in ``carter.installer`` because
it resolves ``_vscode_detected`` through that namespace (test monkeypatching); this
module holds the single-source server list and the JSON-key merge primitive.
"""

from __future__ import annotations

from pathlib import Path

from carter.install.console import log_err, log_warn
from carter.install.files import _backup_file
from carter.install.jsonc import _load_jsonc, _write_json_preserving

# The MCP servers Carter wires into every target. Single source of truth so the
# install and uninstall paths can never diverge (RFC-0002 / ADR-0005 D5).
MCP_SERVERS = ("github", "terraform", "atlassian")


def _merge_json_key(
    file_path: Path, key: str, entries: dict, backup_root: Path | None = None
) -> None:
    """Merge entries into a specific key of a JSON file.

    Handles JSONC (JSON with Comments) used by VS Code settings.json.
    Backs up the file before any modification.
    """
    data: dict = {}
    if file_path.exists():
        # Back up before modifying
        if backup_root:
            _backup_file(file_path, backup_root)

        loaded = _load_jsonc(file_path)
        if loaded is None:
            log_err(f"Could not parse {file_path} — skipping to avoid data loss")
            log_warn(
                "The file may contain syntax errors. Fix them and re-run the installer.",
                f"File: {file_path}",
            )
            return
        data = loaded

    if key not in data:
        data[key] = {}

    # Check for non-carter conflicts
    for name in entries:
        base_name = name.replace("carter-", "")
        if base_name in data.get(key, {}) and name not in data.get(key, {}):
            log_warn(
                f'Existing "{base_name}" server found in {file_path.name}',
                f'Carter will install as "{name}" (separate entry). '
                f'You may want to remove "{base_name}" to avoid duplicate tools.',
            )

    data[key].update(entries)
    _write_json_preserving(file_path, data)
