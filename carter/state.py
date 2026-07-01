"""Workspace state management — .carter/ directory structure."""

from __future__ import annotations

import contextlib
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
    """Initialize a local git repo for state tracking (best-effort)."""
    git_dir = directory / ".git"
    if git_dir.exists():
        return

    _run_git(["init"], directory)
    # init is best-effort; a broken git environment must not abort it
    with contextlib.suppress(StateError):
        commit_state(directory, "chore: init carter state", allow_empty=True)


# Identity for automated state commits — these are local recovery snapshots, not
# authored work, so they carry a stable bot identity (and avoid failing on a
# machine/CI with no global git user configured).
_STATE_COMMIT_NAME = "carter"
_STATE_COMMIT_EMAIL = "carter-bot@users.noreply.github.com"


class StateError(Exception):
    """A ``.carter/`` git state operation failed unexpectedly.

    Distinct from the legitimate "nothing to commit" no-op, so a failed snapshot
    surfaces loudly instead of being silently reported as "nothing to save".
    """


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd``, capturing output and never raising."""
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def commit_state(carter_dir: Path, message: str, *, allow_empty: bool = False) -> bool:
    """Commit the ``.carter/`` state repo — the workspace recovery primitive.

    Stages everything and commits to the nested ``.carter/.git`` so deleted
    plans/sessions are recoverable from history. Returns ``True`` if a commit was
    made, ``False`` if there is no nested repo (e.g. ``--no-git-state``) or there
    is nothing to commit (and ``allow_empty`` is False).

    Raises ``StateError`` if a git operation fails unexpectedly (e.g. ``git add``
    errors), so a failed snapshot is never mistaken for "nothing to commit".
    """
    if not (carter_dir / ".git").exists():
        return False

    add = _run_git(["add", "-A"], carter_dir)
    if add.returncode != 0:
        raise StateError(f"git add failed in {carter_dir}: {add.stderr.strip()}")

    if not allow_empty:
        # `diff --cached --quiet` exits 0 = nothing staged, 1 = staged changes,
        # >1 = git error.
        diff = _run_git(["diff", "--cached", "--quiet"], carter_dir)
        if diff.returncode == 0:
            return False
        if diff.returncode != 1:
            raise StateError(f"git diff failed in {carter_dir}: {diff.stderr.strip()}")

    commit_args = [
        "-c",
        f"user.name={_STATE_COMMIT_NAME}",
        "-c",
        f"user.email={_STATE_COMMIT_EMAIL}",
        "commit",
        "-m",
        message,
    ]
    if allow_empty:
        commit_args.append("--allow-empty")
    commit = _run_git(commit_args, carter_dir)
    if commit.returncode != 0:
        raise StateError(f"git commit failed in {carter_dir}: {commit.stderr.strip()}")
    return True


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
