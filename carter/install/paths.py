"""Filesystem path resolution for the installer.

Every install target's base directory is resolved here. A ``base_dir`` override
(used by tests) redirects all writes into a temp tree instead of the real home.
"""

from __future__ import annotations

from pathlib import Path

from carter.resources import data_dir

# Source of the bundled data files (agents/skills/mcp/...). Resolves the same way
# from a dev checkout and an installed wheel (carter/_data/).
REPO_ROOT = data_dir()


def _home() -> Path:
    return Path.home()


def _copilot_base(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "copilot"
    return _home() / ".copilot"


def _opencode_base(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "opencode"
    return _home() / ".config" / "opencode"


def _carter_base(base_dir: Path | None) -> Path:
    """Return the carter home directory (~/.carter or base_dir/carter)."""
    if base_dir:
        return base_dir / "carter"
    return _home() / ".carter"


def _local_bin(base_dir: Path | None) -> Path:
    """Return the local bin directory (~/.local/bin or base_dir/local/bin)."""
    if base_dir:
        return base_dir / "local" / "bin"
    return _home() / ".local" / "bin"


# Carter-owned state (ADR-0014 D3). Earlier versions kept these under ~/.copilot:
#   ~/.copilot/knowledge/            → ~/.carter/knowledge/
#   ~/.copilot/.carter-manifest.json → ~/.carter/manifest.json
#   ~/.copilot/backup/<timestamp>/   → ~/.carter/backups/<timestamp>/
def knowledge_dir(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "knowledge"


def manifest_path(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "manifest.json"


def backups_dir(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "backups"


def legacy_manifest_path(base_dir: Path | None) -> Path:
    """The manifest pre-ADR-0014 installs wrote under ~/.copilot (read-only now)."""
    return _copilot_base(base_dir) / ".carter-manifest.json"
