"""ANSI color + leveled logging helpers for the installer.

The verbosity level is module state here (single source); ``carter.install.orchestrator.run``
sets it via :func:`set_verbosity`. ``0=quiet, 1=default, 2=verbose, 3=debug``.
"""

from __future__ import annotations

import os
import sys

_NO_COLOR = not sys.stdout.isatty() or os.environ.get("NO_COLOR")


def _c(code: str, text: str) -> str:
    if _NO_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:
    return _c("32", t)


def yellow(t: str) -> str:
    return _c("33", t)


def red(t: str) -> str:
    return _c("31", t)


def bold(t: str) -> str:
    return _c("1", t)


def dim(t: str) -> str:
    return _c("2", t)


# Log levels: 0=quiet, 1=default, 2=verbose, 3=debug
_verbosity = 1


def set_verbosity(level: int) -> None:
    """Set the module-level verbosity used by :func:`_log`."""
    global _verbosity
    _verbosity = level


def _log(msg: str, level: int = 1) -> None:
    if _verbosity >= level:
        print(msg)


def log_step(msg: str) -> None:
    _log(f"\n{bold('→')} {bold(msg)}")


def log_ok(msg: str, detail: str = "") -> None:
    suffix = f" {dim(detail)}" if detail else ""
    _log(f"  {green('✓')} {msg}{suffix}")


def log_warn(msg: str, hint: str = "") -> None:
    _log(f"  {yellow('⚠')} {msg}")
    if hint:
        _log(f"    {dim(hint)}")


def log_err(msg: str) -> None:
    _log(f"  {red('✗')} {msg}", level=0)


def log_skip(msg: str) -> None:
    _log(f"  {dim('·')} {msg}", level=2)


def log_debug(msg: str) -> None:
    _log(f"  {dim('[debug]')} {msg}", level=3)
