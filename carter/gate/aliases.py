"""Git alias resolution (RFC-0007 C.4.2 rule 7, freeze G6).

Git ignores an alias that is named like a built-in command, so the lookup is needed only for the
other subcommands. The lookup is ``git config --get-regexp '^alias\\.'`` run in the effective
directory (``-C`` honoured); ``subprocess`` is imported only here, on that path (spike F: 6 ms).
No directory known means no lookup, and the caller then refuses a non-built-in subcommand.
A missing git, a timeout or a failing lookup mean "no aliases": never a crash, never a deny.
"""

from __future__ import annotations

import os

BUILTINS = frozenset(
    [
        "add",
        "am",
        "annotate",
        "apply",
        "archive",
        "bisect",
        "blame",
        "branch",
        "bundle",
        "cat-file",
        "check-attr",
        "check-ignore",
        "checkout",
        "checkout-index",
        "cherry",
        "cherry-pick",
        "clean",
        "clone",
        "column",
        "commit",
        "commit-graph",
        "commit-tree",
        "config",
        "count-objects",
        "credential",
        "describe",
        "diff",
        "diff-files",
        "diff-index",
        "diff-tree",
        "difftool",
        "fast-export",
        "fast-import",
        "fetch",
        "fetch-pack",
        "filter-branch",
        "fmt-merge-msg",
        "for-each-ref",
        "for-each-repo",
        "format-patch",
        "fsck",
        "gc",
        "get-tar-commit-id",
        "grep",
        "gui",
        "hash-object",
        "help",
        "hook",
        "http-backend",
        "http-fetch",
        "http-push",
        "index-pack",
        "init",
        "interpret-trailers",
        "log",
        "ls-files",
        "ls-remote",
        "ls-tree",
        "mailinfo",
        "mailsplit",
        "maintenance",
        "merge",
        "merge-base",
        "merge-file",
        "merge-index",
        "merge-tree",
        "mergetool",
        "mktag",
        "mktree",
        "multi-pack-index",
        "mv",
        "name-rev",
        "notes",
        "pack-objects",
        "pack-redundant",
        "pack-refs",
        "patch-id",
        "prune",
        "prune-packed",
        "pull",
        "push",
        "range-diff",
        "read-tree",
        "rebase",
        "receive-pack",
        "reflog",
        "remote",
        "repack",
        "replace",
        "request-pull",
        "rerere",
        "reset",
        "restore",
        "rev-list",
        "rev-parse",
        "revert",
        "rm",
        "send-email",
        "send-pack",
        "shell",
        "shortlog",
        "show",
        "show-branch",
        "show-index",
        "show-ref",
        "sparse-checkout",
        "stash",
        "status",
        "stripspace",
        "submodule",
        "switch",
        "symbolic-ref",
        "tag",
        "unpack-file",
        "unpack-objects",
        "update-index",
        "update-ref",
        "update-server-info",
        "var",
        "verify-commit",
        "verify-pack",
        "verify-tag",
        "version",
        "whatchanged",
        "worktree",
        "write-tree",
    ]
)


def is_builtin(sub: str) -> bool:
    return sub in BUILTINS


def lookup(directory: str, extra: dict[str, str]) -> dict[str, str]:
    """Aliases visible from ``directory``; ``extra`` are the ``-c alias.*`` values."""
    found: dict[str, str] = {}
    if os.path.isdir(directory):
        try:
            import subprocess  # noqa: PLC0415 - lazy: 6 ms, needed only for non-built-in subcommands

            done = subprocess.run(
                ["git", "-C", directory, "config", "--get-regexp", r"^alias\."],
                capture_output=True,
                text=True,
                timeout=1.0,
                stdin=subprocess.DEVNULL,
            )
            for line in done.stdout.splitlines() if done.returncode == 0 else ():
                key, _, value = line.partition(" ")
                found[key[len("alias.") :].lower()] = value
        except Exception:  # noqa: BLE001 - git missing, timeout, bad directory: no aliases
            found = {}
    found.update({k.lower(): v for k, v in extra.items()})
    return found
