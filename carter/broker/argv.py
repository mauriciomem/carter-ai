"""Validators and the fixed argv of B's push (RFC-0007 App C.5 "Argv and URL", freeze B11, B13).

The model supplies **nothing** here: ``carter_push`` has no input fields. The URL comes from
``origin``, the branch from ``HEAD``, the sha from ``rev-parse``; everything is still validated,
because a repository's config and a branch name are attacker-influenced data.

Rules (driven by ``tests/data/b_hostile_argv.json``, spike C7/C8):

- the URL matches one of two shapes with ``fullmatch`` (``$`` would accept a trailing newline):
  ``git@github.com:<owner>/<repo>[.git]`` or ``ssh://git@github.com/<owner>/<repo>[.git]``;
  host lower-case, user ``git``, no port, no userinfo, no ``.``/``..`` segment, no leading ``-``;
- an ``http(s)`` origin is ``E-B-HTTPS`` (use A+), every other shape ``E-B-ARGS``;
- the refspec is built here as ``<sha>:refs/heads/<branch>``; a given one is parsed back, with
  no ``+``, no empty source (deletion), no glob, no tag or other namespace, no short name;
- the branch obeys git's ref-name rules and must not start with ``-`` (git would push ``--x``);
- ``--`` precedes the operands, so nothing after it can be an option;
- ``ssh`` is ``<ssh_bin_dir>/ssh`` through ``-c core.sshCommand`` and only the ``ssh`` transport
  is allowed (``protocol.allow=never``, ``protocol.ssh.allow=always``).
"""

from __future__ import annotations

import re
import shlex
import unicodedata
from dataclasses import dataclass

from carter.aplus import run
from carter.broker import refusal
from carter.broker.env import Tools
from carter.identity.errors import E_B_ARGS, E_B_HTTPS, IdentityError

_NAME = r"(?!\.{1,2}[/.]|\.{1,2}$)(?!-)[A-Za-z0-9_.-]+"
_SCP = re.compile(rf"git@github\.com:(?P<owner>{_NAME})/(?P<repo>{_NAME}?)(?:\.git)?")
_SSH = re.compile(rf"ssh://git@github\.com/(?P<owner>{_NAME})/(?P<repo>{_NAME}?)(?:\.git)?")
_HTTP = re.compile(r"https?://", re.IGNORECASE)
_SHA = r"(?:[0-9a-f]{40}|[0-9a-f]{64})"
_REFSPEC = re.compile(rf"(?P<sha>{_SHA}):refs/heads/(?P<branch>[^\n]+)")
_BAD_REF_CHARS = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
MAX_BRANCH = 200
# Belt and braces on top of the config checks: no prompts, no forwarding, no local command.
SSH_OPTIONS = (
    "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", "-o", "ForwardAgent=no",
    "-o", "PermitLocalCommand=no",
)  # fmt: skip


@dataclass(frozen=True)
class RepoUrl:
    owner: str
    repo: str
    url: str

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}"


def _args(detail: str) -> IdentityError:
    return refusal(E_B_ARGS, detail)


def parse_url(url: str) -> RepoUrl:
    """The two allowed SSH shapes; ``E-B-HTTPS`` for http(s), ``E-B-ARGS`` for anything else."""
    for pattern in (_SCP, _SSH):
        match = pattern.fullmatch(url)
        if match and match["repo"] not in (".", ".."):
            return RepoUrl(match["owner"], match["repo"], url)
    if _HTTP.match(url):
        raise refusal(E_B_HTTPS, "origin uses http(s)")
    raise _args(
        "origin is not git@github.com:<owner>/<repo> or ssh://git@github.com/<owner>/<repo>"
    )


def valid_branch(name: str) -> bool:
    """git's ``check-ref-format`` rules for ``refs/heads/<name>`` plus "no leading dash"."""
    if not name or len(name.encode()) > MAX_BRANCH or name.startswith(("-", "/", ".")):
        return False
    if _BAD_REF_CHARS.search(name) or ".." in name or "@{" in name or "//" in name:
        return False
    if any(
        unicodedata.category(c) in ("Cc", "Cf", "Cn", "Co", "Cs", "Zl", "Zp", "Zs") for c in name
    ):
        return False  # bidi overrides and zero-width characters could disguise the prompt (S3)
    if name.endswith(("/", ".", ".lock")) or name == "@":
        return False
    return not any(part.startswith(".") or part.endswith(".lock") for part in name.split("/"))


def require_branch(name: str) -> str:
    if not valid_branch(name):
        raise _args("the current branch name is not a plain branch name")
    return name


def build_refspec(sha: str, branch: str) -> str:
    if not re.fullmatch(_SHA, sha):
        raise _args("the pinned commit is not a full lower-case sha")
    return f"{sha}:refs/heads/{require_branch(branch)}"


def parse_refspec(refspec: str) -> tuple[str, str]:
    """``(sha, branch)`` of a refspec of exactly the shape B builds; anything else is refused."""
    match = _REFSPEC.fullmatch(refspec)
    if not match or not valid_branch(match["branch"]):
        raise _args("the refspec is not <sha>:refs/heads/<branch>")
    return match["sha"], match["branch"]


def ssh_command(tools: Tools) -> str:
    return " ".join([shlex.quote(tools.ssh), *(shlex.quote(a) for a in SSH_OPTIONS)])


def _git(tools: Tools) -> list[str]:
    return [
        tools.git, *run.hardening(),
        "-c", f"core.sshCommand={ssh_command(tools)}",
        "-c", "protocol.allow=never", "-c", "protocol.ssh.allow=always",
        "-c", "push.followTags=false",
        "--no-pager",
    ]  # fmt: skip


def push_argv(tools: Tools, url: RepoUrl, sha: str, branch: str) -> list[str]:
    """The whole ``git push`` command line: fixed, with ``--`` before the operands."""
    return [
        *_git(tools), "push", "--recurse-submodules=no", "--",
        url.url, build_refspec(sha, branch),
    ]  # fmt: skip


def ls_remote_argv(tools: Tools, url: RepoUrl, branch: str) -> list[str]:
    return [*_git(tools), "ls-remote", "--", url.url, f"refs/heads/{require_branch(branch)}"]
