"""Carter-ops — audit ledger and config helper for operational tasks.

The model runs git and gh commands directly in the terminal, with the attribution that
``config --emit`` prints, following the ``carter-ops`` skill. This CLI only provides the
deterministic side-channel around that:

  - audit:           post-hoc audit logging after model-driven execution
  - policy-override: record a single-action strictness-policy override
  - config --emit:   print the resolved attribution (tier, role, trailer) and footer

All output is JSON to stdout. Human-readable errors go to stderr.

Exit codes:
  0 — Success
  1 — Usage/validation error (missing params, unknown subcommand)

Usage (via the ``carter`` CLI):
  carter ops audit --operation git-flow --params '{"branch":"x"}' --result success
  carter ops policy-override --category remote-write --action "vault read x" --tier native-ask
  carter ops config --emit [--field NAME]
"""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from carter.aplus.push import OWN_TERMINAL
from carter.broker import audit as audit_store
from carter.config import _BASH_COMMANDS, RISK_TAXONOMY
from carter.identity.rules import forbidden_classes
from carter.ops.config import Config

# The ops log lives in ~/.carter/state/audit/ next to b.jsonl. It is resolved when
# used, not at import; a test may still point AUDIT_LOG at a file of its own.
AUDIT_LOG: Path | None = None

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
        if AUDIT_LOG is not None:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        else:
            audit_store.append_ops(entry)
    except (OSError, audit_store.AuditError):
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

    _audit(entry)  # silent on success: the agent does not echo a record nobody reads
    return 0


# Cap on free-text fields recorded in the override ledger (keeps entries one-line sized).
MAX_TEXT_LEN = 500

_OVERRIDE_TIERS = ("native-deny", "native-ask", "prose-backstop")

_SEGMENT = re.compile(r"[;&|\n`()]+")


def _github_write_prefixes() -> list[list[str]]:
    """Word lists of every GitHub-write command: the ``github-write`` shell table (what the
    agent permissions deny) plus the ``push-verbs`` class of ``g2_rules.json``."""
    prefixes = [p.removesuffix(" *") for p in _BASH_COMMANDS["github-write"]]
    prefixes += [item for c in forbidden_classes() if c.id == "push-verbs" for item in c.items]
    return [p.lower().split() for p in dict.fromkeys(prefixes)]


def is_github_write(action: str) -> bool:
    """Does ``action`` name a GitHub write (push, PR/issue write, release, API)?

    True when, within one shell segment, the words of any GitHub-write command appear in
    order (so ``git -C repo push`` and ``run: git push && echo`` match). Deliberately broad:
    refusing an override that could not weaken anything costs nothing."""
    for segment in _SEGMENT.split(action.lower()):
        tokens = segment.split()
        for words in _github_write_prefixes():
            position = iter(tokens)
            if all(word in position for word in words):
                return True
    return False


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

    if is_github_write(action):
        # Every GitHub write is human-only: the ledger must not suggest
        # otherwise. Opening, editing and commenting on a PR are not writes of that kind.
        _audit(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "policy-override-refused",
                "category": category,
                "action": action,
                "tier": tier,
                "authorized": False,
            }
        )
        emit_error(
            "GitHub writes (push, merging or reviewing a PR, issues, releases, the API) are "
            "human-only; "
            f"policy-override cannot change that. {OWN_TERMINAL}"
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


def _handle_config_emit(field: str | None = None) -> int:
    """Print config values for model consumption (``field``: just that one, as plain text)."""
    cfg = Config.load()
    for warning in (cfg.footer_warning, *cfg.warnings):
        if warning:
            emit_error(warning)
    data = {
        "tier": cfg.tier,
        "role": cfg.role,
        "role_source": cfg.role_source,
        "mode": cfg.mode,
        "author": cfg.author,
        "committer": cfg.committer,
        "signer_fpr": cfg.signer_fpr,
        "coauthor_trailer": cfg.coauthor_trailer,
        "coauthor_linked": cfg.coauthor_linked,
        "commits": cfg.commits,
        "refusal_reason": cfg.refusal_reason,
        "footer": cfg.footer,
        "has_github_token": bool(cfg.github_token),
    }
    if field is None:
        emit(data)
        return 0
    if field not in data:
        emit_error(f"--field must be one of: {', '.join(data)}")
        return 1
    value = data[field]
    # one value, no JSON: the agent reads it without printing the whole record
    print(
        "true" if value is True else "false" if value is False else "" if value is None else value
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
            flags = _parse_flags([a for a in rest if a != "--emit"])
            field = flags.get("field")
            if "field" in flags and not isinstance(field, str):
                emit_error("--field needs a name")
                return 1
            return _handle_config_emit(field)
        emit_error("Usage: carter ops config --emit [--field NAME]")
        return 1

    emit_error(f"Unknown subcommand: {command}" if command else "Missing subcommand")
    emit_error(USAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
