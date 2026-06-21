"""Locate Carter's bundled data files.

Carter ships static content (agents, skills, instructions, knowledge, MCP
configs, and templates) that must be available both when running from a repo
checkout (development) and when installed as a wheel via ``uv tool install``.

In an installed wheel the data lives at ``carter/_data/``. In a development
checkout it lives at the repository root. ``data_dir()`` resolves whichever
layout is present so callers can simply use ``data_dir() / "agents"`` etc.
"""

from __future__ import annotations

from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent


def data_dir() -> Path:
    """Return the directory containing Carter's bundled data subdirectories.

    Resolution order:
      1. ``carter/_data/`` — present in an installed wheel (force-included).
      2. The repository root — present in a development checkout.

    Raises:
        FileNotFoundError: if neither layout can be located.
    """
    packaged = _PACKAGE_DIR / "_data"
    if packaged.is_dir():
        return packaged

    repo_root = _PACKAGE_DIR.parent
    if (repo_root / "agents").is_dir():
        return repo_root

    raise FileNotFoundError(
        "Could not locate Carter data files. Expected either "
        f"{packaged} (installed) or {repo_root}/agents (development checkout)."
    )


def templates_dir() -> Path:
    """Return the directory containing Jinja2 templates."""
    return data_dir() / "templates"
