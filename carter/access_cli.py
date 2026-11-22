"""``carter access``: what agents may do here. Read-only: no writes, no network.

The rows come from the schema in ``carter.access`` and the values from its resolver, the same
ones the renderer uses; nothing is computed here, with one exception: the per-workspace opt-out
of ``opencode_config`` is applied on top of the resolved row (``_rows``), because the resolver
does not know it. Works in an agent shell.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import click

from carter import ui
from carter.access import CAPABILITIES, ENFORCED, FLOOR, NEVER, Access
from carter.cliguard import verbose_option

_OPT_OUT = "opt-out"  # the source of `opencode_config` when config.toml opens this workspace
_VALUE_WIDTH = len("allowed")

_EPILOG = """\
Levels: strict (the default), guarded and relaxed. Set the level, and any row,
in ~/.carter/config.toml, which only you edit:

\b
  [access]
  level = "guarded"
  pr_write = "ask"

Each id in brackets is a key of [access]. Values: allowed, ask, denied. A row
cannot go past its ceiling: destructive and infra_apply stop at ask,
opencode_config stays denied. Rows marked never are the floor: no level opens
them. A workspace can only tighten: access: in carter.yaml takes the same keys.

Sources: preset (the level), override (your key), workspace (carter.yaml),
opt-out (allow_project_opencode_edit in config.toml).

A line like "! g2 off: push, gh_api" names a consent group that is not
installed; the rows it lists are not denied: run `carter guard install`.
-v shows what enforces each row and how strongly.

Without [access] the level is strict, and `carter update` says so. That notice
repeats on every update while ~/.carter/guard-state.json is missing.

Network and package installs are not limited until a sandbox exists.\
"""


def _header(access: Access) -> tuple[str, str]:
    """The title and its dim note: the level and where it comes from."""
    if access.level_source == "fallback":
        where = "config invalid"
    elif access.effective_level != access.level:
        where = f"carter.yaml tightens {access.level}"
    elif access.level_source == "default":
        where = "default"
    else:
        where = "~/.carter/config.toml"
    return f"Access level: {access.effective_level}", f"({where})"


def _rows(access: Access, *, opt_out: bool) -> list[ui.Row]:
    name_w = max(len(c.label) for c in CAPABILITIES)
    name_w = max(name_w, *(len(label) for _id, label in FLOOR))
    id_w = max(len(c.id) for c in CAPABILITIES)
    id_w = max(id_w, *(len(floor_id) for floor_id, _label in FLOOR)) + 2  # the brackets
    show_layer = ui.verbose()

    def row(label: str, ident: str, note: str) -> ui.Row:
        enforced = ""
        if show_layer:
            layer, strength = ENFORCED[ident]
            enforced = f"enforced by {layer}: {strength}"
        # rows() pads the label column itself: a stacked row must not end in spaces
        text = f"{label:<{name_w}}  {f'[{ident}]':<{id_w}}".rstrip()
        return ui.Row(text, None, note, more=enforced)

    rows = []
    for cap in CAPABILITIES:
        value, source = access.values[cap.id], access.sources[cap.id]
        if cap.id == "opencode_config" and opt_out:
            value, source = "allowed", _OPT_OUT  # the one view-side override
        rows.append(row(cap.label, cap.id, f"{value:<{_VALUE_WIDTH}}  {source}"))
    rows += [row(label, floor_id, NEVER) for floor_id, label in FLOOR]
    return rows


def show(access: Access, *, opt_out: bool, lines: Sequence[str] = ()) -> None:
    """Print the view: the header, one ``!`` line per fact, the rows, the pointer to ``--help``.

    ``lines`` are the extra ``!`` facts: today the missing consent groups. (``access.warnings``
    holds the token-scope facts; nothing passes them in yet.) The resolver's own notes (invalid
    config, a workspace that cannot loosen) come with ``access``."""
    ui.header(*_header(access))
    for line in (*access.notes, *lines):
        ui.warn(line.removeprefix("! "))
    ui.rows(_rows(access, opt_out=opt_out))
    ui.info("see: carter access --help")


@click.command("access", epilog=_EPILOG)
@verbose_option
def access_cmd() -> None:
    """Show what agents may do here."""
    import yaml

    from carter import accessload
    from carter.access import missing_group_lines, resolve_config
    from carter.config import ConfigError, load_config, with_user_access
    from carter.identity.workspace import workspace_key

    root = Path(workspace_key())
    path = root / ".carter" / "carter.yaml"
    try:
        config = load_config(path) if path.is_file() else {}
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc
    except yaml.YAMLError as exc:  # a syntax error is not a ConfigError
        raise click.ClickException(f"Cannot parse {path}: {str(exc).splitlines()[0]}") from exc

    resolved = resolve_config(with_user_access(config, accessload.load_user_access()))
    accepted = accessload.accepted_groups()
    show(
        resolved,
        opt_out=accessload.project_config_open(root, accepted),
        lines=missing_group_lines(accepted),
    )
