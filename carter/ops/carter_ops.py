"""Carter-ops — audit ledger and config helper for operational tasks.

The model executes write operations (git, gh) directly in the terminal
with bot attribution flags, following the ``carter-ops`` skill. This CLI only
provides the deterministic side-channel around that:

  - audit:           post-hoc audit logging after model-driven execution
  - policy-override: record a single-action strictness-policy override
  - config --emit:   print the resolved attribution (tier, role, trailer) and footer

All output is JSON to stdout. Human-readable errors go to stderr.

Exit codes:
  0 — Success
  1 — Usage/validation error (missing params, unknown subcommand)

Usage (via the ``carter`` CLI):
  carter ops audit --operation git-flow --params '{"branch":"x"}' --result success
  carter ops policy-override --category remote-write --action "git push" --tier native-ask
  carter ops config --emit
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

from carter.config import RISK_TAXONOMY
from carter.home import carter_home
from carter.ops.config import Config

AUDIT_LOG = carter_home() / "audit.log"

USAGE = "Usage: carter ops {audit|policy-override|config --emit} [--key value ...]"

HELP_FLAGS = frozenset({"--help", "-h", "help"})


def emit(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2))


def emit_error(message: str) -> None:
    """Write a human-readable error to stderr."""
    print(f"error: {message}", file=sys.stderr)


def _audit(entry: dict[str, Any]) -> None:
    """Append an entry to the audit log (JSONL)."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Audit is best-effort


def _parse_flags(args: list[str]) -> dict[str, Any]:
    """Parse ``--key value`` pairs; a ``--flag`` with no value becomes ``True``.

    Non-flag tokens that are not a flag's value are ignored.
    """
    params: dict[str, Any] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("--") and i + 1 < len(args) and not args[i + 1].startswith("--"):
            params[arg[2:]] = args[i + 1]
            i += 2
        elif arg.startswith("--"):
            params[arg[2:]] = True
            i += 1
        else:
            i += 1
    return params


def _handle_audit(params: dict[str, Any]) -> int:
    """Append an audit entry from model's direct execution."""
    operation = params.get("operation", "")
    if not operation:
        emit_error("--operation is required for audit")
        return 1

    result_status = params.get("result", "")
    if not result_status:
        emit_error("--result is required for audit (success or failure)")
        return 1

    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "operation": operation,
        "phase": "execute",
        "result": result_status,
    }

    # Parse --params JSON
    params_json = params.get("params", "")
    if params_json:
        try:
            entry["params"] = (
                json.loads(params_json) if isinstance(params_json, str) else params_json
            )
        except (json.JSONDecodeError, TypeError):
            entry["params"] = {"raw": str(params_json)}

    # Parse --identifiers JSON
    identifiers_json = params.get("identifiers", "")
    if identifiers_json:
        try:
            entry["identifiers"] = (
                json.loads(identifiers_json)
                if isinstance(identifiers_json, str)
                else identifiers_json
            )
        except (json.JSONDecodeError, TypeError):
            entry["identifiers"] = {"raw": str(identifiers_json)}

    _audit(entry)
    emit({"status": "logged", "operation": operation, "result": result_status})
    return 0


# Cap on free-text fields recorded in the override ledger (keeps entries one-line sized).
MAX_TEXT_LEN = 500

_OVERRIDE_TIERS = ("native-deny", "native-ask", "prose-backstop")


def _handle_policy_override(params: dict[str, Any]) -> int:
    """Record a single-action strictness-policy override in the audit ledger.

    **Override ≠ authorization.** This RECORDS a deliberate override of a policy
    gate for one action; it cannot lift a platform ``deny`` (the emitted native
    config does that). One entry per action — there is no blanket/session-wide
    override (a deliberate choice, to avoid override fatigue). The per-tier
    meaning: ``native-deny`` the user relaxed the emitted config (logged);
    ``native-ask`` confirmed the interactive prompt; ``prose-backstop`` proceeded
    on trust (logged only).
    """
    category = params.get("category", "")
    if not category:
        emit_error("--category is required for policy-override (e.g. remote-write)")
        return 1
    if category not in RISK_TAXONOMY:
        emit_error(f"--category must be one of: {', '.join(RISK_TAXONOMY)}")
        return 1

    action = params.get("action", "")
    if not action or not isinstance(action, str):
        emit_error("--action is required for policy-override (the action being overridden)")
        return 1

    reason = params.get("reason", "")
    if not isinstance(reason, str):
        emit_error("--reason needs a value")
        return 1
    for flag, value in (("action", action), ("reason", reason)):
        if len(value) > MAX_TEXT_LEN:
            emit_error(f"--{flag} is too long ({len(value)} chars; max {MAX_TEXT_LEN})")
            return 1

    tier = params.get("tier", "")
    if tier not in _OVERRIDE_TIERS:
        emit_error(
            "--tier must be one of: "
            + ", ".join(_OVERRIDE_TIERS)
            + " (no blanket/session-wide overrides)"
        )
        return 1

    entry: dict[str, Any] = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "policy-override",
        "category": category,
        "action": action,
        "tier": tier,
        "reason": reason,
        # The ledger records; it never authorizes or lifts a platform deny.
        "authorized": False,
    }
    _audit(entry)
    emit(
        {
            "status": "logged",
            "event": "policy-override",
            "category": category,
            "tier": tier,
            "authorized": False,
        }
    )
    return 0


def _handle_config_emit() -> int:
    """Print config values for model consumption."""
    cfg = Config.load()
    for warning in (cfg.footer_warning, *cfg.warnings):
        if warning:
            emit_error(warning)
    emit(
        {
            "tier": cfg.tier,
            "role": cfg.role,
            "role_source": cfg.role_source,
            "coauthor_trailer": cfg.coauthor_trailer,
            "commits": cfg.commits,
            "refusal_reason": cfg.refusal_reason,
            "footer": cfg.footer,
            "has_github_token": bool(cfg.github_token),
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    command, rest = (argv[0], argv[1:]) if argv else ("", [])

    # Help is plain text on stdout; real subcommands keep the JSON contract.
    if command in HELP_FLAGS or HELP_FLAGS.intersection(rest):
        print(f"{USAGE}\n\n{(__doc__ or '').strip()}")
        return 0

    if command == "audit":
        return _handle_audit(_parse_flags(rest))

    if command == "policy-override":
        return _handle_policy_override(_parse_flags(rest))

    if command == "config":
        if "--emit" in rest:
            return _handle_config_emit()
        emit_error("Usage: carter ops config --emit")
        return 1

    emit_error(f"Unknown subcommand: {command}" if command else "Missing subcommand")
    emit_error(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
