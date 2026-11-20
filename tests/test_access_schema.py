"""The access-level schema: ids, labels, presets and per-row maxima.

The preset table below is typed out from the accepted design on purpose: a change to the schema must
also change this file.
"""

from __future__ import annotations

import pytest

from carter import access
from carter.access import CAPABILITIES, CAPABILITY_IDS, FLOOR, FLOOR_IDS, LEVELS, RANK

# The accepted preset table: id -> (strict, guarded, relaxed, max)
RFC_TABLE = {
    "workspace_edit": ("allowed", "allowed", "allowed", "allowed"),
    "run_commands": ("allowed", "allowed", "allowed", "allowed"),
    "git_commit": ("allowed", "allowed", "allowed", "allowed"),
    "github_read": ("allowed", "allowed", "allowed", "allowed"),
    "pr_write": ("ask", "allowed", "allowed", "allowed"),
    "issue_write": ("denied", "ask", "allowed", "allowed"),
    "destructive": ("denied", "ask", "ask", "ask"),
    "infra_apply": ("denied", "ask", "ask", "ask"),
    "opencode_config": ("denied", "denied", "denied", "denied"),
}
# The fixed floor
RFC_FLOOR = ("push", "gh_api", "github_admin", "sudo", "secrets", "carter_internals")


def test_ids_are_the_nine_of_the_rfc_in_order():
    assert tuple(RFC_TABLE) == CAPABILITY_IDS
    assert len(CAPABILITY_IDS) == 9


def test_floor_ids_are_the_six_of_the_rfc():
    assert FLOOR_IDS == RFC_FLOOR


def test_every_row_has_a_label():
    assert all(c.label.strip() for c in CAPABILITIES)
    assert all(label.strip() for _id, label in FLOOR)


def test_ids_are_unique_and_floor_never_overlaps():
    everything = CAPABILITY_IDS + FLOOR_IDS
    assert len(set(everything)) == len(everything) == 15


def test_levels_are_strict_guarded_relaxed():
    assert LEVELS == ("strict", "guarded", "relaxed")


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("cap_id", RFC_TABLE)
def test_preset_matches_the_rfc_table(level, cap_id):
    cap = next(c for c in CAPABILITIES if c.id == cap_id)
    assert cap.preset(level) == RFC_TABLE[cap_id][LEVELS.index(level)]


@pytest.mark.parametrize("cap_id", RFC_TABLE)
def test_max_matches_the_rfc_table(cap_id):
    cap = next(c for c in CAPABILITIES if c.id == cap_id)
    assert cap.max == RFC_TABLE[cap_id][3]


@pytest.mark.parametrize("cap", CAPABILITIES, ids=CAPABILITY_IDS)
def test_no_preset_is_looser_than_its_max(cap):
    assert all(RANK[cap.preset(level)] >= RANK[cap.max] for level in LEVELS)


@pytest.mark.parametrize("cap", CAPABILITIES, ids=CAPABILITY_IDS)
def test_levels_only_loosen_from_strict_to_relaxed(cap):
    ranks = [RANK[cap.preset(level)] for level in LEVELS]
    assert ranks == sorted(ranks, reverse=True)


def test_relaxed_is_guarded_plus_issue_write_allowed():
    differs = [c.id for c in CAPABILITIES if c.preset("relaxed") != c.preset("guarded")]
    assert differs == ["issue_write"]


def test_role_sets_match_the_shipped_allowlist():
    """`access` keeps its own role sets (no import cycle with config); this pins them."""
    from carter.config import AGENT_ALLOWLIST

    writers = {r for r, cats in AGENT_ALLOWLIST.items() if "local-write" in cats}
    infra = {r for r, cats in AGENT_ALLOWLIST.items() if "dangerous" in cats}
    assert writers == access.LOCAL_WRITE_ROLES
    assert infra == access.INFRA_ROLES
