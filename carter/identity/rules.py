"""Loader for ``g2_rules.json``, the single data file behind Carter's agent rules.

The skill text, the eval ``commands_not_contain`` lists, the gate, the guard script and the
policy writer are all derived from this file, and parity tests fail on drift. Do not copy its
lists into other files; render them with ``render_forbidden_block`` /
``render_forbidden_commands``. The file is strict JSON, so it carries no comments.

Stdlib-only; the file is read through ``importlib.resources`` so it works from a wheel.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

BEGIN_MARK = "<!-- forbidden:begin -->"
END_MARK = "<!-- forbidden:end -->"


@dataclass(frozen=True)
class Marker:
    name: str
    match: str
    value: str


@dataclass(frozen=True)
class ForbiddenClass:
    id: str
    class_: str
    items: tuple[str, ...]
    literals: tuple[str, ...]
    verbs: tuple[str, ...] = ()
    scoped_flags: tuple[dict[str, Any], ...] = ()
    note: str = ""
    group: str = "g2"  # the consent group whose decline skips this rule (gate --skip-groups)
    hint: str = ""  # one line, shown to the model with the rule id; no leading `!`
    item_groups: tuple[tuple[str, str], ...] = ()  # per-item group overrides (sudo/docker/podman)


@dataclass(frozen=True)
class GateRule:
    """A rule id only the gate raises; the other ids are ``ForbiddenClass.id``."""

    id: str
    hint: str


@dataclass(frozen=True)
class Rules:
    version: int
    agent_signals: tuple[str, ...]
    human_signals: tuple[str, ...]
    isolation_markers: tuple[Marker, ...]
    pollution_by_name: tuple[str, ...]
    pollution_by_value: tuple[str, ...]
    not_pollution: tuple[str, ...]
    warn_only: tuple[str, ...]
    credential_paths: tuple[str, ...]
    control_paths: tuple[str, ...]
    forbidden: tuple[ForbiddenClass, ...]
    isolation_vars: tuple[str, ...] = ()
    shim_y_ops: tuple[str, ...] = ()  # `ssh-keygen -Y` operations the shim passes through


@cache
def _data() -> dict[str, Any]:
    text = resources.files("carter.identity").joinpath("g2_rules.json").read_text("utf-8")
    return json.loads(text)


def gate_rules() -> tuple[GateRule, ...]:
    """The rule ids that exist only in the gate."""
    return tuple(GateRule(**row) for row in _data()["gate_rules"])


def plugin_defaults() -> dict[str, Any]:
    """Defaults for ``isolation.json``'s ``plugin`` block; paths are filled at install."""
    return dict(_data()["plugin"])


def human_identity_rules() -> dict[str, Any]:
    """The values that mean "git had no real human identity": fallback emails (``*`` globs,
    compared case-insensitively) and fallback names. One copy; the entry, ``--emit``, the checks
    and the rendered guard script all read it."""
    return dict(_data()["human_identity"])


def shim_data() -> dict[str, Any]:
    """The shim contract: allowed ``-Y`` operations, the signing namespace and options,
    and the minimum git and OpenSSH versions. One copy; the shim generator and the tests read it."""
    return dict(_data()["shim"])


@cache
def load_rules() -> Rules:
    data = _data()
    return Rules(
        version=data["version"],
        agent_signals=tuple(data["agent_signals"]),
        human_signals=tuple(data["human_signals"]),
        isolation_markers=tuple(Marker(**m) for m in data["isolation_markers"]),
        pollution_by_name=tuple(data["pollution_set"]["by_name"]),
        pollution_by_value=tuple(data["pollution_set"]["by_value"]),
        not_pollution=tuple(data["not_pollution"]),
        warn_only=tuple(data["warn_only"]),
        credential_paths=tuple(data["credential_paths"]),
        control_paths=tuple(data["control_paths"]),
        isolation_vars=tuple(data["isolation_vars"]),
        shim_y_ops=tuple(data["shim"]["y_ops"]),
        forbidden=tuple(
            ForbiddenClass(
                id=e["id"],
                class_=e["class"],
                items=tuple(e["items"]),
                literals=tuple(e["literals"]),
                verbs=tuple(e.get("verbs", ())),
                scoped_flags=tuple(e.get("scoped_flags", ())),
                note=e.get("note", ""),
                group=e["group"],
                hint=e["hint"],
                item_groups=tuple(e.get("item_groups", {}).items()),
            )
            for e in data["forbidden"]
        ),
    )


def forbidden_classes() -> tuple[ForbiddenClass, ...]:
    """The classes the gate and the skill text enforce, in file order."""
    return load_rules().forbidden


def render_forbidden_commands() -> list[str]:
    """Literal fragments an agent's commands must not contain, in file order, unique.

    This is the eval ``commands_not_contain`` list."""
    out: list[str] = []
    for entry in forbidden_classes():
        out += [lit for lit in entry.literals if lit not in out]
    return out


def render_forbidden_block() -> str:
    """The marked Markdown block of forbidden items that the carter-ops skill embeds."""
    lines = [BEGIN_MARK, "Never run any of these (generated from `g2_rules.json`):", ""]
    for entry in forbidden_classes():
        items = ", ".join(f"`{item}`" for item in entry.items)
        note = f" {entry.note}" if entry.note else ""
        lines.append(f"- **{entry.class_}:** {items}.{note}")
    lines.append(END_MARK)
    return "\n".join(lines) + "\n"


def pollution_hits(env: Mapping[str, str], *, home: str) -> list[str]:
    """Names in ``env`` that make a server environment polluted.

    Signals match by name (any value); isolation markers only by Carter's exact value, so
    normal desktop state (``SSH_AUTH_SOCK``, another ``DBUS_SESSION_BUS_ADDRESS``) never
    counts. Values are never returned."""
    r = load_rules()
    hits = [name for name in (*r.agent_signals, *r.human_signals) if name in env]
    for marker in r.isolation_markers:
        value = env.get(marker.name)
        if value is None:
            continue
        expected = marker.value.replace("<home>", home)
        if (marker.match == "contains" and expected in value) or (
            marker.match == "equals" and value == expected
        ):
            hits.append(marker.name)
    return hits


STRONG_AGENT_SIGNAL = "CARTER_AGENT_SHELL"


def is_agent(env: Mapping[str, str]) -> bool:
    """Is ``env`` an agent shell? The Python mirror of ``carter-guard``'s check.

    Agent iff ``CARTER_AGENT_SHELL=1``, or any other ``agent_signals`` name is present
    and no ``human_signals`` name is. Names come from the data file, so adding one there
    changes this too. No positive "broker" marker is honoured (any agent shell could forge
    it). Presence is what counts, never the value, except for the strong marker."""
    r = load_rules()
    if env.get(STRONG_AGENT_SIGNAL) == "1":
        return True
    weak = (name for name in r.agent_signals if name != STRONG_AGENT_SIGNAL)
    return any(name in env for name in weak) and not any(n in env for n in r.human_signals)
