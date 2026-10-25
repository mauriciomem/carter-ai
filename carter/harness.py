"""Harness validation: does OpenCode actually load Carter's agents?

``carter check`` runs ``opencode debug agents`` in the workspace. On OpenCode 2.1.4
that prints a JSON list of agents (``id``, ``permissions`` as ``{action, resource,
effect}`` rules, ...). OpenCode silently drops an agent file it rejects (malformed
YAML, a Copilot ``tools:`` list, ...), so a missing id is the signal.

Behaviour notes:

- The first call can return ``[]`` while OpenCode's per-user background service
  starts, so an empty or incomplete result is retried with bounded backoff.
- ``debug agents`` starts that background service if it is not running. It is the
  user's shared service; ``carter check`` leaves it running and never stops it.
- Effective permissions are OpenCode's base rules followed by the agent's emitted
  rules (with ``~`` expanded); OpenCode may append its own rules after them. The
  check therefore requires the emitted rules as one contiguous, in-order block.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_ATTEMPTS = 5
# Waits between attempts: 0.5 + 1 + 2 + 4 = 7.5 s worst case (plus call time).
DEFAULT_BACKOFF = (0.5, 1.0, 2.0, 4.0)
DEFAULT_TIMEOUT = 30.0

Rule = dict[str, Any]


@dataclass
class HarnessResult:
    status: Literal["ok", "fail", "skipped"]
    errors: list[str] = field(default_factory=list)
    warning: str | None = None


class _CallError(Exception):
    """One ``debug agents`` call failed in a way worth reporting."""


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _expand(rule: Rule, home: str | None) -> Rule:
    resource = str(rule.get("resource", ""))
    if resource == "~" or resource.startswith("~/"):
        base = home if home is not None else os.path.expanduser("~")
        resource = base + resource[1:]
    return {"action": rule.get("action"), "resource": resource, "effect": rule.get("effect")}


def _contains_block(effective: Sequence[Rule], block: Sequence[Rule]) -> bool:
    n = len(block)
    if n == 0:
        return True
    return any(list(effective[i : i + n]) == list(block) for i in range(len(effective) - n + 1))


def _call(opencode: str, cwd: Path, runner: Callable[..., Any], timeout: float) -> list[dict]:
    try:
        proc = runner(
            [opencode, "debug", "agents"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except OSError as exc:
        raise _CallError(f"could not run `opencode debug agents`: {exc}") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        tail = f": {detail[-1]}" if detail else ""
        raise _CallError(f"`opencode debug agents` exited {proc.returncode}{tail}")
    try:
        data = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise _CallError(f"`opencode debug agents` printed unparsable output ({exc.msg})") from exc
    if not isinstance(data, list):
        raise _CallError("`opencode debug agents` printed unparsable output (expected a list)")
    return [a for a in data if isinstance(a, dict)]


def validate_agents(
    workspace: Path,
    expected: dict[str, list[Rule] | None],
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] | None = None,
    sleep: Callable[[float], None] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: Sequence[float] = DEFAULT_BACKOFF,
    timeout: float = DEFAULT_TIMEOUT,
    home: str | None = None,
) -> HarnessResult:
    """Check that OpenCode loads every agent in ``expected`` with its emitted rules.

    ``expected`` maps agent id (file stem, suffix included) to its emitted
    ``permissions:`` list, or ``None`` to check presence only.
    """
    opencode = (which or _which)("opencode")
    if not opencode:
        return HarnessResult(
            "skipped",
            warning="opencode not found on PATH — skipping harness validation "
            "(`opencode debug agents`).",
        )
    do_sleep = sleep or time.sleep

    agents: dict[str, dict] = {}
    last_error: str | None = None
    for attempt in range(max(1, attempts)):
        if attempt:
            do_sleep(backoff[min(attempt - 1, len(backoff) - 1)] if backoff else 0)
        try:
            agents = {str(a.get("id")): a for a in _call(opencode, workspace, runner, timeout)}
            last_error = None
        except subprocess.TimeoutExpired:
            return HarnessResult("fail", [f"`opencode debug agents` timed out after {timeout:g}s"])
        except _CallError as exc:
            last_error = str(exc)
            continue
        if all(name in agents for name in expected):
            break

    if last_error:
        return HarnessResult("fail", [last_error])
    if not agents:
        return HarnessResult(
            "fail", [f"`opencode debug agents` listed no agents after {max(1, attempts)} attempts"]
        )

    errors: list[str] = []
    for name, rules in expected.items():
        loaded = agents.get(name)
        if loaded is None:
            errors.append(
                f"{name}: not loaded by OpenCode — its agent file is likely malformed "
                "or uses a key OpenCode rejects (e.g. a Copilot `tools:` list). "
                "Run `carter update` to re-render it."
            )
            continue
        effective = loaded.get("permissions")
        if rules is None or not isinstance(effective, list):
            continue
        block = [_expand(r, home) for r in rules if isinstance(r, dict)]
        if not _contains_block([_expand(r, None) for r in effective if isinstance(r, dict)], block):
            errors.append(
                f"{name}: effective OpenCode permissions do not contain the emitted "
                "`permissions:` rules in order after OpenCode's base rules."
            )
    return HarnessResult("fail" if errors else "ok", errors)
