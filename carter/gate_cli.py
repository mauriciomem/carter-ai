"""``carter gate check``: the human/test wrapper over the same code as ``python -m carter.gate``.

Read-only, so it is allowed anywhere (agent shells included); it refuses nothing. Exit 0 = allow,
1 = deny (RFC-0007 App C.4.2, freeze G15).
"""

from __future__ import annotations

import json
import sys

import click

from carter.gate import MAX_BYTES, check


@click.group()
def gate() -> None:
    """Inspect the command gate."""


@gate.command("check")
@click.option("--json", "as_json", is_flag=True, help="Print the gate's JSON reply.")
@click.option("--cwd", default=None, help="Directory for relative paths.")
@click.option("--skip-groups", default="", help="Declined groups, comma-separated.")
@click.argument("command", required=False)
def check_cmd(as_json: bool, cwd: str | None, skip_groups: str, command: str | None) -> None:
    """Say whether a command would be refused, and by which rule."""
    text = command if command is not None else sys.stdin.read(MAX_BYTES + 1)
    decision = check(text, cwd, tuple(s for s in skip_groups.split(",") if s))
    if as_json:
        click.echo(
            json.dumps(
                {"decision": decision.decision, "rule": decision.rule, "message": decision.message}
            )
        )
    else:
        click.echo(decision.message or "allow")
    raise SystemExit(0 if decision.decision == "allow" else 1)
