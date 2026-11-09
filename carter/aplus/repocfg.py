"""The repo-config check that `carter push` runs.

``git config --list --show-scope --show-origin --includes`` is judged key by key. The broker refuses
on a finding; `carter push` **shows** it (``Finding`` with ``code = E-B-REPOCFG``) and the
human decides.
The rules, by scope of the key (an included file counts at the including scope, with the
included file as ``origin``):

- **allowlist, any scope:** exactly Carter's own ``include.path`` value(s), ``includeIf``
  targets that point into Carter's fragment directory, and ``hook.carter-guard-*`` keys whose
  origin is Carter's gitconfig. Nothing else under ``include*`` is allowlisted.
- **local / worktree / command:** any exec-capable or routing key (``core.sshCommand``,
  ``core.fsmonitor``, ``core.hooksPath``, pagers, ``core.askPass``, ``credential.*``, ``url.*``,
  ``remote.*.pushurl|receivepack|uploadpack``, ``protocol.*``, ``include*``, ``diff.external``,
  ``filter.*``, ``gpg.program`` and ``gpg.*.program``, ``hook.*``).
- **global:** only what executes or reroutes during an SSH push: ``core.sshCommand``;
  ``url.*.insteadOf|pushInsteadOf`` whose value is a prefix of the origin URL;
  ``remote.origin.*``; ``protocol.*``; ``hook.*`` not owned by Carter. Credential helpers,
  ``http.*``, pagers, ``core.askPass|fsmonitor|hooksPath`` and ``gpg.*program`` are neutralised
  by the hardened calls and not reported. System scope is never read.
- **hook files:** every executable file named after a git hook event in the effective hooks
  directory (``core.hooksPath`` target, else the repository's ``hooks``) that Carter does not
  own. ``*.sample`` files and non-executable files cannot run and are ignored.

A finding names scope, key (URL userinfo masked) and origin file; it never holds a value.
Pure apart from running read-only git commands through ``carter.aplus.run``.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from carter.aplus import run
from carter.aplus.findings import Finding, mask_userinfo, to_error
from carter.identity.errors import E_B_REPOCFG

__all__ = ["CarterOwned", "Finding", "RepoCheckError", "check_repo_config", "to_error"]

_HOOK_NAMES = (
    "applypatch-msg pre-applypatch post-applypatch pre-commit pre-merge-commit "
    "prepare-commit-msg commit-msg post-commit pre-rebase post-checkout post-merge pre-push "
    "pre-receive update proc-receive post-receive post-update reference-transaction "
    "push-to-checkout pre-auto-gc post-rewrite sendemail-validate fsmonitor-watchman "
    "post-index-change"
)
HOOK_EVENTS = frozenset(_HOOK_NAMES.split(" "))
_EXACT = frozenset(
    {
        "core.sshcommand", "core.fsmonitor", "core.hookspath", "core.pager", "core.askpass",
        "diff.external", "gpg.program",
    }
)  # fmt: skip
_PREFIXES = (
    "pager.", "credential.", "url.", "protocol.", "hook.", "filter.", "include.", "includeif.",
)  # fmt: skip
_PATTERNS = (
    re.compile(r"remote\..+\.(pushurl|receivepack|uploadpack)$"),
    re.compile(r"gpg\..+\.program$"),
)
_URL_REWRITE = re.compile(r"url\..+\.(insteadof|pushinsteadof)$")
_ORDER = {"command": 0, "worktree": 1, "local": 2, "global": 3, "system": 4, "hooks": 5}


class RepoCheckError(Exception):
    """The repository could not be inspected (not a repository, git failed)."""


@dataclass(frozen=True)
class CarterOwned:
    """What Carter owns, from guard state (matched exactly, never by pattern)."""

    include: tuple[str, ...] = ()  # the single include.path value(s)
    fragment_dir: str = ""  # directory of the cap fragments
    gitconfig_files: tuple[str, ...] = ()  # Carter's gitconfig file(s) (origin of hook.* entries)
    hook_files: tuple[str, ...] = ()  # hook files Carter installed (per-repo fallback)

    @classmethod
    def from_state(cls, state: object) -> CarterOwned:
        from carter.guard.state import GuardState

        assert isinstance(state, GuardState)
        value = (state.gitconfig or {}).get("value", "")
        hooks = [r["path"] for r in state.repo_hooks]
        return cls(
            include=(value,) if value else (),
            fragment_dir=f"{value}.d" if value else "",
            gitconfig_files=(value,) if value else (),
            hook_files=tuple(hooks),
        )


def _entries(stdout: str) -> list[tuple[str, str, str, str]]:
    """(scope, origin, key, value) from ``git config --list -z --show-scope --show-origin``."""
    parts = stdout.split("\0")
    out = []
    for i in range(0, len(parts) - 2, 3):
        scope, origin, kv = parts[i], parts[i + 1], parts[i + 2]
        key, _, value = kv.partition("\n")
        out.append((scope, origin.removeprefix("file:"), key, value))
    return out


def _in_dir(path: str, directory: str) -> bool:
    return bool(directory) and os.path.normpath(path).startswith(
        os.path.normpath(directory) + os.sep
    )


def _allowed(key: str, value: str, origin: str, owned: CarterOwned) -> bool:
    if key == "include.path":
        return value in owned.include
    if key.startswith("includeif.") and key.endswith(".path"):
        return _in_dir(value, owned.fragment_dir)
    return key.startswith("hook.carter-guard-") and origin in owned.gitconfig_files


def _reason(scope: str, key: str, value: str, origin_url: str | None) -> str | None:
    if scope in ("global", "system"):
        if key == "core.sshcommand":
            return "runs a command for every SSH connection"
        if _URL_REWRITE.fullmatch(key) and origin_url and value and origin_url.startswith(value):
            return "rewrites the origin URL"
        if key.startswith(("remote.origin.", "protocol.", "hook.")):
            return "reroutes or runs code during a push"
        return None
    if key in _EXACT or key.startswith(_PREFIXES) or any(p.fullmatch(key) for p in _PATTERNS):
        return "could run code with your credentials or reroute the push"
    return None


def _hook_findings(
    repo: Path, entries: list[tuple[str, str, str, str]], owned: CarterOwned
) -> list[Finding]:
    configured = [v for _, _, k, v in entries if k == "core.hookspath"]
    if configured:
        directory = Path(os.path.expanduser(configured[-1]))
        if not directory.is_absolute():
            top = run.git(["rev-parse", "--show-toplevel"], repo, harden=False).stdout.strip()
            directory = Path(top or repo) / directory
    else:
        rel = run.git(["rev-parse", "--git-path", "hooks"], repo, harden=False).stdout.strip()
        directory = repo / rel
    found = []
    try:
        names = sorted(directory.iterdir())
    except OSError:
        return []
    for path in names:
        executable = path.is_file() and os.access(path, os.X_OK)
        if path.name in HOOK_EVENTS and executable and str(path) not in owned.hook_files:
            found.append(
                Finding(
                    E_B_REPOCFG,
                    "hooks",
                    path.name,
                    str(path),
                    "a hook of this event runs on push or commit",
                )
            )
    return found


def check_repo_config(
    repo: Path, *, origin_url: str | None = None, owned: CarterOwned | None = None
) -> list[Finding]:
    """Findings for ``repo`` (empty = clean), sorted by scope then key. Read-only."""
    owned = owned or CarterOwned()
    probe = run.git(["rev-parse", "--git-dir"], repo)
    if probe.returncode != 0:
        raise RepoCheckError("not a git repository")
    listing = run.git(
        ["config", "--list", "-z", "--show-scope", "--show-origin", "--includes"],
        repo,
        harden=False,
    )
    if listing.returncode != 0:
        raise RepoCheckError(f"git config failed ({listing.returncode})")
    entries = _entries(listing.stdout)
    found: list[Finding] = []
    for scope, origin, key, value in entries:
        if _allowed(key, value, origin, owned):
            continue
        reason = _reason(scope, key, value, origin_url)
        if reason:
            found.append(Finding(E_B_REPOCFG, scope, mask_userinfo(key), origin, reason))
    found += _hook_findings(repo, entries, owned)
    return sorted(set(found), key=lambda f: (_ORDER.get(f.scope, 9), f.key, f.origin))
