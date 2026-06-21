# /// script
# requires-python = ">=3.11"
# ///
"""Carter-ops structured output formatting.

All output to stdout is JSON. Human-readable errors go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def dry_run_output(
    operation: str,
    steps: list[str],
    attribution: str,
    side_effects: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a dry-run result dict."""
    result: dict[str, Any] = {
        "phase": "dry-run",
        "operation": operation,
        "steps": steps,
        "attribution": attribution,
    }
    if side_effects:
        result["side_effects"] = side_effects
    if extra:
        result.update(extra)
    return result


def execute_output(
    operation: str,
    success: bool,
    result: dict[str, Any],
    attribution: str,
) -> dict[str, Any]:
    """Build an execute result dict."""
    return {
        "phase": "execute",
        "operation": operation,
        "success": success,
        "result": result,
        "attribution": attribution,
    }


def error_output(
    operation: str,
    code: str,
    message: str,
    suggestion: str = "",
) -> dict[str, Any]:
    """Build an error result dict."""
    err: dict[str, Any] = {
        "phase": "execute",
        "operation": operation,
        "success": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
    if suggestion:
        err["error"]["suggestion"] = suggestion
    return err


def emit(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2))


def emit_error(message: str) -> None:
    """Write human-readable error to stderr."""
    print(f"error: {message}", file=sys.stderr)
