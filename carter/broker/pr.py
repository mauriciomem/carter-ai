"""``broker pr --plan|--exec``: open a pull request from the handoff file (App C.5, C.6.6, B12).

``carter_pr`` never pushes. Its only input is ``.carter/state/handoff/<encoded-branch>.md`` for
the current branch (the 1G parser: typed model, quoted title, size caps); the model supplies no
argument. Plan (no network, no credential) refuses, with registry codes:

handoff missing or malformed / ``head_sha`` not an ancestor of HEAD (``E-HANDOFF``) -> a secret in
the title, the branch name or the body (``E-SECRET-SCAN``) -> an ``origin`` that is not the
handoff's repo, or a branch that is not on origin at HEAD (``E-B-ARGS``: "run ``carter_push``
first or ``carter push``"; the local ``origin/<branch>`` tracking ref is what says so, which a B
push and ``carter push`` both update).

Exec re-runs all of it, resolves the PR target (the parent if ``origin`` is a fork; this is the
one network call, with the per-verb ``pr`` environment) and runs ``gh`` by absolute path with
``--repo=``, ``--head=``, ``--base=``, ``--title=`` and ``--body-file=`` as one argv element each
(a title of ``--web`` stays data). ``gh`` runs in a fresh 0700 scratch directory, never in the
repository, so no repository config can reach it. The body goes in a 0600 file there. The handoff
is deleted only after ``gh`` succeeded.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carter.aplus import handoff, run, secretscan
from carter.aplus.findings import mask_userinfo
from carter.aplus.pr import BODY_PREVIEW_LINES, _parent_slug, build_argv
from carter.broker import argv as argvmod
from carter.broker import checks, env, execute, plan, refusal
from carter.broker.plan import SHORT, Caller, clean
from carter.identity.errors import E_B_ARGS, E_B_MOVED, E_HANDOFF, IdentityError

GH_TIMEOUT = 60.0
PREVIEW_LINE_CHARS = 200
ASK_BODY_LINES = 10


@dataclass(frozen=True)
class PrPlan:
    toplevel: Path
    branch: str
    item: handoff.Handoff
    head: str


def _git(args: list[str], repo: Path) -> str | None:
    proc = run.git(args, repo)
    return proc.stdout.strip() if proc.returncode == 0 else None


def build_pr_plan(
    cwd: Path, ctx: checks.Context, caller: Caller, server: Mapping[str, str]
) -> PrPlan:
    plan.admit(caller, ctx)
    env.check_tools(ctx.tools, need_gh=True)
    with run.forced_env(plan.read_env(server, ctx)):
        try:
            return _pr_plan(cwd)
        except run.RunError as exc:
            raise refusal(E_B_ARGS, str(exc)) from exc


def _pr_plan(cwd: Path) -> PrPlan:
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    if not top:
        raise refusal(E_B_ARGS, "the session directory is not a git repository")
    repo = Path(top)
    branch = argvmod.require_branch(_git(["symbolic-ref", "--short", "-q", "HEAD"], repo) or "")
    try:
        item = handoff.read_handoff(repo, branch)
    except IdentityError as exc:
        if exc.code != E_HANDOFF:
            raise
        expected = f"{handoff.HANDOFF_SUBDIR}/{handoff.handoff_filename(branch)}"
        raise IdentityError(E_HANDOFF, detail=f"{exc.detail}; expected {expected}") from exc
    head = _git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], repo) or ""
    if run.git(["merge-base", "--is-ancestor", item.head_sha, "HEAD"], repo).returncode != 0:
        raise IdentityError(E_HANDOFF, detail="head_sha is not an ancestor of HEAD")
    findings = secretscan.scan(item.title, branch, item.body)
    if error := secretscan.to_error(findings):
        raise error
    _cross_check_origin(repo, item)
    tracking = _git(["rev-parse", "--verify", "-q", f"refs/remotes/origin/{branch}"], repo)
    if tracking != head:
        raise refusal(
            E_B_ARGS,
            f"{branch} is not on origin at HEAD: run `carter_push` first, or `carter push` "
            "in your own terminal",
        )
    return PrPlan(repo, branch, item, head)


def _cross_check_origin(repo: Path, item: handoff.Handoff) -> None:
    from carter.aplus import protection  # noqa: PLC0415 - heavier imports only when needed

    origin = _git(["remote", "get-url", "origin"], repo)
    slug = protection.github_slug(origin) if origin else None
    if slug is None:
        raise refusal(E_B_ARGS, "origin is not a github.com repository")
    if f"{slug[0]}/{slug[1]}".lower() != item.repo.lower():
        raise IdentityError(E_HANDOFF, detail="repo in the handoff is not the repo of origin")


def pr_ask(p: PrPlan, caller: Caller) -> dict[str, Any]:
    body = [
        clean(ln, PREVIEW_LINE_CHARS)
        for ln in p.item.body.rstrip("\n").splitlines()[:ASK_BODY_LINES]
    ]
    resources = [
        f"pr create {p.item.repo} {p.branch} -> {clean(p.item.base, 80)}"
        + (" (draft)" if p.item.draft else ""),
        f"title: {clean(p.item.title, 256)}",
        *body,
    ]
    return {
        "resources": resources,
        "metadata": {
            "verb": "pr",
            "caller": clean(caller.agent, 40),
            "session": clean(caller.session, 80),
            "pinned": p.head[:SHORT],
        },
    }


def pr_plan_json(p: PrPlan, ctx: checks.Context, caller: Caller) -> dict[str, Any]:
    lines = p.item.body.rstrip("\n").splitlines()
    return {
        "verb": "pr",
        "repo": p.item.repo,
        "branch": p.branch,
        "base": clean(p.item.base, 200),
        "title": clean(p.item.title, 256),
        "draft": p.item.draft,
        "head_sha": p.item.head_sha,
        "pinned_sha": p.head,
        "body_preview": [clean(ln, PREVIEW_LINE_CHARS) for ln in lines[:BODY_PREVIEW_LINES]],
        "body_lines": len(lines),
        "approval": plan.approval(ctx),
        "ask": pr_ask(p, caller),
        "audit": {
            "owner_repo": p.item.repo,
            "branch": p.branch,
            "range": f"{p.item.head_sha[:SHORT]}..{p.head[:SHORT]}",
            "commits": 0,
            "verb": "pr",
        },
    }


def _gh(
    ctx: checks.Context, args: list[str], cwd: Path, child: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [ctx.tools.gh, *args], cwd=cwd, env=child, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=GH_TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise refusal(E_B_ARGS, f"gh did not finish within {GH_TIMEOUT:g} s") from exc
    except OSError as exc:
        raise refusal(E_B_ARGS, f"gh could not be started ({type(exc).__name__})") from exc


def _gh_text(proc: subprocess.CompletedProcess[str]) -> str:
    return " | ".join(execute.masked_lines(proc.stderr)[:3])


def _target(
    p: PrPlan, ctx: checks.Context, child: dict[str, str], scratch: Path
) -> tuple[str, str]:
    """``(target repo, --head value)``: the parent and ``owner:branch`` for a fork."""
    view = _gh(ctx, ["repo", "view", p.item.repo, "--json", "parent"], scratch, child)
    if view.returncode != 0:
        raise refusal(E_B_ARGS, f"gh could not read {p.item.repo} ({_gh_text(view)})")
    parent = _parent_slug(view.stdout)
    owner = p.item.repo.split("/")[0]
    return (parent, f"{owner}:{p.branch}") if parent else (p.item.repo, p.branch)


def exec_pr(
    cwd: Path,
    ctx: checks.Context,
    caller: Caller,
    server: Mapping[str, str],
    *,
    pinned_sha: str,
    asked_at: int,
    answered_at: int,
    info: dict[str, Any] | None = None,
    now: int | None = None,
) -> dict[str, Any]:
    info = info if info is not None else {}
    info["verb"] = "pr"
    dwell: int | None = None
    try:
        plan.admit(caller, ctx)
        dwell = execute.judge_approval(asked_at, answered_at, ctx, now=now)
        current = build_pr_plan(cwd, ctx, caller, server)
        info.update(owner_repo=current.item.repo, branch=current.branch, commits=0,
                    range=f"{current.item.head_sha[:SHORT]}..{current.head[:SHORT]}")  # fmt: skip
        if current.head != pinned_sha:
            raise refusal(
                E_B_MOVED,
                "HEAD changed after the plan",
                pinned=pinned_sha[:12],
                now=current.head[:12],
            )
        child = env.child_env("pr", server, ctx.tools, ctx.home)
        execute.log(ctx, execute._event(caller, info, "approved", "", dwell), must=True)
        scratch = Path(tempfile.mkdtemp(prefix="carter-pr-"))
        try:
            scratch.chmod(0o700)
            return _create(current, ctx, child, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    except IdentityError as exc:
        if not info.get("_logged"):
            execute.refuse_and_log(exc, ctx, caller, info, dwell)
        raise


def _create(p: PrPlan, ctx: checks.Context, child: dict[str, str], scratch: Path) -> dict[str, Any]:
    target, head = _target(p, ctx, child, scratch)
    body = scratch / "body.md"
    fd = os.open(body, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(p.item.body)
    proc = _gh(ctx, build_argv(p.item, target, head, body), scratch, child)
    if proc.returncode != 0:
        info_detail = f"gh pr create failed (exit {proc.returncode}): {_gh_text(proc)}"
        raise refusal(E_B_ARGS, info_detail + "; the handoff is kept")
    handoff.delete_after_success(p.toplevel, p.branch, success=True)
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    shown = mask_userinfo(clean(url, 300))
    return {"ok": True, "url": shown, "target": target, "head": head,
            "text": f"Created pull request {shown}"}  # fmt: skip
