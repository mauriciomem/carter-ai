"""Carter-ops structured output formatting.

All output to stdout is JSON. Human-readable errors go to stderr.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def emit(data: dict[str, Any]) -> None:
    """Write JSON to stdout."""
    print(json.dumps(data, indent=2))


def emit_error(message: str) -> None:
    """Write human-readable error to stderr."""
    print(f"error: {message}", file=sys.stderr)
