# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx"]
# ///
"""Carter-ops — deterministic CLI for operational tasks.

The model executes write operations directly in the terminal with bot
attribution flags. This CLI provides:
  - audit: Post-hoc audit logging after model-driven execution
  - config --emit: Print config values for model consumption
  - --list: List available operation names

Legacy support (backward compat):
  carter-ops <operation> [params] --dry-run   → shows the plan
  carter-ops <operation> [params] --execute   → executes the plan

All output is JSON to stdout. Human-readable errors go to stderr.

Exit codes:
  0 — Success
  1 — Validation error (missing params, bad ticket key, etc.)
  2 — Execution error (git push rejected, Jira API 403, etc.)
  3 — Configuration error (missing env vars, signing key not found)

Usage:
  carter-ops audit --operation git-flow --params '{"branch":"x"}' --result success
  carter-ops config --emit
  carter-ops --list
  carter-ops git-flow --branch feature/X --message "feat: X" --dry-run  (legacy)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add ops directory to path so modules can be imported
sys.path.insert(0, str(Path(__file__).parent))

from config import Config
from operations import discover_operations, get_operation, list_operations
from output import (
    dry_run_output,
    emit,
    emit_error,
    error_output,
    execute_output,
)

AUDIT_LOG = Path.home() / ".carter" / "audit.log"


def _audit(entry: dict[str, Any]) -> None:
    """Append an entry to the audit log (JSONL)."""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(AUDIT_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Audit is best-effort


def _parse_argv(argv: list[str]) -> tuple[str, dict[str, Any], str]:
    """Parse CLI arguments into (operation_name, params, phase).

    Returns phase as 'dry-run', 'execute', or 'list'.
    """
    if not argv:
        return "", {}, ""

    # Check for --list
    if "--list" in argv:
        return "", {}, "list"

    operation = argv[0]
    params: dict[str, Any] = {}
    phase = ""
    i = 1

    while i < len(argv):
        arg = argv[i]

        if arg == "--dry-run":
            phase = "dry-run"
            i += 1
        elif arg == "--execute":
            phase = "execute"
            i += 1
        elif arg.startswith("--"):
            key = arg[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                value = argv[i + 1]
                # Handle list params (--files can appear multiple times or comma-separated)
                if key in params:
                    existing = params[key]
                    if isinstance(existing, list):
                        existing.append(value)
                    else:
                        params[key] = [existing, value]
                else:
                    params[key] = value
                i += 2
            else:
                params[key] = True
                i += 1
        else:
            i += 1

    # Normalize files param to list
    if "files" in params and isinstance(params["files"], str):
        if "," in params["files"]:
            params["files"] = [f.strip() for f in params["files"].split(",")]
        else:
            params["files"] = [params["files"]]

    # Normalize labels param to list
    if "labels" in params and isinstance(params["labels"], str):
        if "," in params["labels"]:
            params["labels"] = [l.strip() for l in params["labels"].split(",")]

    return operation, params, phase


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
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": operation,
        "phase": "execute",
        "result": result_status,
    }

    # Parse --params JSON
    params_json = params.get("params", "")
    if params_json:
        try:
            entry["params"] = json.loads(params_json) if isinstance(params_json, str) else params_json
        except (json.JSONDecodeError, TypeError):
            entry["params"] = {"raw": str(params_json)}

    # Parse --identifiers JSON
    identifiers_json = params.get("identifiers", "")
    if identifiers_json:
        try:
            entry["identifiers"] = json.loads(identifiers_json) if isinstance(identifiers_json, str) else identifiers_json
        except (json.JSONDecodeError, TypeError):
            entry["identifiers"] = {"raw": str(identifiers_json)}

    _audit(entry)
    emit({"status": "logged", "operation": operation, "result": result_status})
    return 0


def _handle_config_emit() -> int:
    """Print config values for model consumption."""
    cfg = Config.load()
    emit({
        "bot_name": cfg.bot_name,
        "bot_email": cfg.bot_email,
        "signing_key": cfg.signing_key,
        "footer": cfg.footer,
        "jira_url": cfg.jira_url,
        "jira_email": cfg.jira_email,
        "has_jira_token": bool(cfg.jira_token),
        "has_github_token": bool(cfg.github_token),
    })
    return 0


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    # Discover all operations (for legacy --dry-run/--execute support)
    discover_operations()

    # Handle subcommands: audit, config
    if argv and argv[0] == "audit":
        _, params, _ = _parse_argv(argv[1:])
        # Re-parse: audit uses positional-style --key value pairs
        audit_params: dict[str, Any] = {}
        i = 1
        while i < len(argv):
            arg = argv[i]
            if arg.startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                audit_params[arg[2:]] = argv[i + 1]
                i += 2
            elif arg.startswith("--"):
                audit_params[arg[2:]] = True
                i += 1
            else:
                i += 1
        return _handle_audit(audit_params)

    if argv and argv[0] == "config":
        if "--emit" in argv:
            return _handle_config_emit()
        emit_error("Usage: carter-ops config --emit")
        return 1

    operation_name, params, phase = _parse_argv(argv)

    # --list mode
    if phase == "list":
        ops = list_operations()
        emit({"operations": ops})
        return 0

    # Validate we have an operation and phase
    if not operation_name:
        emit_error("Usage: carter-ops <operation> [params] --dry-run|--execute")
        emit_error(f"Operations: {', '.join(list_operations())}")
        return 1

    if not phase:
        emit_error(f"Must specify --dry-run or --execute")
        return 1

    # Look up operation
    op = get_operation(operation_name)
    if not op:
        emit_error(f"Unknown operation: {operation_name}")
        emit_error(f"Available: {', '.join(list_operations())}")
        return 1

    # Load config
    cfg = Config.load()

    # Validate config for domain
    if operation_name.startswith("jira-"):
        cfg_errors = cfg.validate_jira()
        if cfg_errors:
            emit(error_output(operation_name, "CONFIG_ERROR", "; ".join(cfg_errors)))
            return 3

    if operation_name.startswith("gh-"):
        cfg_errors = cfg.validate_github()
        if cfg_errors:
            emit(error_output(operation_name, "CONFIG_ERROR", "; ".join(cfg_errors)))
            return 3

    # Validate params
    validation_errors = op.validate(params)
    if validation_errors:
        emit(error_output(operation_name, "VALIDATION_ERROR", "; ".join(validation_errors)))
        return 1

    # Execute the phase
    if phase == "dry-run":
        plan = op.dry_run(params, cfg)
        result = dry_run_output(
            operation=plan.operation,
            steps=plan.steps,
            attribution=plan.attribution,
            side_effects=plan.side_effects,
        )
        emit(result)

        _audit({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "operation": operation_name,
            "phase": "dry-run",
            "params": {k: v for k, v in params.items() if k not in ("body", "description")},
        })
        return 0

    elif phase == "execute":
        result = op.execute(params, cfg)

        if result.success:
            output = execute_output(
                operation=result.operation,
                success=True,
                result=result.data,
                attribution=result.attribution,
            )
            emit(output)

            _audit({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation": operation_name,
                "phase": "execute",
                "params": {k: v for k, v in params.items() if k not in ("body", "description")},
                "result": "success",
                "identifiers": {
                    k: v for k, v in result.data.items()
                    if k in ("commit_sha", "branch", "key", "comment_id", "ticket")
                },
            })
            return 0
        else:
            # Check if result has a suggestion
            suggestion = result.data.pop("suggestion", "")
            output = error_output(
                operation=result.operation,
                code=result.data.get("error", "EXECUTION_ERROR"),
                message=result.data.get("message", result.data.get("error", "Unknown error")),
                suggestion=suggestion,
            )
            emit(output)

            _audit({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "operation": operation_name,
                "phase": "execute",
                "params": {k: v for k, v in params.items() if k not in ("body", "description")},
                "result": "failure",
                "error": result.data.get("error", ""),
            })
            return 2

    return 1


if __name__ == "__main__":
    sys.exit(main())
