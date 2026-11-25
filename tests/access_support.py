"""Test helper: the guard state a machine has after `carter guard install` accepted its groups."""

from __future__ import annotations

from carter.guard.state import GuardState, save
from carter.identity.policyset import consent_groups
from carter.install.paths import guard_state_path

ALL_GROUPS = ("g2", "hooks", "docker", "read-edit-denies", "config-edit")


def record_groups(*groups: str) -> None:
    """Record ``groups`` as accepted (at their current revision) in the fixture home's state."""
    revs = {g.id: g.rev for g in consent_groups()}
    state = GuardState()
    for group in groups:
        state.consent(group, "accepted", "2026-11-21", revs[group])
    path = guard_state_path(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    save(state, path)
