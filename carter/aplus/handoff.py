"""The A+ handoff file: the only input of ``carter pr`` (RFC-0007 C.6.6, freeze F11).

An agent that has finished a branch writes ``.carter/state/handoff/<encoded-branch>.md``
with its own file tools; the human then runs ``carter push`` and ``carter pr`` in their own
terminal. The file is **untrusted input** from a model, so this parser returns only a small
typed model (never argv, flags or anything from the file that could become a command line),
refuses unknown keys, caps the sizes, and refuses YAML aliases and tags before anything is
expanded.

Front matter keys, exactly: ``title`` (str), ``base`` (str), ``draft`` (bool), ``head_sha``
(40 lowercase hex) and ``repo`` (``owner/name``). ``<encoded-branch>`` percent-encodes ``%``
then ``/`` and nothing else (``feat/x`` → ``feat%2Fx``). Errors are ``E-HANDOFF`` whose
``detail`` names keys, never values.
"""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

import yaml

from carter.identity.errors import E_HANDOFF, IdentityError
from carter.install.atomic import atomic_write_bytes
from carter.plans import parse_frontmatter

HANDOFF_SUBDIR = Path(".carter") / "state" / "handoff"
KEYS = ("title", "base", "draft", "head_sha", "repo")
MAX_FILE_BYTES = 1 << 20  # 1 MiB: a PR body, not a data store
MAX_FRONT_MATTER_BYTES = 4096
MAX_NAME_BYTES = 200  # encoded branch, leaving room for ".md" under every filesystem's 255
MAX_TITLE = 256

# The one place the "run it yourself" sentence lives (steps 19, 20, 23 and the skill use it).
# Spike 2 (does `!` give a TTY?) is still open, so per C.6.6 it names only the human's own
# terminal and never suggests a leading `!`.
OWN_TERMINAL = "Run `carter push` and then `carter pr` in your own terminal, not through an agent."

_SHA = re.compile(r"[0-9a-f]{40}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_BAD_REF_CHARS = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
_ESCAPE = {"%25": "%", "%2F": "/"}


def _err(detail: str) -> IdentityError:
    return IdentityError(E_HANDOFF, detail=detail)


def _check_ref(name: str, what: str) -> str:
    """A git-ref-shaped name (git's own ``check-ref-format`` rules, the ones that matter here)."""
    bad = (
        not name
        or len(name.encode()) > MAX_NAME_BYTES
        or _BAD_REF_CHARS.search(name)
        or ".." in name
        or "@{" in name
        or "//" in name
        or name in ("@",)
        or name.startswith(("/", "-", "."))
        or name.endswith(("/", ".", ".lock"))
        or any(part.startswith(".") or part.endswith(".lock") for part in name.split("/"))
    )
    if bad:
        raise _err(f"{what} is not a safe branch name")
    return name


def encode_branch(branch: str) -> str:
    """``feat/x`` → ``feat%2Fx`` (``%`` first, then ``/``); unsafe names are refused."""
    return _check_ref(branch, "branch").replace("%", "%25").replace("/", "%2F")


def decode_branch(encoded: str) -> str:
    """Inverse of ``encode_branch``; only ``%25`` and ``%2F`` are valid escapes."""
    if not encoded:
        raise _err("empty handoff name")
    out: list[str] = []
    i = 0
    while i < len(encoded):
        if encoded[i] == "%":
            piece = encoded[i : i + 3]
            if piece not in _ESCAPE:
                raise _err("bad escape in handoff name")
            out.append(_ESCAPE[piece])
            i += 3
        else:
            out.append(encoded[i])
            i += 1
    return _check_ref("".join(out), "branch")


def handoff_filename(branch: str) -> str:
    return f"{encode_branch(branch)}.md"


def handoff_path(workspace: Path, branch: str) -> Path:
    return workspace / HANDOFF_SUBDIR / handoff_filename(branch)


@dataclass(frozen=True)
class Handoff:
    title: str
    base: str
    draft: bool
    head_sha: str
    repo: str
    body: str = ""


def _front_matter_block(text: str) -> str:
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        raise _err("no front matter")
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[1:i])
    raise _err("front matter is not closed")


def _refuse_aliases(block: str) -> None:
    """Aliases and anchors can expand exponentially ("billion laughs"); events are lazy,
    so this scan never builds the structure."""
    try:
        for event in yaml.parse(block):
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
                raise _err("YAML aliases and anchors are not allowed")
    except yaml.YAMLError as exc:
        raise _err("front matter is not valid YAML") from exc


def _text(value: object, key: str, *, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _err(f"{key} must be a non-empty string")
    if len(value) > limit or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        raise _err(f"{key} must be one printable line of at most {limit} characters")
    return value


def parse_handoff(text: str) -> tuple[Handoff, list[str]]:
    """Parse a handoff file. Returns ``(model, warnings)``; raises ``IdentityError(E-HANDOFF)``."""
    if len(text.encode()) > MAX_FILE_BYTES:
        raise _err("file is too large")
    text = text.removeprefix("\ufeff").replace("\r\n", "\n")
    block = _front_matter_block(text)
    if len(block.encode()) > MAX_FRONT_MATTER_BYTES:
        raise _err("front matter is too large")
    _refuse_aliases(block)
    data = parse_frontmatter(text)
    if data is None:
        raise _err("front matter is not a valid mapping")
    unknown = sorted(str(k)[:40] for k in data if k not in KEYS)
    if unknown:
        raise _err(f"unknown key(s): {', '.join(unknown)}")
    missing = [k for k in KEYS if k not in data]
    if missing:
        raise _err(f"missing key(s): {', '.join(missing)}")
    if not isinstance(data["draft"], bool):
        raise _err("draft must be true or false")
    sha, repo = data["head_sha"], data["repo"]
    if not (isinstance(sha, str) and _SHA.fullmatch(sha)):
        raise _err("head_sha must be 40 lowercase hex characters")
    if not (isinstance(repo, str) and _REPO.fullmatch(repo) and ".." not in repo):
        raise _err("repo must be owner/name")
    base = _check_ref(_text(data["base"], "base", limit=MAX_NAME_BYTES), "base")
    body = text.split("\n---", 1)[1].split("\n", 1)[1] if "\n---" in text else ""
    model = Handoff(
        title=_text(data["title"], "title", limit=MAX_TITLE),
        base=base,
        draft=data["draft"],
        head_sha=sha,
        repo=repo,
        body=body.lstrip("\n"),
    )
    return model, []


def read_handoff(workspace: Path, branch: str) -> Handoff:
    """Read and validate the handoff for ``branch`` (a regular, non-symlink, size-capped file)."""
    path = handoff_path(workspace, branch)
    try:
        st = path.lstat()
    except OSError as exc:
        raise _err("no handoff file for this branch") from exc
    if not stat.S_ISREG(st.st_mode):
        raise _err("handoff is not a regular file")
    if st.st_size > MAX_FILE_BYTES:
        raise _err("file is too large")
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise _err("handoff is not readable UTF-8") from exc
    return parse_handoff(text)[0]


def render_handoff(item: Handoff) -> str:
    def quote(value: str) -> str:
        return (
            yaml.safe_dump(value, default_flow_style=True, width=10_000).split("\n...")[0].strip()
        )

    front = "\n".join(
        [
            "---",
            f"title: {quote(item.title)}",
            f"base: {quote(item.base)}",
            f"draft: {'true' if item.draft else 'false'}",
            f"head_sha: {item.head_sha}",
            f"repo: {item.repo}",
            "---",
        ]
    )
    return f"{front}\n\n{item.body}"


def write_handoff(workspace: Path, branch: str, item: Handoff) -> Path:
    """Write the handoff atomically, mode 0600 (for tests and docs; agents use their own tools)."""
    path = handoff_path(workspace, branch)
    return atomic_write_bytes(path, render_handoff(item).encode())


def delete_after_success(workspace: Path, branch: str, *, success: bool) -> bool:
    """Delete exactly this branch's handoff, only when ``success is True``; never via a link."""
    if success is not True:
        return False
    path = handoff_path(workspace, branch)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return False
        os.unlink(path)
    except OSError:
        return False
    return True


def handoff_template(branch: str, repo: str, head_sha: str, *, base: str = "main") -> str:
    """What the agent-facing skill shows: a valid handoff with the PR text left to fill in."""
    encode_branch(branch)  # validates
    item = Handoff("TITLE: one line, Conventional Commits style", base, False, head_sha, repo)
    return render_handoff(Handoff(**{**item.__dict__, "body": "PR description in Markdown.\n"}))
