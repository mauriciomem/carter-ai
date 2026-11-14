"""Workspace state management — .carter/ directory structure."""

from __future__ import annotations

import contextlib
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from carter.config import write_config
from carter.identity.rules import load_rules
from carter.identity.scrub import scrub_git_env
from carter.identity.trailer import ASSISTED_BY_CARTER
from carter.ops.config import Config

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
            path.write_text(content, encoding="utf-8")


def _git_init(directory: Path) -> None:
    """Initialize a local git repo for state tracking (best-effort)."""
    git_dir = directory / ".git"
    if git_dir.exists():
        return

    _run_git(["init"], directory)
    # init is best-effort; a broken git environment must not abort it
    with contextlib.suppress(StateError):
        commit_state(directory, "chore: init carter state", allow_empty=True)


# Fallback author for state commits, used only when git has no identity (e.g. a bare CI
# runner) so a recovery snapshot never fails for lack of one. The address is on the
# reserved ``.invalid`` TLD: it is deliberately not a real mailbox or a GitHub account.
_STATE_COMMIT_NAME = "Carter"
_STATE_COMMIT_EMAIL = "state@carter.invalid"


def co_author_trailer() -> str:
    """The attribution trailer for commits Carter makes in the state repo.

    ``Assisted-by: Carter`` at T0, ``Co-authored-by: <login> <noreply>`` at T1/T2 (from
    the resolver). A broken config or a refused resolution still yields
    ``Assisted-by: Carter``: a state save is not an agent commit, so it never fails or
    blocks, and it never names an identity it could not resolve.
    """
    return Config.load().coauthor_trailer or ASSISTED_BY_CARTER


class StateError(Exception):
    """A ``.carter/`` git state operation failed unexpectedly.

    Distinct from the legitimate "nothing to commit" no-op, so a failed snapshot
    surfaces loudly instead of being silently reported as "nothing to save".
    """


def state_env(env: Mapping[str, str]) -> dict[str, str]:
    """The environment of Carter's own state commit: scrubbed, and no longer an agent shell.

    The commit guards judge a commit by the agent tag in its environment. A state commit has no
    identity block (the scrub removes it: the commit is the human's and unsigned), so with the tag
    still set the guard would reject it as an agent commit that lacks the block. Dropping the tag
    for this one child process is enough: the call is made by Carter's code, never by the agent,
    and it can only commit in the state repo; every other git command keeps its environment.
    """
    clean = scrub_git_env(env)
    for name in load_rules().agent_signals:
        clean.pop(name, None)
    return clean


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in ``cwd``, capturing output and never raising.

    The only subprocess entry in this module. The environment is scrubbed (a polluted
    shell cannot pick the author, committer, injected config or repository) and signing
    is switched off: state commits are the human's, unsigned, whatever the environment.
    """
    return subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=state_env(os.environ),
        capture_output=True,
        text=True,
        check=False,
    )


def _has_git_identity(cwd: Path) -> bool:
    """Whether git resolves both ``user.name`` and ``user.email`` in ``cwd``."""
    return all(_run_git(["config", key], cwd).stdout.strip() for key in ("user.name", "user.email"))


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

    # The user's git identity is the author; fall back to a bot identity only when
    # none is configured. Carter itself is credited via the co-author trailer.
    identity: list[str] = []
    if not _has_git_identity(carter_dir):
        identity = [
            "-c",
            f"user.name={_STATE_COMMIT_NAME}",
            "-c",
            f"user.email={_STATE_COMMIT_EMAIL}",
        ]
    commit_args = [*identity, "commit", "-m", message, "-m", co_author_trailer()]
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
        content = gitignore.read_text(encoding="utf-8")
        if entry in content:
            return
        if not content.endswith("\n"):
            content += "\n"
        content += f"{entry}\n"
        gitignore.write_text(content, encoding="utf-8")
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")
