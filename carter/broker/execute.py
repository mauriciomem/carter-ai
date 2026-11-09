"""``broker push --exec``: the approved push.

Order, each step a refusal with a registry code and an audit line:

1. caller and rejection counter (as in the plan);
2. the **approval** is judged here, from the raw timestamps the plugin measured around
   ``ctx.permission.assert``: fewer than ``min_dwell_ms`` (500, only configurable upward) is
   ``E-B-DWELL`` (auto-accept: ``--auto``, a script), more than 120 s is ``E-B-TIMEOUT``;
   either counts as a rejection; timestamps far from now are refused as stale;
3. HEAD must still be the pinned sha (``E-B-MOVED``); then **every plan check runs again**
   (repo config, SSH config, URL, default branch, range, signatures, agent);
4. the audit line ``approved`` is written (a failure to write it refuses: no unlogged push);
5. under a per-repo ``flock``, ``git push -- <url> <sha>:refs/heads/<branch>`` runs with the
   per-verb environment, no retry; the remote ref is read back with ``ls-remote`` and must equal
   the pinned sha; the local ``origin/<branch>`` tracking ref is then updated (a push to a URL
   does not do it).

The child's output is masked (userinfo in URLs, control characters) before it is returned.
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import os
import subprocess
import time
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from carter.aplus import run
from carter.aplus.findings import mask_userinfo
from carter.broker import argv as argvmod
from carter.broker import audit, checks, counter, env, plan, refusal
from carter.broker.plan import TIMEOUT_MS, Caller, clean
from carter.identity.errors import E_B_ARGS, E_B_DWELL, E_B_MOVED, E_B_TIMEOUT, IdentityError

PUSH_TIMEOUT = 120.0
STALE_MS = 30_000
OUTPUT_LINES = 8


def now_ms() -> int:
    return int(time.time() * 1000)


def judge_approval(
    asked_at: int, answered_at: int, ctx: checks.Context, *, now: int | None = None
) -> int:
    """The dwell in ms if the approval is acceptable; else the refusal (``E-B-DWELL`` etc.)."""
    current = now_ms() if now is None else now
    dwell = answered_at - asked_at
    if abs(current - answered_at) > STALE_MS or asked_at <= 0:
        raise refusal(E_B_ARGS, "the approval timestamps are not from this moment")
    if dwell > TIMEOUT_MS:
        raise refusal(E_B_TIMEOUT, f"approval after {dwell} ms")
    minimum = plan.dwell_ms(ctx)
    if dwell < minimum:
        raise refusal(
            E_B_DWELL, f"approval after {max(dwell, 0)} ms", n=str(max(dwell, 0)), min=str(minimum)
        )
    return dwell


@contextlib.contextmanager
def repo_lock(carter_dir: Path, toplevel: Path) -> Iterator[None]:
    """``flock`` per repository (concurrent ``--exec`` on one repo serialise)."""
    key = hashlib.sha256(os.path.realpath(toplevel).encode()).hexdigest()[:16]
    directory = carter_dir / "run"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(directory / f"b-{key}.lock", os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def masked_lines(*streams: str) -> list[str]:
    lines = [ln for stream in streams for ln in stream.splitlines() if ln.strip()]
    return [mask_userinfo(clean(ln, 300)) for ln in lines[:OUTPUT_LINES]]


def _head(cwd: Path, ctx: checks.Context, server: Mapping[str, str]) -> tuple[Path, str]:
    with run.forced_env(plan.read_env(server, ctx)):
        top = run.git(["rev-parse", "--show-toplevel"], cwd)
        head = run.git(
            ["rev-parse", "--verify", "-q", "HEAD^{commit}"], Path(top.stdout.strip() or cwd)
        )
    if top.returncode != 0 or head.returncode != 0:
        raise refusal(E_B_ARGS, "the session directory is not a git repository with a commit")
    return Path(top.stdout.strip()), head.stdout.strip()


def _event(
    caller: Caller, info: dict[str, Any], decision: str, code: str, dwell: int | None
) -> dict[str, Any]:
    return {
        **{k: info.get(k, "") for k in ("owner_repo", "branch", "range", "commits")},
        "root": caller.root, "session": caller.session, "agent": caller.agent,
        "verb": info.get("verb", "push"),
        "decision": decision, "code": code, "dwell_ms": dwell,
    }  # fmt: skip


def log(ctx: checks.Context, event: dict[str, Any], *, must: bool = False) -> None:
    try:
        audit.record(event, ctx.carter_dir)
    except audit.AuditError as exc:
        if must:
            raise refusal(
                E_B_ARGS, f"the audit file cannot be written, so nothing is pushed ({exc})"
            ) from exc


def refuse_and_log(
    exc: IdentityError,
    ctx: checks.Context,
    caller: Caller,
    info: dict[str, Any],
    dwell: int | None = None,
) -> None:
    """Audit a refusal; dwell and timeout also count as a rejection."""
    decision = {E_B_DWELL: "dwell", E_B_TIMEOUT: "timeout"}.get(exc.code, "refused")
    if decision in ("dwell", "timeout"):
        with contextlib.suppress(counter.CounterError):
            counter.add(caller.root, ctx.carter_dir)
    log(ctx, _event(caller, info, decision, exc.code, dwell))
    info["_logged"] = True


def exec_push(
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
    """Push the pinned commit; returns the result document. Raises ``IdentityError``."""
    info = info if info is not None else {}
    dwell: int | None = None
    try:
        plan.admit(caller, ctx)
        dwell = judge_approval(asked_at, answered_at, ctx, now=now)
        top, head = _head(cwd, ctx, server)
        if head != pinned_sha:
            raise refusal(
                E_B_MOVED, "HEAD changed after the plan", pinned=pinned_sha[:12], now=head[:12]
            )
        current = plan.build_push_plan(cwd, ctx, caller, server)
        info.update(
            owner_repo=current.url.slug,
            branch=current.branch,
            range=current.range_text,
            commits=current.count,
        )
        if current.pinned_sha != pinned_sha:
            raise refusal(
                E_B_MOVED,
                "HEAD changed after the plan",
                pinned=pinned_sha[:12],
                now=current.pinned_sha[:12],
            )
        sock = env.agent_socket(server, ctx.tools)
        child = env.child_env("push", server, ctx.tools, ctx.home, ssh_auth_sock=sock)
        log(ctx, _event(caller, info, "approved", "", dwell), must=True)
        with repo_lock(ctx.carter_dir, current.toplevel):
            return _push(current, ctx, caller, child, info, dwell)
    except IdentityError as exc:
        if not info.get("_logged"):
            refuse_and_log(exc, ctx, caller, info, dwell)
        raise


def _run_child(
    cmd: list[str], cwd: Path, child: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd, cwd=cwd, env=child, stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=PUSH_TIMEOUT, check=False,
        )  # fmt: skip
    except subprocess.TimeoutExpired as exc:
        raise refusal(
            E_B_ARGS, f"git did not finish within {PUSH_TIMEOUT:g} s; nothing is retried"
        ) from exc
    except OSError as exc:
        raise refusal(E_B_ARGS, f"git could not be started ({type(exc).__name__})") from exc


def _push(
    current: plan.PushPlan, ctx: checks.Context, caller: Caller, child: dict[str, str],
    info: dict[str, Any], dwell: int | None,
) -> dict[str, Any]:  # fmt: skip
    # The last look before the push (inside the lock): a repo or ssh config written since the plan
    # is refused here (the window is a few milliseconds, not the checks).
    with run.forced_env(child):
        checks.require_clean(checks.vet(current.toplevel, current.url.url, ctx))
    proc = _run_child(
        argvmod.push_argv(ctx.tools, current.url, current.pinned_sha, current.branch),
        current.toplevel,
        child,
    )
    output = masked_lines(proc.stdout, proc.stderr)
    if proc.returncode != 0:
        detail = f"git push failed (exit {proc.returncode}): " + " | ".join(output[:3])
        raise _logged(refusal(E_B_ARGS, detail), ctx, caller, info, dwell)
    seen = _run_child(
        argvmod.ls_remote_argv(ctx.tools, current.url, current.branch), current.toplevel, child
    )
    remote = seen.stdout.split()[:1]
    if seen.returncode != 0 or remote != [current.pinned_sha]:
        detail = "git push ended without error but the remote branch is not at the pinned commit"
        raise _logged(refusal(E_B_ARGS, detail), ctx, caller, info, dwell)
    with run.forced_env(env.child_env("push", {}, ctx.tools, ctx.home)):
        run.git(
            ["update-ref", f"refs/remotes/origin/{current.branch}", current.pinned_sha],
            current.toplevel,
        )
    return {
        "ok": True, "pushed": current.pinned_sha, "repo": current.url.slug,
        "branch": current.branch,
        "range": current.range_text, "output": output,
        "text": f"Pushed {current.branch} ({current.range_text}) to {current.url.slug}.",
    }  # fmt: skip


def _logged(
    exc: IdentityError, ctx: checks.Context, caller: Caller, info: dict[str, Any], dwell: int | None
) -> IdentityError:
    """Audit a failure that happened after the ``approved`` line (decision ``error``)."""
    log(ctx, _event(caller, info, "error", exc.code, dwell))
    info["_logged"] = True
    return exc
