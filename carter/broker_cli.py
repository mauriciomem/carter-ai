"""``python -I -m carter.broker_cli``: the only entry of B's Python core (freeze B2, erratum T6).

Spawned by the OpenCode plugin tools ``carter_push`` / ``carter_pr`` with the **server**
environment (nothing here is meant for a human or an agent shell; there is no click wrapper
because humans use A+, ``carter push`` / ``carter pr``). Subcommands::

    push --plan --cwd DIR --agent A --session S --root R --git G [--gh H]
    push --exec ... --pinned-sha SHA --asked-at MS --answered-at MS
    pr   --plan|--exec ...                       (same flags)
    record --outcome rejected|timeout|aborted|corrected|dwell --agent A --session S --root R
           [--audit JSON]

Output is one JSON line on stdout. Exit 0 = ok, 1 = refusal (``{"code","message","detail"}``),
2 = usage. **Every** subcommand first refuses when the environment shows an agent shell or
Carter's isolation (``E-B-POLLUTED``, names only; never scrubbed), so an agent that calls this
module from its own shell is refused; the command gate also denies it (``human-only-carter``).
Stdlib argparse only: the start-up budget of the plugin's calls.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from carter.broker import audit, checks, counter, env, execute, plan, refusal
from carter.broker import pr as prmod
from carter.broker.plan import Caller
from carter.identity.errors import (
    E_B_ARGS,
    E_B_DWELL,
    E_B_REJECTED,
    E_B_TIMEOUT,
    IdentityError,
    registry,
)

OUTCOMES = ("rejected", "timeout", "aborted", "corrected", "dwell")
EXIT_OK, EXIT_REFUSED, EXIT_USAGE = 0, 1, 2
_DECISION = {"rejected": "rejected", "corrected": "corrected", "timeout": "timeout",
             "aborted": "aborted", "dwell": "dwell"}  # fmt: skip


class _Usage(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise _Usage(message)


def parser() -> argparse.ArgumentParser:
    top = _Parser(prog="python -I -m carter.broker_cli", add_help=False)
    sub = top.add_subparsers(dest="command", required=True, parser_class=_Parser)
    for verb in ("push", "pr"):
        p = sub.add_parser(verb, add_help=False)
        mode = p.add_mutually_exclusive_group(required=True)
        mode.add_argument("--plan", action="store_true")
        mode.add_argument("--exec", action="store_true", dest="execute")
        _common(p)
        p.add_argument("--pinned-sha")
        p.add_argument("--asked-at", type=int)
        p.add_argument("--answered-at", type=int)
    rec = sub.add_parser("record", add_help=False)
    rec.add_argument("--outcome", required=True, choices=OUTCOMES)
    rec.add_argument("--agent", required=True)
    rec.add_argument("--session", required=True)
    rec.add_argument("--root", required=True)
    rec.add_argument("--audit")
    rec.add_argument("--git", default="")
    rec.add_argument("--base-dir", type=Path, default=None, help=argparse.SUPPRESS)
    return top


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--cwd", required=True, type=Path)
    p.add_argument("--agent", required=True)
    p.add_argument("--session", required=True)
    p.add_argument("--root", required=True)
    p.add_argument("--git", required=True)
    p.add_argument("--gh", default="")
    p.add_argument("--base-dir", type=Path, default=None, help=argparse.SUPPRESS)


def _out(stream: Any, doc: Mapping[str, Any]) -> None:
    stream.write(json.dumps(doc, sort_keys=True, ensure_ascii=True) + "\n")
    stream.flush()


def _error_doc(exc: IdentityError) -> dict[str, str]:
    return {"code": exc.code, "message": str(exc), "detail": exc.detail}


def _audit_refusal(
    exc: IdentityError, args: argparse.Namespace, ctx: checks.Context | None, info: dict[str, Any]
) -> None:
    """Best-effort audit of a refusal that happened before the exec path logged it."""
    base = ctx.carter_dir if ctx else None
    decision = {E_B_DWELL: "dwell", E_B_TIMEOUT: "timeout"}.get(exc.code, "refused")
    event = {
        **{k: info.get(k, "") for k in ("owner_repo", "branch", "range", "commits")},
        "root": args.root, "session": args.session, "agent": args.agent,
        "verb": getattr(args, "command", ""), "decision": decision, "code": exc.code,
    }  # fmt: skip
    with contextlib.suppress(audit.AuditError):
        audit.record(event, base)


def run(argv: Sequence[str], environ: Mapping[str, str], stdout: Any = None) -> int:
    stdout = stdout or sys.stdout
    try:
        args = parser().parse_args(list(argv))
    except _Usage as exc:
        _out(stdout, {"code": "usage", "message": str(exc)})
        return EXIT_USAGE
    info: dict[str, Any] = {}
    ctx: checks.Context | None = None
    try:
        env.refuse_polluted(environ, str(Path.home()))
        ctx = checks.load_context(git=args.git, gh=getattr(args, "gh", ""), base_dir=args.base_dir)
        if args.command == "record":
            return _record(args, ctx, stdout)
        doc = _dispatch(args, ctx, environ, info)
    except IdentityError as exc:
        if not info.get("_logged") and args.command != "record":
            _audit_refusal(exc, args, ctx, info)
        _out(stdout, _error_doc(exc))
        return EXIT_REFUSED
    except counter.CounterError as exc:
        _out(stdout, _error_doc(refusal(E_B_REJECTED, str(exc))))
        return EXIT_REFUSED
    _out(stdout, doc)
    return EXIT_OK


def _dispatch(
    args: argparse.Namespace, ctx: checks.Context, environ: Mapping[str, str], info: dict[str, Any]
) -> dict[str, Any]:
    caller = Caller(args.agent, args.session, args.root)
    cwd = args.cwd
    if args.plan:
        if args.command == "push":
            built = plan.build_push_plan(cwd, ctx, caller, environ)
            return plan.push_plan_json(built, ctx, caller)
        p = prmod.build_pr_plan(cwd, ctx, caller, environ)
        return prmod.pr_plan_json(p, ctx, caller)
    if args.pinned_sha is None or args.asked_at is None or args.answered_at is None:
        raise _exec_args_error()
    runner = execute.exec_push if args.command == "push" else prmod.exec_pr
    return runner(
        cwd, ctx, caller, environ, pinned_sha=args.pinned_sha,
        asked_at=args.asked_at, answered_at=args.answered_at, info=info,
    )  # fmt: skip


def _exec_args_error() -> IdentityError:
    return refusal(E_B_ARGS, "--exec needs --pinned-sha, --asked-at and --answered-at")


def _record(args: argparse.Namespace, ctx: checks.Context, stdout: Any) -> int:
    """Count a rejection, timeout, abort or dwell refusal and write the audit line (no network)."""
    caller = Caller(args.agent, args.session, args.root)
    try:
        extra = json.loads(args.audit) if args.audit else {}
    except ValueError:
        extra = {}
    if not isinstance(extra, dict):
        extra = {}
    total = counter.add(args.root, ctx.carter_dir)
    event = {
        **{k: extra.get(k, "") for k in ("owner_repo", "branch", "range", "commits", "verb")},
        "root": caller.root, "session": caller.session, "agent": caller.agent,
        "decision": _DECISION[args.outcome], "code": "",
    }  # fmt: skip
    if args.outcome == "timeout":
        event["code"] = E_B_TIMEOUT
    with contextlib.suppress(audit.AuditError):  # the refusal already happened: best effort
        audit.record(event, ctx.carter_dir)
    doc: dict[str, Any] = {"ok": True, "count": total, "stopped": total >= counter.MAX_REJECTIONS}
    if args.outcome == "timeout":
        doc["code"], doc["message"] = E_B_TIMEOUT, registry()[E_B_TIMEOUT].message
    _out(stdout, doc)
    return EXIT_OK


def main() -> int:
    import os

    return run(sys.argv[1:], os.environ)


if __name__ == "__main__":
    sys.exit(main())
