# /// script
# requires-python = ">=3.11"
# ///
"""Carter-ops operation base class and auto-discovery registry."""
from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from carter.ops.config import Config


@dataclass
class Plan:
    """Dry-run result describing what would happen."""
    operation: str
    steps: list[str]
    attribution: str
    side_effects: list[str]


@dataclass
class Result:
    """Execution result."""
    operation: str
    success: bool
    data: dict[str, Any]
    attribution: str


class Operation(ABC):
    """Base class for all carter-ops operations."""

    name: str = ""

    @abstractmethod
    def dry_run(self, params: dict[str, Any], cfg: Config) -> Plan:
        """Return what would happen without doing it."""

    @abstractmethod
    def execute(self, params: dict[str, Any], cfg: Config) -> Result:
        """Execute the operation and return a structured result."""

    def validate(self, params: dict[str, Any]) -> list[str]:
        """Return a list of validation errors. Empty = valid."""
        return []


# Global registry
_registry: dict[str, type[Operation]] = {}


def register(cls: type[Operation]) -> type[Operation]:
    """Decorator that registers an Operation subclass."""
    _registry[cls.name] = cls
    return cls


def get_operation(name: str) -> Operation | None:
    """Look up a registered operation by name and return an instance."""
    cls = _registry.get(name)
    return cls() if cls else None


def list_operations() -> list[str]:
    """Return sorted list of registered operation names."""
    return sorted(_registry.keys())


def discover_operations() -> None:
    """Import all modules in the operations package to trigger @register."""
    from carter.ops import operations as ops_pkg

    for _importer, modname, _ispkg in pkgutil.iter_modules(ops_pkg.__path__):
        if modname.startswith("_"):
            continue
        importlib.import_module(f"carter.ops.operations.{modname}")
