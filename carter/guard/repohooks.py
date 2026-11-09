"""Per-repo ``pre-push`` fallback for git older than 2.54.

Without config-based hooks the backstop is a ``.git/hooks/pre-push`` file in each repo: the same
fail-safe wrapper as the config hook (``hooks.repo_hook_text``), calling ``carter-guard``.

Rules:

- Carter writes a repo hook only where ``pre-push`` is absent or **Carter-owned** (it is recorded in
  ``repo_hooks`` with its hash and still has it). A foreign or edited hook, or a repo with
  ``core.hooksPath`` (husky, pre-commit, a global hooksPath), is reported ``unguarded`` with a
  snippet to chain by hand. Carter never edits ``.husky/`` or ``.pre-commit-config.yaml``.
- ``init.templateDir`` covers new clones and inits. It is single-valued, so Carter sets it (in
  ``~/.carter/gitconfig``) only if the user has none; otherwise it prints the chain snippet and
  reports ``unguarded: templateDir`` for new clones.
- When git >= 2.54 appears the config hook covers every repo, and the owned, unchanged repo hooks
  are removed. ``other_old_gits`` finds older git binaries that would still need them.
- Only the human-run ``carter guard install`` reaches this code. An agent shell cannot write
  ``.git/hooks`` (edit-denied and gate-denied), and the reads here change nothing.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from carter.guard import gitconfig, hooks
from carter.guard.state import GuardState
from carter.install.atomic import atomic_write_bytes

HOOK = "pre-push"
MIN_CONFIG_HOOKS = (2, 54)
TEMPLATE_KEY = "init.templateDir"


@dataclass
class RepoStatus:
    repo: Path
    state: Literal["guarded", "installable", "unguarded"]
    reason: str = ""
    hook: Path | None = None
    snippet: str = ""

    def line(self) -> str:
        what = "guarded" if self.state == "guarded" else f"unguarded: {self.reason or 'no hook'}"
        return f"{self.repo}: {what}"


def _git(args: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return gitconfig.run_git(args, cwd=cwd)


def toplevel(path: Path) -> Path | None:
    """The work tree root of the repository containing ``path`` (None: not a repository)."""
    if not path.is_dir():
        return None
    done = _git(["rev-parse", "--show-toplevel"], path)
    return Path(done.stdout.strip()) if done.returncode == 0 and done.stdout.strip() else None


def hooks_dir(repo: Path) -> Path | None:
    done = _git(["rev-parse", "--git-path", "hooks"], repo)
    if done.returncode != 0 or not done.stdout.strip():
        return None
    return repo / done.stdout.strip()  # absolute when git says so; repo-relative otherwise


def hooks_path_setting(repo: Path) -> str:
    """``core.hooksPath`` as the repo sees it (any scope: husky sets it locally, some people
    globally). Empty when unset."""
    done = _git(["config", "--get", "core.hooksPath"], repo)
    return done.stdout.strip() if done.returncode == 0 else ""


def chain_snippet(script: Path, event: str = HOOK) -> str:
    """Lines for the human to add to a hook Carter does not own."""
    quoted = shlex.quote(str(script))
    env = ""
    if event != HOOK:  # the commit events read the tier mirror from Carter's own git file
        env = f"CARTER_GUARD_CONFIG={shlex.quote(str(script.parent.parent / 'gitconfig'))} "
    what = "agent-push guard" if event == HOOK else "agent-commit guard"
    return f'[ -x {quoted} ] && {{ {env}{quoted} {event} "$@" || exit 1; }}   # Carter: {what}'


def inspect(repo: Path, state: GuardState, base_dir: Path | None, event: str = HOOK) -> RepoStatus:
    """Where ``repo`` stands for one hook event. Read-only."""
    script = hooks.script_path(base_dir)
    directory = hooks_dir(repo)
    if directory is None:
        return RepoStatus(repo, "unguarded", "not a repository")
    hook = directory / event
    if setting := hooks_path_setting(repo):
        snippet = (
            f"core.hooksPath is {setting}: add this to its {event} hook:\n"
            f"  {chain_snippet(script, event)}"
        )
        return RepoStatus(repo, "unguarded", "hooksPath", hook, snippet)
    if not hook.exists() and not hook.is_symlink():
        return RepoStatus(repo, "installable", "not installed", hook)
    if state.repo_hook_unchanged(hook):
        return RepoStatus(repo, "guarded", "", hook)
    owned = any(h["path"] == str(hook) for h in state.repo_hooks)
    reason = "edited hook" if owned else "foreign hook"
    return RepoStatus(
        repo, "unguarded", reason, hook, f"add this to {hook}:\n  {chain_snippet(script, event)}"
    )


def install(repo: Path, state: GuardState, base_dir: Path | None, event: str = HOOK) -> RepoStatus:
    """Write the owned hook if (and only if) ``inspect`` says ``installable``."""
    found = inspect(repo, state, base_dir, event)
    if found.state != "installable" or found.hook is None:
        return found
    data = hooks.repo_hook_text(hooks.script_path(base_dir), event).encode()
    atomic_write_bytes(found.hook, data, mode=0o755, dir_mode=0o755)
    state.record_repo_hook(found.hook, data)
    return RepoStatus(repo, "guarded", "", found.hook)


def scan(
    repos: Iterable[Path],
    state: GuardState,
    base_dir: Path | None,
    events: Sequence[str] = (HOOK,),
) -> list[RepoStatus]:
    """Status of each repo and event for ``check --host``: an uninstalled repo is unguarded too."""
    return [inspect(r, state, base_dir, event) for r in repos for event in events]


def verdict(statuses: Sequence[RepoStatus], tier: str) -> Literal["ok", "warn", "fail"]:
    """Unguarded repos are a warning; while T2 is set they are a FAIL (E-GIT-OLD remediation)."""
    if all(s.state == "guarded" for s in statuses):
        return "ok"
    return "fail" if tier == "t2" else "warn"


def repos_in_scope(cwd: Path, workspaces: Iterable[str]) -> list[Path]:
    """The repo containing ``cwd`` plus each configured workspace that is itself a repository."""
    found: list[Path] = []
    for candidate in [cwd, *(Path(w).expanduser() for w in workspaces)]:
        top = toplevel(candidate)
        if top is not None and top.resolve() not in {f.resolve() for f in found}:
            found.append(top)
    return found


# -- init.templateDir ---------------------------------------------------------------------


@dataclass
class TemplatePlan:
    status: Literal["set", "ours", "kept-user-value"]
    directory: Path
    snippet: str = ""


def template_dir(base_dir: Path | None) -> Path:
    return hooks.script_path(base_dir).parent / "template"


def plan_template(global_config: Path, base_dir: Path | None) -> TemplatePlan:
    """Single-valued key: ours only if the user has none (includes followed)."""
    directory = template_dir(base_dir)
    have = gitconfig._file_git(str(global_config), "--includes", "--get", TEMPLATE_KEY)
    if have.returncode == 0 and have.stdout.strip() == str(directory):
        return TemplatePlan("ours", directory)
    if have.returncode == 0:
        theirs = have.stdout.strip()
        snippet = (
            f"{TEMPLATE_KEY} is already set ({theirs}); Carter kept it. New clones are NOT "
            f"guarded: copy {directory / 'hooks' / HOOK} into {theirs}/hooks/ "
            f"(or chain: {chain_snippet(hooks.script_path(base_dir))})"
        )
        return TemplatePlan("kept-user-value", directory, snippet)
    return TemplatePlan("set", directory)


def install_template(
    base_dir: Path | None, state: GuardState, events: Sequence[str] = (HOOK,)
) -> str:
    """Write ``<template>/hooks/<event>`` (0755, hash-tracked like the other Carter files).

    Returns the status of the first event (they are written together)."""
    script = hooks.script_path(base_dir)
    statuses = [
        gitconfig.install_file(
            template_dir(base_dir) / "hooks" / event,
            hooks.repo_hook_text(script, event),
            state,
            mode=0o755,
        )
        for event in events
    ]
    return statuses[0]


# -- removal -----------------------------------------------------------------


@dataclass
class Removal:
    removed: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)  # changed since, or not ours: left in place


def remove_owned(state: GuardState) -> Removal:
    """Delete each recorded repo hook that still has its recorded hash; keep the others."""
    out = Removal()
    for rec in list(state.repo_hooks):
        path = Path(rec["path"])
        if state.repo_hook_unchanged(path):
            path.unlink()
            out.removed.append(str(path))
        elif path.exists():
            out.kept.append(str(path))
        state.forget_repo_hook(path)
    return out


def git_version(binary: str) -> tuple[int, int] | None:
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else None


def other_old_gits(env: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """Git binaries on PATH (and the usual system paths) older than 2.54: ``(path, version)``.

    ``check`` warns about them once git is upgraded: a repo reached through such a git has no
    config hook, and its owned repo hook was removed."""
    environment = os.environ if env is None else env
    dirs = [d for d in environment.get("PATH", "").split(os.pathsep) if d]
    dirs += ["/usr/bin", "/usr/local/bin", "/opt/homebrew/bin"]
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for directory in dirs:
        candidate = os.path.join(directory, "git")
        if not (os.path.isfile(candidate) and os.access(candidate, os.X_OK)):
            continue
        real = os.path.realpath(candidate)
        if real in seen:
            continue
        seen.add(real)
        version = git_version(candidate)
        if version is not None and version < MIN_CONFIG_HOOKS:
            out.append((candidate, f"{version[0]}.{version[1]}"))
    return out
