"""Identity error registry: code, where, message, remediation (RFC-0007 Appendix B §2).

The one place ``E-*`` codes and their wording live; the data is ``errors.json`` (strict
JSON, read through ``importlib.resources`` like ``g2_rules.json``). The CLI raises from it
and the carter-ops skill embeds ``render_error_table()``; a parity test fails on drift.

``slice`` is the first slice that can raise a code. Slice 1 raises ``E-CONFIG`` and
``E-ROLE-B-TIER`` and carries the text of ``E-TIER-REQUIRED`` (enforced by 2a/2b) and
``E-COMMIT-T1`` (``carter commit``, 2b). Every other code is registered with its Appendix B
wording and raised by its own slice. Messages hold placeholders such as ``<t>``, never
values read from the environment, a config or a key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

SLICES = ("1", "1G", "2a", "2b", "2c", "B", "CI-E")
CURRENT_SLICE = "1"
ERRORS_BEGIN = "<!-- errors:begin -->"
ERRORS_END = "<!-- errors:end -->"

E_CONFIG = "E-CONFIG"
E_ROLE_B_TIER = "E-ROLE-B-TIER"
E_TIER_REQUIRED = "E-TIER-REQUIRED"
E_COMMIT_T1 = "E-COMMIT-T1"
# Slice 1G (plan 003). The last two are not in Appendix B; the architect added them (F10).
E_POLICIES_MISSING = "E-POLICIES-MISSING"
E_HUMAN_TERMINAL = "E-HUMAN-TERMINAL"
E_STATE_INVALID = "E-STATE-INVALID"


@dataclass(frozen=True)
class ErrorEntry:
    code: str
    slice: str
    where: str
    message: str
    remediation: str = ""


@cache
def registry() -> dict[str, ErrorEntry]:
    """Every registered code, in Appendix B order."""
    text = resources.files("carter.identity").joinpath("errors.json").read_text("utf-8")
    return {row["code"]: ErrorEntry(**row) for row in json.loads(text)["errors"]}


MSG_CONFIG = registry()[E_CONFIG].message
MSG_ROLE_B_TIER = registry()[E_ROLE_B_TIER].message


class IdentityError(Exception):
    """An identity failure with a stable ``code``.

    ``str(error)`` is the registry message. ``detail`` is a short technical hint (a key
    name, a TOML position); it never contains values read from the config, so a secret
    cannot leak through an error.
    """

    def __init__(self, code: str, message: str | None = None, detail: str = "") -> None:
        super().__init__(message if message is not None else registry()[code].message)
        self.code = code
        self.detail = detail


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_error_table(current: str = CURRENT_SLICE) -> str:
    """The marked Markdown table of the codes slice ``current`` raises or carries.

    ``blocks.py`` keeps the carter-ops skill's copy equal to this rendering."""
    lines = [ERRORS_BEGIN, "| Code | Where | Message | What to do |", "|---|---|---|---|"]
    for entry in registry().values():
        if SLICES.index(entry.slice) <= SLICES.index(current):
            lines.append(
                f"| `{entry.code}` | {_cell(entry.where)} | {_cell(entry.message)} "
                f"| {_cell(entry.remediation) or '—'} |"
            )
    lines.append(ERRORS_END)
    return "\n".join(lines) + "\n"
