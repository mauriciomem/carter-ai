"""Harness validation: does OpenCode actually load Carter's agents?

``carter check`` runs ``opencode debug agents`` in the workspace. On OpenCode 2.1.4
that prints a JSON list of agents (``id``, ``permissions`` as ``{action, resource,
effect}`` rules, ...). OpenCode silently drops an agent file it rejects (malformed
YAML, an unknown key, ...), so a missing id is the signal.

Behaviour notes:

- ``debug agents`` is answered by OpenCode's per-user background service and
  starts it if it is not running. It is the user's shared service; ``carter
  check`` leaves it running and never stops it. (``--standalone`` exists only on
  the root command and is rejected by ``debug agents`` on 2.1.0-2.1.4.)
- The service reloads agent files from a file watcher, so right after an edit it
  can still answer with the previous list (observed: stale for < 0.4 s), and the
  first call after start-up can return ``[]``. Two guards: wait until the newest
  agent file is ``settle`` seconds old before the first call, and treat a result
  as stale unless every agent's description, model and permission block match
  what was rendered — retrying with bounded backoff until they do.
- ``debug config`` (OpenCode 2.1.4) prints a JSON list of config sources, not one object:
  ``document`` entries carry each parsed file as ``info``; a file that does not parse has no
  entry; a statement OpenCode rejects is simply absent. ``read_debug_config`` folds the
  documents into one mapping. Right after a write the service can still show the old file
  for a moment (the guard writer re-reads), and the first ``debug agents`` can be ``[]``.
- Effective permissions are OpenCode's base rules followed by the agent's emitted
  rules (with ``~`` expanded); OpenCode may append its own rules after them. The
  check therefore requires the emitted rules as one contiguous, in-order block.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

DEFAULT_ATTEMPTS = 5
# Waits between attempts: 0.5 + 1 + 2 + 4 = 7.5 s worst case (plus call time).
DEFAULT_BACKOFF = (0.5, 1.0, 2.0, 4.0)
DEFAULT_TIMEOUT = 30.0
# Minimum age of the newest agent file before the first call (file-watcher lag).
DEFAULT_SETTLE = 1.5
STALE_HINT = (
    "OpenCode may be serving stale agent config (its background service reloads "
    "files asynchronously); re-run `carter check` to confirm."
)

Rule = dict[str, Any]


@dataclass
class HarnessResult:
    status: Literal["ok", "fail", "skipped"]
    errors: list[str] = field(default_factory=list)
    warning: str | None = None


@dataclass(frozen=True)
class Expected:
    """What one rendered agent should look like once OpenCode loads it.

    ``None`` fields are not compared. ``model`` is ``provider/model[#variant]``.
    """

    rules: list[Rule] | None = None
    description: str | None = None
    model: str | None = None


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


def _model_string(model: Any) -> str | None:
    if not isinstance(model, dict):
        return None
    out = f"{model.get('providerID')}/{model.get('id')}"
    return f"{out}#{model['variant']}" if model.get("variant") else out


def _diff(
    agents: dict[str, dict], expected: dict[str, Expected], home: str | None
) -> tuple[list[str], dict[str, list[str]]]:
    """Return (not-loaded errors, field mismatches per listed agent)."""
    missing: list[str] = []
    mismatched: dict[str, list[str]] = {}
    for name, exp in expected.items():
        loaded = agents.get(name)
        if loaded is None:
            missing.append(
                f"{name}: not loaded by OpenCode — its agent file is likely malformed "
                "or uses a key OpenCode rejects. "
                "Run `carter update` to re-render it."
            )
            continue
        errors: list[str] = []
        if exp.description is not None and loaded.get("description") != exp.description:
            errors.append(f"{name}: OpenCode reports a different description than the agent file.")
        if exp.model is not None and _model_string(loaded.get("model")) != exp.model:
            errors.append(
                f"{name}: OpenCode reports model {_model_string(loaded.get('model'))!r}, "
                f"the agent file sets {exp.model!r}."
            )
        effective = loaded.get("permissions")
        if exp.rules is not None and isinstance(effective, list):
            block = [_expand(r, home) for r in exp.rules if isinstance(r, dict)]
            got = [_expand(r, None) for r in effective if isinstance(r, dict)]
            if not _contains_block(got, block):
                errors.append(
                    f"{name}: effective OpenCode permissions do not contain the emitted "
                    "`permissions:` rules in order after OpenCode's base rules."
                )
        if errors:
            mismatched[name] = errors
    return missing, mismatched


def validate_agents(
    workspace: Path,
    expected: Mapping[str, Expected | list[Rule] | None],
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] | None = None,
    sleep: Callable[[float], None] | None = None,
    clock: Callable[[], float] = time.time,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: Sequence[float] = DEFAULT_BACKOFF,
    timeout: float = DEFAULT_TIMEOUT,
    settle: float = DEFAULT_SETTLE,
    newest_change: float | None = None,
    home: str | None = None,
) -> HarnessResult:
    """Check that OpenCode loads every agent in ``expected`` as rendered.

    ``expected`` maps agent id (file stem, suffix included) to an ``Expected``;
    a bare rule list (or ``None``) checks permissions (or presence) only.
    ``newest_change`` is the newest agent-file mtime (``clock`` time base).
    """
    opencode = (which or _which)("opencode")
    if not opencode:
        return HarnessResult(
            "skipped",
            warning="opencode not found on PATH — skipping harness validation "
            "(`opencode debug agents`).",
        )
    do_sleep = sleep or time.sleep
    want = {k: v if isinstance(v, Expected) else Expected(rules=v) for k, v in expected.items()}

    if newest_change is not None:
        wait = settle - (clock() - newest_change)
        if wait > 0:
            do_sleep(min(wait, settle))

    agents: dict[str, dict] = {}
    missing: list[str] = []
    mismatched: dict[str, list[str]] = {}
    last_error: str | None = None
    tries = max(1, attempts)
    for attempt in range(tries):
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
        missing, mismatched = _diff(agents, want, home)
        if not missing and not mismatched:
            return HarnessResult("ok")

    if last_error:
        return HarnessResult("fail", [last_error])
    if not agents:
        return HarnessResult(
            "fail", [f"`opencode debug agents` listed no agents after {tries} attempts"]
        )
    errors = list(missing)
    if mismatched:
        errors += [e for errs in mismatched.values() for e in errs]
        names = ", ".join(mismatched)
        errors.append(f"{STALE_HINT} (affects {names}; {tries} attempts made)")
    return HarnessResult("fail", errors)


class DebugConfigError(Exception):
    """``opencode debug config`` could not be read or parsed.

    The message never carries OpenCode's output: the resolved config holds provider
    settings (RFC-0007 App C.6.3), so only exit codes and parser positions are reported."""


def read_debug_config(
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] | None = None,
    home: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Run ``opencode debug config`` (cwd ``$HOME``) and return the parsed JSON.

    The result is for in-memory comparison only: the caller must not log it or write it
    anywhere (it contains provider settings). Raises ``DebugConfigError``."""
    opencode = (which or _which)("opencode")
    if not opencode:
        raise DebugConfigError("opencode not found on PATH")
    try:
        proc = runner(
            [opencode, "debug", "config"],
            cwd=home if home is not None else Path.home(),
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise DebugConfigError(f"`opencode debug config` timed out after {timeout:g}s") from exc
    except OSError as exc:
        raise DebugConfigError(
            f"could not run `opencode debug config` ({type(exc).__name__})"
        ) from exc
    if proc.returncode != 0:
        raise DebugConfigError(f"`opencode debug config` exited {proc.returncode}")
    try:
        data = json.loads(proc.stdout or "")
    except json.JSONDecodeError as exc:
        raise DebugConfigError(
            f"`opencode debug config` printed unparsable output ({exc.msg} at {exc.pos})"
        ) from None
    return _resolve(data)


def _bad(why: str) -> DebugConfigError:
    return DebugConfigError(f"`opencode debug config` printed unparsable output ({why})")


def _merge(into: dict[str, Any], info: Mapping[str, Any]) -> None:
    """Fold one document's ``info`` into the resolved mapping: dict blocks (providers, agents)
    are extended key by key, lists (policies, an agent's permissions) are appended in order,
    anything else is overridden by the later source."""
    for key, value in info.items():
        current = into.get(key)
        if isinstance(value, dict) and isinstance(current, dict):
            _merge(current, value)
        elif isinstance(value, list) and isinstance(current, list):
            current.extend(value)
        else:
            into[key] = json.loads(json.dumps(value))  # a private copy


def _resolve(data: Any) -> dict[str, Any]:
    """The resolved config from ``debug config`` output, in either shape.

    OpenCode 2.1.4 prints a list of config sources (``document`` entries carrying the parsed
    file as ``info``, in precedence order, plus ``directory`` entries); other versions are
    taken to print one object. Anything else fails closed. Statements OpenCode rejected are
    absent from ``info`` and a file it could not parse has no ``document`` entry, so the
    callers' "is it still there" comparisons see exactly what OpenCode will enforce."""
    if isinstance(data, dict):
        return data
    if not isinstance(data, list) or not data:
        raise _bad("expected an object or a non-empty list of config sources")
    merged: dict[str, Any] = {}
    for source in data:
        if not isinstance(source, dict) or not isinstance(source.get("type"), str):
            raise _bad("a config source is not an object with a type")
        if source["type"] != "document":
            continue  # directories (and kinds this version does not know) carry no settings
        info = source.get("info")
        if not isinstance(info, dict):
            raise _bad("a config document has no info object")
        for block in ("policies", "providers"):
            kind = list if block == "policies" else dict
            if block in info and not isinstance(info[block], kind):
                raise _bad(f"`{block}` has an unexpected type")
        _merge(merged, info)
    return merged


def provider_ids(debug_config: Mapping[str, Any]) -> set[str]:
    """Provider ids in a resolved config (``providers``)."""
    block = debug_config.get("providers")
    return {str(k) for k in block} if isinstance(block, dict) else set()


def policy_statements(debug_config: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The ``{action, resource, effect}`` statements OpenCode resolved, in order."""
    block = debug_config.get("policies")
    return [s for s in block if isinstance(s, dict)] if isinstance(block, list) else []


def read_agents(
    *,
    runner: Callable[..., Any] = subprocess.run,
    which: Callable[[str], str | None] | None = None,
    home: Path | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    sleep: Callable[[float], None] | None = None,
    attempts: int = DEFAULT_ATTEMPTS,
    backoff: Sequence[float] = DEFAULT_BACKOFF,
) -> list[dict[str, Any]]:
    """Every agent OpenCode knows, with its resolved ``permissions`` (`opencode debug agents`).

    The first call after OpenCode's service starts can print ``[]`` (observed on 2.1.4); an
    empty list is never real (the built-ins always exist), so it is retried with the same
    bounded backoff as ``validate_agents``. Raises ``DebugConfigError``."""
    opencode = (which or _which)("opencode")
    if not opencode:
        raise DebugConfigError("opencode not found on PATH")
    do_sleep = sleep or time.sleep
    tries = max(1, attempts)
    for attempt in range(tries):
        if attempt:
            do_sleep(backoff[min(attempt - 1, len(backoff) - 1)] if backoff else 0)
        try:
            agents = _call(opencode, home if home is not None else Path.home(), runner, timeout)
        except subprocess.TimeoutExpired as exc:
            raise DebugConfigError(f"`opencode debug agents` timed out after {timeout:g}s") from exc
        except _CallError as exc:
            raise DebugConfigError(str(exc)) from exc
        if any(isinstance(a.get("id"), str) for a in agents):
            return agents
    raise DebugConfigError(f"`opencode debug agents` listed no agents after {tries} attempts")


def read_agent_ids(**kwargs: Any) -> list[str]:
    """Ids of every agent OpenCode knows, in order (see ``read_agents``)."""
    return [str(a["id"]) for a in read_agents(**kwargs) if isinstance(a.get("id"), str)]


DENIED_ACTIONS = ("carter_push",)
EXEMPT_AGENTS = ("carter-devops", "devops")


def _action_matches(pattern: str, action: str) -> bool:
    return fnmatch.fnmatchcase(action, pattern)


def agent_deny_gaps(
    agents: Sequence[Mapping[str, Any]], *, exempt: Sequence[str] = EXEMPT_AGENTS
) -> list[tuple[str, str]]:
    """``(agent, action)`` pairs where the effective rule is not ``deny`` (last matching rule
    wins, resource ``*``), for every agent except ``exempt`` (spike D)."""
    gaps: list[tuple[str, str]] = []
    for agent in agents:
        name = str(agent.get("id", ""))
        if name in exempt:
            continue
        rules = [r for r in agent.get("permissions", []) if isinstance(r, dict)]
        for action in DENIED_ACTIONS:
            effect = None
            for rule in rules:
                if _action_matches(str(rule.get("action", "")), action) and rule.get(
                    "resource"
                ) in (
                    "*",
                    None,
                ):
                    effect = rule.get("effect")
            if effect != "deny":
                gaps.append((name, action))
    return gaps
