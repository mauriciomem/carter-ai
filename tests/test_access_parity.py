"""`carter access`, the `[access]` schema and the docs name the same ids, in both directions.

The schema (``carter.access``) is the only source. A new id there that has no label, no
"enforced by" entry or no docs row fails here; so does an id printed that the schema does not know.
"""

from __future__ import annotations

import re

import pytest
from click.testing import CliRunner

from carter import access
from carter.access import (
    CAPABILITIES,
    CAPABILITY_IDS,
    ENFORCED,
    FLOOR,
    FLOOR_IDS,
    GROUP_FLOORS,
    LEVELS,
    resolve,
)
from carter.cli import main
from carter.identity.policyset import consent_groups
from docs_support import text

ALL_IDS = {*CAPABILITY_IDS, *FLOOR_IDS}
ID_COLUMN = re.compile(r"\[([a-z_]+)\]")


def _printed_ids(*args: str) -> list[str]:
    result = CliRunner().invoke(main, ["access", *args])
    assert result.exit_code == 0, result.output
    return ID_COLUMN.findall(result.stdout)


@pytest.mark.parametrize("args", [(), ("-v",)])
def test_every_printed_id_is_in_the_schema_and_every_schema_id_is_printed(
    args: tuple[str, ...],
) -> None:
    printed = _printed_ids(*args)
    assert set(printed) == ALL_IDS  # both directions
    assert len(printed) == len(ALL_IDS)  # each id once


def test_the_ids_printed_are_the_keys_the_config_accepts() -> None:
    for cap in CAPABILITIES:
        for value in ("allowed", "ask", "denied"):
            problem = resolve({cap.id: value}).notes
            loosest_ok = access.RANK[value] >= access.RANK[cap.max]
            assert (problem == ()) == loosest_ok, (cap.id, value, problem)
    for floor_id in FLOOR_IDS:
        assert resolve({floor_id: "allowed"}).notes[0] == (
            f"config.toml [access]: {floor_id} is fixed at never"
        )
    assert resolve({"level": "guarded"}).notes == ()


def test_the_output_shows_the_schema_labels() -> None:
    out = CliRunner().invoke(main, ["access"]).stdout
    for cap in CAPABILITIES:
        assert f"{cap.label}" in out
    for _id, label in FLOOR:
        assert label in out


def test_every_row_has_a_label_a_layer_and_a_strength() -> None:
    assert all(c.label.strip() for c in CAPABILITIES)
    assert all(label.strip() for _id, label in FLOOR)
    labels = [c.label for c in CAPABILITIES] + [label for _id, label in FLOOR]
    assert len(set(labels)) == len(labels)
    assert set(ENFORCED) == ALL_IDS  # a new id without an "enforced by" entry fails
    assert all(layer and strength for layer, strength in ENFORCED.values())


def test_the_groups_named_for_the_floor_are_real_consent_groups() -> None:
    real = {g.id for g in consent_groups()}
    assert set(GROUP_FLOORS) <= real
    assert {"hooks", "repo_hooks", "config-edit"} <= real
    named = {floor_id for ids in GROUP_FLOORS.values() for floor_id in ids}
    assert named <= set(FLOOR_IDS)


def _config_section() -> str:
    """The `[access]` part of the configuration reference."""
    body = text("reference/configuration.md")
    start = body.index("### access")
    end = body.index("\n### ", start + 1)
    return body[start:end]


def _table_rows(block: str) -> list[list[str]]:
    rows = []
    for line in block.splitlines():
        if line.startswith("|") and not set(line) <= set("|- "):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_the_configuration_docs_list_the_same_ids_as_the_output() -> None:
    rows = _table_rows(_config_section())
    ids = {m.group(1) for row in rows for m in [re.match(r"`([a-z_]+)`$", row[0])] if m}
    assert ids - {"level"} == ALL_IDS


def test_the_configuration_docs_match_the_presets_and_ceilings() -> None:
    rows = {row[0].strip("`"): row for row in _table_rows(_config_section())}
    for cap in CAPABILITIES:
        row = rows[cap.id]
        assert row[2:5] == [cap.preset(level) for level in LEVELS], cap.id
        assert row[5] == cap.max, cap.id
    for floor_id in FLOOR_IDS:
        assert "never" in rows[floor_id], floor_id


def test_the_docs_name_the_command_in_the_cli_reference() -> None:
    assert "## carter access" in text("reference/cli.md")
