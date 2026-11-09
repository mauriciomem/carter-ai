"""Pin ``carter.yaml identity.role`` / ``require_tier`` into ``~/.carter/config.toml``.

Only the human-run ``carter update`` calls this. ``carter.yaml`` is writable by an agent,
so it never changes attribution at runtime; the pin is the explicit, displayed, confirmed
copy under ``[workspaces."<abs path>"]`` (key: ``workspace.workspace_key``).

``plan_pin`` is pure (a diff and a refusal reason); ``apply_pin`` writes through the
schema-only writer, which refuses to drop unmodelled keys.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from carter.identity.errors import E_ROLE_B_TIER
from carter.identity.schema import TIERS, IdentityConfig, Workspace
from carter.identity.writer import write_config

UNSET = "(unset)"


@dataclass(frozen=True)
class Change:
    field: str
    old: str
    new: str


@dataclass(frozen=True)
class PinPlan:
    key: str
    role: str  # desired from carter.yaml, "" = unset
    require_tier: str
    changes: tuple[Change, ...]
    max_tier: str  # hand-edited cap, shown, never changed here
    refusal: str = ""


def plan_pin(cfg: IdentityConfig, key: str, *, role: str, require_tier: str) -> PinPlan:
    """What pinning would change for workspace ``key``; ``refusal`` is set if it must not."""
    current = cfg.workspaces.get(key, Workspace())
    changes = tuple(
        Change(name, old or UNSET, new or UNSET)
        for name, old, new in (
            ("role", current.role, role),
            ("require_tier", current.require_tier, require_tier),
        )
        if old != new
    )
    refusal = ""
    cap = current.max_tier
    if cap and role == "author":  # role author needs T2 and every cap is below it; never downgraded
        refusal = (
            f"{E_ROLE_B_TIER}: role author needs LLM signing on, but max_tier {cap} "
            "(hand-edited in config.toml) caps this workspace below it; remove the cap or keep "
            "role co-author"
        )
    elif cap and require_tier and TIERS.index(cap) < TIERS.index(require_tier):
        refusal = (
            f"max_tier {cap} (hand-edited in config.toml) is below require_tier {require_tier}; "
            "lower require_tier or raise max_tier"
        )
    return PinPlan(key, role, require_tier, changes, cap, refusal)


def apply_pin(cfg: IdentityConfig, plan: PinPlan, path: Path | None = None) -> bool:
    """Write the pin. Returns ``False`` if the file already holds it. An entry left
    with nothing set is dropped. Raises what ``write_config`` raises."""
    entry = replace(
        cfg.workspaces.get(plan.key, Workspace()), role=plan.role, require_tier=plan.require_tier
    )
    workspaces = {k: v for k, v in cfg.workspaces.items() if k != plan.key}
    if entry != Workspace():
        workspaces[plan.key] = entry
    return write_config(replace(cfg, workspaces=workspaces, state="current"), path)
