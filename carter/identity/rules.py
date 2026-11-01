"""Loader for ``g2_rules.json``, the single data file behind Carter's agent rules.

RFC-0007 Appendix C.1: the skill text, the eval ``commands_not_contain`` lists and,
in later slices, the gate, the guard script and the policy writer are derived from this
file, and parity tests fail on drift. Do not copy its lists into other files; render them
with ``render_forbidden_block`` / ``render_forbidden_commands``.

Slice 1 uses the signal tables and the ``forbidden`` list. ``isolation_vars``,
``gh_read_allowlist`` and ``policy_set`` are present but empty (``reserved``) so later
slices fill them without a schema change. Every ``forbidden`` entry names the RFC row it
comes from (``rfc``) and the first slice that enforces it (``applies_from``): the file is
strict JSON and cannot carry comments. A class not yet enforced (push verbs: 1G) is data,
not skill text, until ``CURRENT_SLICE`` reaches it.

Stdlib-only; the file is read through ``importlib.resources`` so it works from a wheel.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Any

SLICES = ("1", "1G", "2a", "2b", "2c", "B", "CI-E")
CURRENT_SLICE = "1"  # bumped by the slice that starts enforcing more classes
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
    applies_from: str
    items: tuple[str, ...]
    literals: tuple[str, ...]
    rfc: str
    verbs: tuple[str, ...] = ()
    scoped_flags: tuple[dict[str, Any], ...] = ()
    note: str = ""


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


@cache
def load_rules() -> Rules:
    text = resources.files("carter.identity").joinpath("g2_rules.json").read_text("utf-8")
    data = json.loads(text)
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
        forbidden=tuple(
            ForbiddenClass(
                id=e["id"],
                class_=e["class"],
                applies_from=e["applies_from"],
                items=tuple(e["items"]),
                literals=tuple(e["literals"]),
                rfc=e["rfc"],
                verbs=tuple(e.get("verbs", ())),
                scoped_flags=tuple(e.get("scoped_flags", ())),
                note=e.get("note", ""),
            )
            for e in data["forbidden"]
        ),
    )


def forbidden_classes(
    current: str = CURRENT_SLICE, *, all_slices: bool = False
) -> tuple[ForbiddenClass, ...]:
    """The classes enforced at slice ``current`` (all of them with ``all_slices``)."""
    return tuple(
        e
        for e in load_rules().forbidden
        if all_slices or SLICES.index(e.applies_from) <= SLICES.index(current)
    )


def render_forbidden_commands(current: str = CURRENT_SLICE) -> list[str]:
    """Literal fragments an agent's commands must not contain, in file order, unique.

    This is the eval ``commands_not_contain`` list."""
    out: list[str] = []
    for entry in forbidden_classes(current):
        out += [lit for lit in entry.literals if lit not in out]
    return out


def render_forbidden_block(current: str = CURRENT_SLICE) -> str:
    """The marked Markdown block of forbidden items that the carter-ops skill embeds."""
    lines = [BEGIN_MARK, "Never run any of these (generated from `g2_rules.json`):", ""]
    for entry in forbidden_classes(current):
        items = ", ".join(f"`{item}`" for item in entry.items)
        note = f" {entry.note}" if entry.note else ""
        lines.append(f"- **{entry.class_}:** {items}.{note}")
    lines.append(END_MARK)
    return "\n".join(lines) + "\n"


def pollution_hits(env: Mapping[str, str], *, home: str) -> list[str]:
    """Names in ``env`` that make a server environment polluted (App C.1).

    Signals match by name (any value); isolation markers only by Carter's exact value, so
    normal desktop state (``SSH_AUTH_SOCK``, another ``DBUS_SESSION_BUS_ADDRESS``) never
    counts. The ``GIT_CONFIG_KEY_n/VALUE_n`` pair marker needs the isolation entries and
    is evaluated by the slice that writes them (2a). Values are never returned."""
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


def warn_hits(env: Mapping[str, str]) -> list[str]:
    """Variables that only warrant a ``check --host`` WARN (``GH_TOKEN``/``GITHUB_TOKEN``)."""
    return [name for name in load_rules().warn_only if name in env]
