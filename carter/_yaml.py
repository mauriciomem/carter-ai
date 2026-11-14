"""YAML loading with libyaml when PyYAML has it: the pure-Python parser is ~10x slower."""

from __future__ import annotations

from typing import IO, Any

import yaml

SafeLoader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def load(source: str | IO[str]) -> Any:
    """``yaml.safe_load`` through the fastest safe loader available."""
    return yaml.load(source, Loader=SafeLoader)
