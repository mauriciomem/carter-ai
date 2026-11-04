"""Filesystem path resolution for the installer.

Every directory the installer reads or writes is resolved here. A ``base_dir``
override (used by tests) redirects all writes into a temp tree instead of the
real home.
"""

from __future__ import annotations

from pathlib import Path

from carter.home import carter_home
from carter.resources import data_dir

# Source of the bundled data files (agents/skills/mcp/...). Resolves the same way
# from a dev checkout and an installed wheel (carter/_data/).
REPO_ROOT = data_dir()


def _home() -> Path:
    return Path.home()


def _opencode_base(base_dir: Path | None) -> Path:
    if base_dir:
        return base_dir / "opencode"
    return _home() / ".config" / "opencode"


def _carter_base(base_dir: Path | None) -> Path:
    """Return the carter home directory (~/.carter or base_dir/carter)."""
    if base_dir:
        return base_dir / "carter"
    return carter_home()


# Carter-owned state under ~/.carter.
def knowledge_dir(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "knowledge"


def manifest_path(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "manifest.json"


def backups_dir(base_dir: Path | None) -> Path:
    return _carter_base(base_dir) / "backups"


def guard_state_path(base_dir: Path | None) -> Path:
    """``~/.carter/guard-state.json``: G2 ownership, kept apart from ``manifest.json``."""
    return _carter_base(base_dir) / "guard-state.json"


def carter_gitconfig_path(base_dir: Path | None) -> Path:
    """``~/.carter/gitconfig``: every global git key Carter owns (D61), included by one line."""
    return _carter_base(base_dir) / "gitconfig"


def guard_script_path(base_dir: Path | None) -> Path:
    """``~/.carter/hooks/carter-guard``: the one POSIX guard script every hook calls."""
    return _carter_base(base_dir) / "hooks" / "carter-guard"


def managed_roots(base_dir: Path | None) -> tuple[Path, ...]:
    """Directories whose files uninstall may delete (path-component containment, resolved).

    ``~/.carter/{bin,hooks,run}`` are listed for the files slice 2a installs there; in 1G they
    hold nothing. ``guard remove`` deletes its own files by code, not through these roots."""
    carter = _carter_base(base_dir)
    return tuple(
        p.resolve()
        for p in (
            _opencode_base(base_dir),
            knowledge_dir(base_dir),
            carter / "bin",
            carter / "hooks",
            carter / "run",
        )
    )


def token_path(base_dir: Path | None) -> Path:
    """``~/.carter/secrets/gh-read.token``: the read-only fine-grained PAT (App C.7)."""
    return _carter_base(base_dir) / "secrets" / "gh-read.token"


def carter_config_path(base_dir: Path | None) -> Path:
    """``~/.carter/config.toml``: the identity and ``[github]`` settings."""
    return _carter_base(base_dir) / "config.toml"
