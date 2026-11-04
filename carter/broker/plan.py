"""``broker push --plan``: everything B can know **before** the human approves (App C.5).

No network call and no credential is used here: the plan reads local refs only (the A+ range
rule: ``origin/<branch>`` if it exists, else ``merge-base(origin/HEAD, HEAD)``, labelled "as of
<ref>"). It refuses, in this order and with the registry codes of Appendix B:

caller (``E-B-CALLER``) and rejection counter (``E-B-REJECTED``) -> tools -> repo and SSH config
(``E-B-REPOCFG``) -> origin URL (``E-B-HTTPS`` / ``E-B-ARGS``) -> current branch (detached HEAD,
bad name) -> the remote default branch (``E-B-DEFAULT``, D63: routed to A+) -> the range
(non-fast-forward, empty) -> signatures of LLM-committed commits (``E-B-UNSIGNED``) -> the SSH
agent (``E-B-NOAGENT``, so the human is not asked for something that cannot work).

The same function runs again at ``--exec``; the pinned sha is what must still match.
The plan JSON holds no env, no URL with userinfo, no token, no commit body.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carter.aplus import rangecalc, run, sigcheck
from carter.broker import DEVOPS_AGENT, checks, counter, env, refusal
from carter.broker import argv as argvmod
from carter.identity.errors import (
    E_APLUS_ARGS,
    E_B_ARGS,
    E_B_CALLER,
    E_B_DEFAULT,
    E_B_REJECTED,
    IdentityError,
)

DWELL_DEFAULT_MS = 500
DWELL_FLOOR_MS = 500  # freeze B3 / erratum T5: configurable upward only
DWELL_CAP_MS = 10_000
TIMEOUT_MS = 120_000  # fixed, not configurable
ASSUMED_DEFAULTS = ("main", "master")  # never pushed by B even if origin/HEAD says otherwise (S2)
MAX_COMMITS_SHOWN = 20
SUBJECT_CHARS = 72
SHORT = 12
_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,80}")


def clean(text: str, limit: int = 100) -> str:
    """Printable, single-line, bounded text for a prompt: controls, bidi overrides, zero-width and
    line-separator characters become ``?`` (security review S3: a branch or commit subject must not
    reorder or hide what the human reads in the approval prompt)."""
    plain = "".join("?" if unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") else c for c in text)
    return _CONTROL.sub("?", plain)[:limit]


@dataclass(frozen=True)
class Caller:
    agent: str
    session: str
    root: str


def admit(caller: Caller, ctx: checks.Context) -> None:
    """The caller must be devops with plain session ids, and its family must not be stopped."""
    if caller.agent != DEVOPS_AGENT:
        raise refusal(E_B_CALLER, f"agent {clean(caller.agent, 40)!r}")
    for what, value in (("session", caller.session), ("root", caller.root)):
        if not _ID.fullmatch(value):
            raise refusal(E_B_ARGS, f"the {what} session id is not a plain identifier")
    try:
        if counter.stopped(caller.root, ctx.carter_dir):
            raise refusal(E_B_REJECTED, "rejections in this session family")
    except counter.CounterError as exc:
        raise refusal(E_B_REJECTED, f"the rejection counter cannot be read ({exc})") from exc


def dwell_ms(ctx: checks.Context) -> int:
    """The effective minimum dwell: the configured value, never below 500 ms, at most 10 s."""
    return max(DWELL_FLOOR_MS, min(ctx.cfg.broker.min_dwell_ms, DWELL_CAP_MS))


def approval(ctx: checks.Context) -> dict[str, int]:
    return {"min_dwell_ms": dwell_ms(ctx), "timeout_ms": TIMEOUT_MS}


@dataclass(frozen=True)
class PushPlan:
    toplevel: Path
    url: argvmod.RepoUrl
    branch: str
    base: str
    base_label: str
    pinned_sha: str
    commits: tuple[tuple[str, str], ...]  # (sha, subject) oldest first
    count: int
    new_branch: bool
    sensitive: tuple[str, ...]

    @property
    def range_text(self) -> str:
        return f"{self.base[:SHORT]}..{self.pinned_sha[:SHORT]}"


def read_env(server: Mapping[str, str], ctx: checks.Context) -> dict[str, str]:
    """The base of every read-only git call: B's own child environment, never the server's."""
    return env.child_env("push", server, ctx.tools, ctx.home)


def _git(args: list[str], repo: Path, *, harden: bool = True) -> str | None:
    proc = run.git(args, repo, harden=harden)
    return proc.stdout.strip() if proc.returncode == 0 else None


def _to_b_args(exc: IdentityError) -> IdentityError:
    return refusal(E_B_ARGS, exc.detail) if exc.code == E_APLUS_ARGS else exc


def _default_branch(repo: Path) -> str:
    ref = _git(["symbolic-ref", "--short", "-q", "refs/remotes/origin/HEAD"], repo, harden=False)
    if not ref:
        raise refusal(
            E_B_ARGS,
            "origin/HEAD is not set, so the default branch is unknown "
            "(run: git remote set-head origin --auto)",
        )
    return ref.removeprefix("origin/")


def _commit_lines(repo: Path, commits: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    shown = commits[-MAX_COMMITS_SHOWN:]
    out = []
    for sha in shown:
        subject = _git(["log", "-1", "--format=%s", sha], repo) or ""
        out.append((sha, clean(subject, SUBJECT_CHARS)))
    return tuple(out)


def build_push_plan(
    cwd: Path, ctx: checks.Context, caller: Caller, server: Mapping[str, str], *, agent: bool = True
) -> PushPlan:
    """All the refusals of a push, then the plan. Raises ``IdentityError`` with the B code."""
    admit(caller, ctx)
    env.check_tools(ctx.tools)
    base_env = read_env(server, ctx)
    with run.forced_env(base_env):
        try:
            return _push_plan(cwd, ctx, server)
        except run.RunError as exc:
            raise refusal(E_B_ARGS, str(exc)) from exc
        except sigcheck.SigCheckError as exc:
            raise refusal(E_B_ARGS, f"signatures cannot be checked ({exc})") from exc
        except IdentityError as exc:
            raise _to_b_args(exc) from exc


def _push_plan(cwd: Path, ctx: checks.Context, server: Mapping[str, str]) -> PushPlan:
    top = _git(["rev-parse", "--show-toplevel"], cwd)
    if not top:
        raise refusal(E_B_ARGS, "the session directory is not a git repository")
    repo = Path(top)
    origin = _git(["remote", "get-url", "origin"], repo)
    if not origin:
        raise refusal(E_B_ARGS, "no remote named origin")
    checks.require_clean(checks.vet(repo, origin, ctx))  # before anything else is read or run
    url = argvmod.parse_url(origin)
    branch = _git(["symbolic-ref", "--short", "-q", "HEAD"], repo)
    if not branch:
        raise refusal(E_B_ARGS, "detached HEAD: check out the branch to push")
    argvmod.require_branch(branch)
    if run.run([ctx.tools.git, "check-ref-format", f"refs/heads/{branch}"]).returncode != 0:
        raise refusal(E_B_ARGS, "git does not accept the branch name")
    pinned = _git(["rev-parse", "--verify", "-q", "HEAD^{commit}"], repo) or ""
    argvmod.build_refspec(pinned, branch)  # validates the sha shape
    # `refs/remotes/origin/HEAD` is a local ref a shell can move (`git remote set-head`): the names
    # that are the default almost everywhere stay refused whatever it says (security review S2)
    if _default_branch(repo) == branch or branch in ASSUMED_DEFAULTS:
        raise refusal(E_B_DEFAULT, f"{branch} is the default branch", branch=branch)
    rng = rangecalc.compute_range(repo)
    if not rng.new_branch and not rng.fast_forward:
        raise refusal(E_B_ARGS, f"non-fast-forward: origin/{branch} has commits you do not have")
    if not rng.commits:
        raise refusal(E_B_ARGS, f"nothing to push: no commits beyond {rng.base_ref}")
    failed = sigcheck.check_signatures(repo, rng.commits, sigcheck.SigIdentity.from_config(ctx.cfg))
    sigcheck_error = sigcheck.to_error(failed)
    if sigcheck_error is not None:
        raise sigcheck_error
    env.agent_socket(server, ctx.tools)
    return PushPlan(
        toplevel=repo,
        url=url,
        branch=branch,
        base=rng.base,
        base_label=rng.base_label,
        pinned_sha=pinned,
        commits=_commit_lines(repo, rng.commits),
        count=len(rng.commits),
        new_branch=rng.new_branch,
        sensitive=tuple(f"{c.status} {clean(c.path)}" for c in rng.sensitive[:MAX_COMMITS_SHOWN]),
    )


def push_ask(plan: PushPlan, caller: Caller) -> dict[str, Any]:
    """The text of the OpenCode prompt: built and escaped here, pasted by the plugin."""
    lines = [f"{sha[:SHORT]} {subject}" for sha, subject in plan.commits]
    if plan.count > len(plan.commits):
        lines.append(f"... and {plan.count - len(plan.commits)} earlier commit(s)")
    resources = [
        f"push {plan.url.slug} {plan.branch}",
        f"{plan.range_text} ({plan.base_label}), {plan.count} commit(s)",
        *lines,
    ]
    if plan.sensitive:
        resources.append("touches hook/CI paths: " + ", ".join(plan.sensitive[:5]))
    return {
        "resources": resources,
        "metadata": {
            "verb": "push",
            "caller": clean(caller.agent, 40),
            "session": clean(caller.session, 80),
            "pinned": plan.pinned_sha[:SHORT],
        },
    }


def push_plan_json(plan: PushPlan, ctx: checks.Context, caller: Caller) -> dict[str, Any]:
    return {
        "verb": "push",
        "repo": plan.url.slug,
        "branch": plan.branch,
        "old": plan.base[:SHORT],
        "new": plan.pinned_sha[:SHORT],
        "base_label": plan.base_label,
        "pinned_sha": plan.pinned_sha,
        "commits": [{"sha": s[:SHORT], "subject": t} for s, t in plan.commits],
        "count": plan.count,
        "new_branch": plan.new_branch,
        "sensitive": list(plan.sensitive),
        "approval": approval(ctx),
        "ask": push_ask(plan, caller),
        "audit": {
            "owner_repo": plan.url.slug,
            "branch": plan.branch,
            "range": plan.range_text,
            "commits": plan.count,
            "verb": "push",
        },
    }
