"""The human behind a role-b commit: who they are, whether the identity is usable, and whether
GitHub can credit it (role ``author``).

In role ``author`` the LLM is author and committer and the human is credited by
``Co-authored-by: <user.name> <user.email>``. That line is built from the human's own git config,
read in the working directory (``includeIf`` overrides respected). Never from ``git var``, which
returns the LLM inside a role-b shell, and never pasted unchecked: a raw ``user.name`` can hold a
newline, a ``<``, or be a Carter fallback.

Stdlib-only (the plugin's entry imports this). ``validate`` is the one definition of "usable";
the rendered guard script repeats it in POSIX sh and ``tests/data/human_identity_vectors.json``
holds both to the same answers. The link state and its cache are in ``coauthor_link``
(re-exported here).
"""

from __future__ import annotations

import fnmatch
import subprocess
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from carter.identity.rules import human_identity_rules

PROBLEMS = ("missing-name", "missing-email", "bad-name", "bad-email", "llm-email", "fallback")
GIT_TIMEOUT = (
    5  # seconds: the entry's whole budget is 2 s per call; a hung git must not hold a shell
)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Human:
    """The human's ``user.name`` / ``user.email`` as git reports them in one directory.

    ``problem`` is ``""`` for a usable identity, else one of ``PROBLEMS``. The values are kept
    even when invalid so a caller can say *which* is wrong (never printed with the problem)."""

    name: str
    email: str
    problem: str

    @property
    def ok(self) -> bool:
        return not self.problem

    @property
    def trailer(self) -> str:
        """``Co-authored-by: <name> <email>``, or ``""`` for an unusable identity."""
        return "" if self.problem else f"Co-authored-by: {self.name} <{self.email}>"


def _has_control(text: str) -> bool:
    return any(unicodedata.category(ch) == "Cc" for ch in text)


def validate(name: str, email: str, llm_email: str) -> str:
    """``""`` when the pair can credit a human, else the first problem (order of ``PROBLEMS``).

    ``llm_email`` is the LLM's noreply address; the human must not be the LLM. Emails compare
    after ``casefold()``."""
    if not name.strip():
        return "missing-name"
    if not email.strip():
        return "missing-email"
    if name != name.strip() or _has_control(name) or "<" in name or ">" in name:
        return "bad-name"
    if (
        _has_control(email)
        or any(ch.isspace() for ch in email)
        or "<" in email
        or ">" in email
        or email.count("@") != 1
        or email.startswith("@")
        or email.endswith("@")
    ):
        return "bad-email"
    folded = email.casefold()
    if llm_email and folded == llm_email.casefold():
        return "llm-email"
    rules = human_identity_rules()
    if any(fnmatch.fnmatchcase(folded, pat.casefold()) for pat in rules["fallback_emails"]):
        return "fallback"
    if any(
        name.casefold() == n.casefold() and folded == e.casefold()
        for n, e in rules["fallback_pairs"]
    ):  # the state-commit pair only: a person named Carter, or that address alone, is valid
        return "fallback"
    return ""


def read_git_user(
    cwd: str | Path, env: Mapping[str, str] | None = None, run: Runner | None = None
) -> tuple[str, str]:
    """``(user.name, user.email)`` as ``git config`` reports them in ``cwd``; ``""`` for a missing
    one. One call, NUL-separated so a value with a newline stays one value. The last value wins
    (git's own precedence). ``GIT_AUTHOR_*`` and the signing block do not affect ``user.*``."""
    runner = run or subprocess.run
    try:
        done = runner(
            ["git", "-C", str(cwd), "config", "-z", "--get-regexp", r"^user\.(name|email)$"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=GIT_TIMEOUT,
            env=None if env is None else dict(env),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "", ""
    values: dict[str, str] = {}
    for record in done.stdout.split("\0") if done.returncode == 0 else []:
        key, _, value = record.partition("\n")
        if key in ("user.name", "user.email"):
            values[key] = value
    return values.get("user.name", ""), values.get("user.email", "")


def human_identity(
    cwd: str | Path,
    llm_email: str,
    env: Mapping[str, str] | None = None,
    run: Runner | None = None,
) -> Human:
    """Read and validate the human identity for ``cwd`` (a directory that exists or not: git
    then falls back to the global config)."""
    name, email = read_git_user(cwd if Path(cwd).is_dir() else Path.home(), env, run)
    return Human(name, email, validate(name, email, llm_email))


# The link state and its cache live in ``coauthor_link``; the names stay importable from here.
from carter.identity.coauthor_link import (  # noqa: E402
    LINK_CACHE_REL,
    LINK_CACHE_TTL_S,
    LINK_STATES,
    cache_path,
    cached_link,
    check_link,
    email_key,
    gh_user_emails,
    noreply_parts,
    record_link,
    refresh_link,
)

__all__ = [
    "GIT_TIMEOUT", "LINK_CACHE_REL", "LINK_CACHE_TTL_S", "LINK_STATES", "PROBLEMS", "Human",
    "cache_path", "cached_link", "check_link", "email_key", "gh_user_emails", "human_identity",
    "noreply_parts", "read_git_user", "record_link", "refresh_link", "validate",
]  # fmt: skip
