"""Leveled logging for the installer, drawn by ``carter.ui``.

The verbosity level is module state here (single source); ``carter.install.orchestrator.run``
sets it via :func:`set_verbosity`. ``0=quiet, 1=default, 2=verbose, 3=debug``. A default run
shows only warnings and errors, then the one summary line the caller prints; ``-v`` shows each
step.
"""

from __future__ import annotations

from carter import ui

# Log levels: 0=quiet, 1=default, 2=verbose, 3=debug
_verbosity = 1


def set_verbosity(level: int) -> None:
    """Set the module-level verbosity used by :func:`_log`."""
    global _verbosity
    _verbosity = level


def _log(msg: str, level: int = 1) -> None:
    if _verbosity >= level:
        ui.info(msg.strip("\n"))


def log_step(msg: str) -> None:
    if _verbosity >= 2:
        ui.info(f"→ {msg}")


def log_ok(msg: str, detail: str = "") -> None:
    if _verbosity >= 2:
        ui.ok(msg, detail)


def log_warn(msg: str, hint: str = "") -> None:
    if _verbosity >= 1:
        ui.warn(msg, hint)


def log_err(msg: str) -> None:
    ui.fail(msg)


def log_skip(msg: str) -> None:
    if _verbosity >= 2:
        ui.info(f"· {msg}")


def log_debug(msg: str) -> None:
    if _verbosity >= 3:
        ui.info(f"[debug] {msg}")
