"""``carter pr``: open a pull request from the agent's handoff file (RFC-0007 C.6.6, App B).

Human terminal only (the click layer enforces it before this module runs). The input is the
one file ``.carter/state/handoff/<encoded-branch>.md`` for the current branch, which is
**untrusted** (an agent wrote it): ``carter.aplus.handoff`` returns a typed model, and Carter
builds the ``gh`` command line itself. Every value goes in as ``--flag=value`` (one argv
element), so a title like ``--web`` or a body that starts with ``-`` cannot become an option;
the body travels in a 0600 temporary file, never on the command line.

Order: read the handoff (``head_sha`` must be an ancestor of HEAD) → secret scan of title,
branch and body → find the PR target (the parent if origin is a fork) → check the branch is on
origin at HEAD, offering ``carter push`` if not → show title, target, base and the first 40
body lines → ``y/N`` → ``gh pr create``. The handoff file is deleted only after ``gh``
succeeded; on any failure it stays.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from carter.aplus import handoff, protection, push, run, secretscan
from carter.aplus.findings import mask_userinfo
from carter.identity.errors import E_APLUS_ARGS, E_HANDOFF, IdentityError

BODY_PREVIEW_LINES = 40
_SLUG = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_PART = re.compile(r"[A-Za-z0-9_.-]+")


def _args(detail: str) -> IdentityError:
    return IdentityError(E_APLUS_ARGS, detail=detail)


def _out(repo: Path, args: list[str]) -> str | None:
    proc = run.git(args, repo, harden=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _read(workspace: Path, branch: str) -> handoff.Handoff:
    try:
        return handoff.read_handoff(workspace, branch)
    except IdentityError as exc:
        if exc.code != E_HANDOFF:
            raise
        expected = f"{handoff.HANDOFF_SUBDIR}/{handoff.handoff_filename(branch)}"
        raise IdentityError(E_HANDOFF, detail=f"{exc.detail}; expected {expected}") from exc


def _parent_slug(raw: str) -> str | None:
    """``owner/name`` of the fork's parent from ``gh repo view --json parent`` output."""
    try:
        parent = json.loads(raw).get("parent")
        owner, name = parent["owner"]["login"], parent["name"]
    except (ValueError, AttributeError, KeyError, TypeError):
        return None
    if isinstance(owner, str) and isinstance(name, str) and _PART.fullmatch(owner + name):
        return f"{owner}/{name}"
    return None


def _gh_lines(stderr: str, limit: int = 5) -> str:
    text = mask_userinfo(stderr.strip())
    return " | ".join(push.clean(line, 200) for line in text.splitlines()[:limit])


def _target(repo: Path, item: handoff.Handoff, branch: str, io: push.Io) -> tuple[str, str]:
    """``(target repo, --head value)``: the parent and ``owner:branch`` for a fork."""
    url = _out(repo, ["remote", "get-url", push.REMOTE]) or ""
    slug = protection.github_slug(url)
    owner = item.repo.split("/")[0]
    if slug is None:
        io.echo("notice: origin is not on github.com, so the handoff's repo was not cross-checked")
    elif f"{slug[0]}/{slug[1]}".lower() != item.repo.lower():
        raise IdentityError(E_HANDOFF, detail="repo in the handoff is not the repo of origin")
    view = run.gh(["repo", "view", item.repo, "--json", "parent"], repo)
    if view.returncode != 0:
        raise _args(f"gh could not read {item.repo} ({_gh_lines(view.stderr)})")
    parent = _parent_slug(view.stdout)
    return (parent, f"{owner}:{branch}") if parent else (item.repo, branch)


def _on_origin(repo: Path, branch: str) -> bool:
    """Is ``branch`` on origin at HEAD? (``ls-remote`` with your credentials; no fetch.)"""
    head = _out(repo, ["rev-parse", "HEAD"])
    proc = run.network_git(["ls-remote", "--heads", push.REMOTE, f"refs/heads/{branch}"], repo)
    if proc.returncode != 0:
        raise _args(f"cannot reach origin ({mask_userinfo(push.clean(proc.stderr.strip(), 200))})")
    return bool(head) and proc.stdout.split()[:1] == [head]


def _preview(item: handoff.Handoff, target: str, head: str, io: push.Io) -> None:
    lines = item.body.rstrip("\n").splitlines()
    io.echo(f"Title:  {push.clean(item.title, 256)}")
    io.echo(f"Target: {target}   Base: {push.clean(item.base)}   Head: {push.clean(head)}")
    io.echo(f"Draft:  {'yes' if item.draft else 'no'}")
    io.echo("Body:")
    for line in lines[:BODY_PREVIEW_LINES]:
        io.echo(f"  {push.clean(line, 200)}")
    if len(lines) > BODY_PREVIEW_LINES:
        io.echo(f"  ... ({len(lines) - BODY_PREVIEW_LINES} more line(s) not shown)")


def build_argv(item: handoff.Handoff, target: str, head: str, body_file: Path) -> list[str]:
    """The ``gh pr create`` arguments (without the executable). One element per flag."""
    argv = [
        "pr", "create",
        f"--repo={target}",
        f"--head={head}",
        f"--base={item.base}",
        f"--title={item.title}",
        f"--body-file={body_file}",
    ]  # fmt: skip
    return [*argv, "--draft"] if item.draft else argv


def _create(repo: Path, item: handoff.Handoff, target: str, head: str) -> tuple[bool, str]:
    scratch = Path(tempfile.mkdtemp(prefix="carter-pr-"))
    try:
        scratch.chmod(0o700)
        body = scratch / "body.md"
        fd = os.open(body, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(item.body)
        proc = run.gh(build_argv(item, target, head, body), repo)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        return False, _gh_lines(proc.stderr)
    return True, proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""


def run_pr(repo: Path, io: push.Io, *, base_dir: Path | None = None) -> int:
    """0 = created, 1 = declined or failed. Raises ``IdentityError`` for the expected refusals."""
    try:
        return _flow(repo, io, base_dir)
    except run.RunError as exc:
        raise _args(str(exc)) from exc


def _flow(repo: Path, io: push.Io, base_dir: Path | None) -> int:
    workspace = _out(repo, ["rev-parse", "--show-toplevel"])
    branch = _out(repo, ["symbolic-ref", "--short", "-q", "HEAD"])
    if workspace is None:
        raise _args("not a git repository")
    if not branch:
        raise _args("detached HEAD: check out the branch of the pull request")
    root = Path(workspace)
    item = _read(root, branch)
    ancestor = run.git(["merge-base", "--is-ancestor", item.head_sha, "HEAD"], root, harden=False)
    if ancestor.returncode != 0:
        raise IdentityError(E_HANDOFF, detail="head_sha is not an ancestor of HEAD")
    if error := secretscan.to_error(secretscan.scan(item.title, branch, item.body)):
        raise error  # before any gh call; the file stays
    leaked = [v for v in run.GH_TOKEN_VARS if v in os.environ]
    if leaked:
        io.echo(
            f"notice: {', '.join(leaked)} is set, so gh uses it instead of your `gh auth login`"
        )
    target, head = _target(root, item, branch, io)
    url = _out(root, ["remote", "get-url", "--push", push.REMOTE])
    if url is None:
        raise _args(f"no remote named {push.REMOTE}")
    home = Path.home()
    _cfg, stop = push.vet_local(root, url, io, base_dir=base_dir, home=home)
    if stop is not None:
        return stop
    if not _on_origin(root, branch):
        io.echo(
            f"{branch} is not on {push.REMOTE} at HEAD: running the `carter push` checks first."
        )
        if push.run_push(root, push.Options(), io, base_dir=base_dir) != 0:
            io.echo("Aborted: no pull request was created; the handoff is kept.")
            return 1
    _preview(item, target, head, io)
    if not push.confirmed(io, "Create this pull request? [y/N] "):
        io.echo("Aborted: no pull request was created; the handoff is kept.")
        return 1
    ok, detail = _create(root, item, target, head)
    if not ok:
        io.echo(f"gh pr create failed ({detail}). The handoff is kept.")
        return 1
    handoff.delete_after_success(root, branch, success=True)
    io.echo(f"Created: {mask_userinfo(push.clean(detail, 300))}")
    return 0


__all__ = ["BODY_PREVIEW_LINES", "build_argv", "run_pr"]
