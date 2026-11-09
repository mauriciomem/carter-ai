"""Carter AI — workspace scaffolding and management."""

from __future__ import annotations

__version__: str  # resolved on first use, see __getattr__


def __getattr__(name: str) -> str:
    """Resolve ``__version__`` lazily (PEP 562).

    ``importlib.metadata`` costs about 25 ms to import and ``python -m carter.gate`` runs on every
    agent shell command, so the package itself must stay free to import."""
    if name == "__version__":
        from importlib.metadata import PackageNotFoundError, version  # noqa: PLC0415

        try:
            value = version("carter-ai")
        except PackageNotFoundError:  # running from a source tree without installed metadata
            value = "0+unknown"
        globals()["__version__"] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
