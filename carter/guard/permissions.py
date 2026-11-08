"""Per-agent permission denies for the agents Carter did not write (D46, F6).

``carter_push`` is denied per agent, never as global policies: devops must
stay able to call it. Carter's own agents get the rule in their rendered front matter
(``carter.config``); the **built-in** agents (`build`, `plan`, `general`, ...) are denied
here, in the user's global OpenCode config: ``agents.<name>.permissions`` is an ordered rule
list and Carter appends ``{action: <tool>, resource: "*", effect: "deny"}`` (last match
wins, so it wins over any earlier user rule). Their only effect is hiding a Carter tool, so
non-Carter agents are otherwise untouched (D71).

The user's other keys and rules are merged, never replaced. A rule or value that is already
exactly as Carter would write it is ``preexisting`` and never removed. Removal deletes only
a recorded rule that is still there unchanged, and prunes only containers it emptied.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from carter.guard.configwrite import PolicyWriteError
from carter.guard.state import GuardState

KEY_PREFIX = "permission."


@dataclass
class PermDiff:
    added: list[str] = field(default_factory=list)  # "agent:tool"
    removed: list[str] = field(default_factory=list)
    preexisting: list[str] = field(default_factory=list)
    kept_edited: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    records: list[dict[str, Any]] = field(default_factory=list)


def _rule(tool: str) -> dict[str, str]:
    return {"action": tool, "resource": "*", "effect": "deny"}


def _map(parent: dict[str, Any], key: str, what: str) -> dict[str, Any] | None:
    value = parent.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise PolicyWriteError(
            f"`{what}` in the OpenCode config is not an object; nothing was written"
        )
    return value


def _drop_last(items: list[Any], wanted: dict[str, str]) -> bool:
    for i in range(len(items) - 1, -1, -1):
        if items[i] == wanted:
            del items[i]
            return True
    return False


def _prune(config: dict[str, Any], map_key: str, agent: str, leaf: str) -> None:
    """Remove ``leaf`` and ``agent`` entries that Carter just emptied, and the map itself."""
    entries = config.get(map_key)
    if not isinstance(entries, dict):
        return
    entry = entries.get(agent)
    if isinstance(entry, dict):
        if entry.get(leaf) in ([], {}):
            del entry[leaf]
        if not entry:
            del entries[agent]
    if not entries:
        del config[map_key]


def remove_owned(config: dict[str, Any], state: GuardState, diff: PermDiff) -> None:
    """Delete the recorded, still-unchanged denies (preexisting ones are never touched)."""
    for rec in state.owned_permissions():
        agent, tool = rec["agent"], rec["key"].removeprefix(KEY_PREFIX)
        entry = (_map(config, "agents", "agents") or {}).get(agent)
        rules = entry.get("permissions") if isinstance(entry, dict) else None
        gone = isinstance(rules, list) and _drop_last(rules, _rule(tool))
        if gone:
            _prune(config, "agents", agent, "permissions")
        (diff.removed if gone else diff.kept_edited).append(f"{agent}:{tool}")


def add_wanted(
    config: dict[str, Any], agents: Sequence[str], tools: Sequence[str], diff: PermDiff
) -> None:
    """Add every (agent, tool) deny that is not already there; record all of them."""
    for agent in agents:
        for tool in tools:
            owned = _add(config, agent, tool)
            label = f"{agent}:{tool}"
            (diff.added if owned else diff.preexisting).append(label)
            diff.records.append(
                {
                    "agent": agent,
                    "key": f"{KEY_PREFIX}{tool}",
                    "value": "deny",
                    "preexisting": not owned,
                }
            )


def _add(config: dict[str, Any], agent: str, tool: str) -> bool:
    agents = config.setdefault("agents", {})
    if not isinstance(agents, dict):
        raise PolicyWriteError(
            "`agents` in the OpenCode config is not an object; nothing was written"
        )
    entry = agents.setdefault(agent, {})
    if not isinstance(entry, dict):
        raise PolicyWriteError(f"`agents.{agent}` is not an object; nothing was written")
    rules = entry.setdefault("permissions", [])
    if not isinstance(rules, list):
        raise PolicyWriteError(f"`agents.{agent}.permissions` is not a list; nothing was written")
    if _rule(tool) in rules:
        return False
    rules.append(_rule(tool))
    return True


def converge(
    config: dict[str, Any], state: GuardState, agents: Sequence[str], tools: Sequence[str]
) -> PermDiff:
    """Remove what Carter recorded, then add what is wanted (idempotent when nothing changed).

    ``added``/``removed`` are the net change against the recorded denies; ``records`` is
    what guard state should hold afterwards."""
    before = {
        f"{r['agent']}:{r['key'].removeprefix(KEY_PREFIX)}" for r in state.owned_permissions()
    }
    diff = PermDiff()
    remove_owned(config, state, diff)
    diff.removed = []
    add_wanted(config, agents, tools, diff)
    owned_now = set(diff.added)
    diff.added = sorted(owned_now - before)
    diff.removed = sorted(before - owned_now)
    return diff


def present(config: dict[str, Any], record: dict[str, Any]) -> bool:
    """Is the recorded per-agent deny still in ``config`` exactly as Carter wrote it?"""
    agent, tool = record["agent"], record["key"].removeprefix(KEY_PREFIX)
    entry = (config.get("agents") or {}).get(agent)
    rules = entry.get("permissions") if isinstance(entry, dict) else None
    return isinstance(rules, list) and _rule(tool) in rules
