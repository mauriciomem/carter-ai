"""Loader for the golden vectors shared by pytest, ``node --test`` and the sh tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parents[1] / "data" / "plugin_vectors.json"


def load() -> dict[str, Any]:
    return json.loads(PATH.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def expand(env: dict[str, Any]) -> dict[str, str]:
    """Resolve the ``$expand`` shorthand: N identical key/value entries, to keep the file small."""
    spec = env.get("$expand")
    out = {k: v for k, v in env.items() if k != "$expand"}
    if spec:
        for i in range(spec["entries"]):
            out[f"GIT_CONFIG_KEY_{i}"] = spec["key"]
            out[f"GIT_CONFIG_VALUE_{i}"] = spec["value"]
    return out
