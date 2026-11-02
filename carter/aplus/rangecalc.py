"""The commit range ``carter push`` shows and checks (RFC-0007 App C.6.6).

Base = ``origin/<branch>`` if that remote-tracking branch exists, else
``merge-base(origin/HEAD, HEAD)``. The branch's configured upstream is deliberately **not**
used: in a fork flow it often tracks ``upstream/main``, which is not where this push lands.
There is no network call here; ``carter push`` fetches the target ref first.

Also lists which paths in the range can run code on someone's machine or in CI (``.husky/``,
``.githooks/``, the ``core.hooksPath`` target, ``.pre-commit-config.yaml``, ``lefthook.*``,
``.github/workflows/``), counting renames (both paths) and deletions, so A+ can show them in
red. A detached HEAD, a missing ``origin`` or a missing base are ``E-APLUS-ARGS``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from carter.aplus import run
from carter.identity.errors import E_APLUS_ARGS, IdentityError

_DIR_NAMES = (".husky", ".githooks")
_BASENAME = re.compile(r"(?:\.?lefthook\.[A-Za-z0-9]+|\.pre-commit-config\.yaml)$")


@dataclass(frozen=True)
class Change:
    status: str  # A M D R C T
    path: str
    old_path: str = ""


@dataclass(frozen=True)
class RangeInfo:
    branch: str
    base: str  # sha
    base_ref: str
    commits: tuple[str, ...]  # oldest first
    changes: tuple[Change, ...]
    sensitive: tuple[Change, ...]
    new_branch: bool
    fast_forward: bool

    @property
    def base_label(self) -> str:
        return f"as of {self.base_ref}"


def _err(detail: str) -> IdentityError:
    return IdentityError(E_APLUS_ARGS, detail=detail)


def _is_sensitive(path: str, hooks_path: str | None) -> bool:
    parts = path.split("/")
    if any(part in _DIR_NAMES for part in parts[:-1]):
        return True
    if path.startswith(".github/workflows/") or _BASENAME.fullmatch(parts[-1]):
        return True
    if hooks_path:
        prefix = hooks_path.strip("/") + "/"
        return path.startswith(prefix)
    return False


def sensitive_paths(changes: tuple[Change, ...], *, hooks_path: str | None = None) -> list[Change]:
    """The changes touching a hook or CI location (either side of a rename)."""
    return [
        c
        for c in changes
        if _is_sensitive(c.path, hooks_path)
        or (c.old_path and _is_sensitive(c.old_path, hooks_path))
    ]


def _name_status(stdout: str) -> tuple[Change, ...]:
    tokens = stdout.split("\0")
    changes, i = [], 0
    while i < len(tokens) and tokens[i]:
        status = tokens[i][0]
        if status in "RC":
            changes.append(Change(status, tokens[i + 2], tokens[i + 1]))
            i += 3
        else:
            changes.append(Change(status, tokens[i + 1]))
            i += 2
    return tuple(changes)


def _ok(repo: Path, args: list[str]) -> str | None:
    proc = run.git(args, repo, harden=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def compute_range(repo: Path) -> RangeInfo:
    """The range for the current branch of ``repo`` (read-only, no network)."""
    if _ok(repo, ["rev-parse", "--git-dir"]) is None:
        raise _err("not a git repository")
    branch = _ok(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if not branch:
        raise _err("detached HEAD")
    if _ok(repo, ["remote", "get-url", "origin"]) is None:
        raise _err("no remote named origin")
    on_remote = _ok(repo, ["rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}"])
    if on_remote:
        base, base_ref, new_branch = on_remote, f"origin/{branch}", False
    else:
        if _ok(repo, ["rev-parse", "--verify", "-q", "refs/remotes/origin/HEAD"]) is None:
            raise _err("origin/HEAD is not set (run: git remote set-head origin --auto)")
        base = _ok(repo, ["merge-base", "origin/HEAD", "HEAD"]) or ""
        if not base:
            raise _err("no common ancestor with origin/HEAD")
        base_ref, new_branch = "merge-base(origin/HEAD, HEAD)", True
    commits = _ok(repo, ["rev-list", "--reverse", f"{base}..HEAD"]) or ""
    listing = run.git(["diff", "--name-status", "-M", "-z", base, "HEAD"], repo, harden=False)
    changes = _name_status(listing.stdout)
    hooks = _ok(repo, ["config", "--get", "core.hooksPath"])
    fast_forward = (
        run.git(["merge-base", "--is-ancestor", base, "HEAD"], repo, harden=False).returncode == 0
    )
    return RangeInfo(
        branch=branch,
        base=base,
        base_ref=base_ref,
        commits=tuple(commits.split()),
        changes=changes,
        sensitive=tuple(sensitive_paths(changes, hooks_path=hooks)),
        new_branch=new_branch,
        fast_forward=fast_forward,
    )
