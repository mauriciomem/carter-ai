"""Workspace state management — .carter/ directory structure."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from carter.config import write_config

KNOWLEDGE_FILES: dict[str, str] = {
    "lessons-learned.md": """\
# Lessons Learned

> **PERMANENT FILE — append only, never remove entries.**
> Universal truths discovered through experience.
> Entries can be annotated with [SUPERSEDED] but never deleted.

## Categories: Agent behavior | Development patterns | Tool-specific | Security
""",
    "gotchas.md": """\
# Known Issues & Workarounds

> Workspace-specific issues and their workarounds.
> Entries can be removed when the underlying issue is fixed.
""",
    "tools.md": """\
# Available Tools

> Tools, CLIs, MCP servers, and auth methods in this workspace.

## Always Available

| Tool | Purpose | Auth |
|------|---------|------|
""",
    "decisions.md": """\
# Architecture Decisions

> Key decisions with rationale. Append new decisions; mark old ones [SUPERSEDED] if reversed.
""",
    "patterns.md": """\
# Patterns & Conventions

> Recurring patterns established in this workspace.
""",
}


def init_workspace(
    target_dir: Path,
    config: dict[str, Any],
    git_state: bool = True,
) -> Path:
    """Create .carter/ directory structure and write initial config.

    Returns the path to the .carter/ directory.
    """
    carter_dir = target_dir / ".carter"
    carter_dir.mkdir(parents=True, exist_ok=True)

    # State directories
    state_dir = carter_dir / "state"
    (state_dir / "plans" / "active").mkdir(parents=True, exist_ok=True)
    (state_dir / "plans" / "completed").mkdir(parents=True, exist_ok=True)
    (state_dir / "sessions").mkdir(parents=True, exist_ok=True)

    # Knowledge directory
    knowledge_dir = carter_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    _init_knowledge_files(knowledge_dir)

    # Write config
    config_path = carter_dir / "carter.yaml"
    if not config_path.exists():
        write_config(config_path, config)

    # Optional git init for state tracking
    if git_state:
        _git_init(carter_dir)

    return carter_dir


def _init_knowledge_files(knowledge_dir: Path) -> None:
    """Create knowledge files if they don't already exist."""
    for filename, content in KNOWLEDGE_FILES.items():
        path = knowledge_dir / filename
        if not path.exists():
            path.write_text(content)


def _git_init(directory: Path) -> None:
    """Initialize a local git repo for state tracking."""
    git_dir = directory / ".git"
    if git_dir.exists():
        return

    subprocess.run(
        ["git", "init"],
        cwd=directory,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "add", "-A"],
        cwd=directory,
        capture_output=True,
        check=False,
    )
    subprocess.run(
        ["git", "commit", "-m", "chore: init carter state", "--allow-empty"],
        cwd=directory,
        capture_output=True,
        check=False,
    )


def add_to_gitignore(target_dir: Path, entry: str = ".carter/") -> None:
    """Add an entry to .gitignore if not already present."""
    gitignore = target_dir / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if entry in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content)
    else:
        gitignore.write_text(f"{entry}\n")
