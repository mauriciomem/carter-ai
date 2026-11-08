"""Identity error registry: code, where, message, remediation (RFC-0007 Appendix B §2).

The one place ``E-*`` codes and their wording live; the data is ``errors.json`` (strict
JSON, read through ``importlib.resources`` like ``g2_rules.json``). The CLI raises from it
and the carter-ops skill embeds ``render_error_table()``; a parity test fails on drift.

``slice`` is the first slice that can raise a code. Slice 1 raises ``E-CONFIG`` and
``E-ROLE-B-TIER`` and carries the text of ``E-TIER-REQUIRED`` (enforced by 2a/2b) and
``E-COMMIT-T1`` (``carter commit``, 2b); slice 1G raises the policy, handoff, secret-scan,
A+ and human-terminal codes. Every other code is registered with its Appendix B wording and
raised by its own slice. ``render_error_table()`` lists the codes up to ``CURRENT_SLICE``.
Messages hold placeholders such as ``<t>``, never values read from the environment, a config
or a key.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib import resources

from carter.identity.rules import CURRENT_SLICE, SLICES  # one constant for the whole package

ERRORS_BEGIN = "<!-- errors:begin -->"
ERRORS_END = "<!-- errors:end -->"

E_CONFIG = "E-CONFIG"
E_ROLE_B_TIER = "E-ROLE-B-TIER"
E_CI_REVIEW = "E-CI-REVIEW"  # slice CI-E (plan 008): context E, review only, no commits
E_TIER_REQUIRED = "E-TIER-REQUIRED"
E_COMMIT_T1 = "E-COMMIT-T1"
# Slice 1G (plan 003). The last two are not in Appendix B; the architect added them (F10).
E_POLICIES_MISSING = "E-POLICIES-MISSING"
E_HUMAN_TERMINAL = "E-HUMAN-TERMINAL"
E_STATE_INVALID = "E-STATE-INVALID"
E_APLUS_ARGS = "E-APLUS-ARGS"
E_PAT_TYPE = "E-PAT-TYPE"
E_PAT_PERM = "E-PAT-PERM"
E_GH_READONLY = "E-GH-READONLY"
E_HANDOFF = "E-HANDOFF"
E_SECRET_SCAN = "E-SECRET-SCAN"
E_B_REPOCFG = "E-B-REPOCFG"
E_B_UNSIGNED = "E-B-UNSIGNED"
# Slice 2a (plan 004). The last two are not in Appendix B (G14).
E_ISOLATION_MISSING = "E-ISOLATION-MISSING"
E_FALSE_MISSING = "E-FALSE-MISSING"
E_PROBE_SCOPE = "E-PROBE-SCOPE"
E_PUSH_GUARD = "E-PUSH-GUARD"
E_GIT_OLD = "E-GIT-OLD"
E_OPENCODE_VERSION = "E-OPENCODE-VERSION"
# Slice 2b (plan 005); the other 2b codes get a constant when the step that raises them lands.
E_SHIM_REFUSED = "E-SHIM-REFUSED"
E_SSH_OLD = "E-SSH-OLD"
E_UNLOCK_TTY = "E-UNLOCK-TTY"
E_UNLOCK_OPENCODE = "E-UNLOCK-OPENCODE"
E_UNLOCK_PATH = "E-UNLOCK-PATH"
E_IDENTITY_CHECK = "E-IDENTITY-CHECK"
E_GITHUB_UNREACHABLE = "E-GITHUB-UNREACHABLE"
E_GUARD_NOIDENT = "E-GUARD-NOIDENT"
E_GUARD_COMMITTER = "E-GUARD-COMMITTER"
E_GUARD_SIGNCFG = "E-GUARD-SIGNCFG"
E_GUARD_TRAILER = "E-GUARD-TRAILER"
E_GUARD_T01SIGN = "E-GUARD-T01SIGN"
E_GUARD_UNSIGNED = "E-GUARD-UNSIGNED"
E_SIGN_HUMAN_FALLBACK = "E-SIGN-HUMAN-FALLBACK"
E_SIGN_AGENT_REFUSE = "E-SIGN-AGENT-REFUSE"
E_SIGN_LOCKED = "E-SIGN-LOCKED"
# Slice 2c (plan 006)
E_HUMAN_IDENTITY = "E-HUMAN-IDENTITY"
# Slice B (plan 007). E-B-HEADLESS is raised by OpenCode (auto-reject), not by Carter.
E_B_CALLER = "E-B-CALLER"
E_B_DWELL = "E-B-DWELL"
E_B_TIMEOUT = "E-B-TIMEOUT"
E_B_HEADLESS = "E-B-HEADLESS"
E_B_POLLUTED = "E-B-POLLUTED"
E_B_NOAGENT = "E-B-NOAGENT"
E_B_HTTPS = "E-B-HTTPS"
E_B_MOVED = "E-B-MOVED"
E_B_DEFAULT = "E-B-DEFAULT"
E_B_ARGS = "E-B-ARGS"
E_B_REJECTED = "E-B-REJECTED"


@dataclass(frozen=True)
class ErrorEntry:
    code: str
    slice: str
    where: str
    message: str
    remediation: str = ""
    fix: str = ""  # the one line a human command prints after the cause (D68 a)
    observed: tuple[str, ...] = ()  # raw strings seen in the wild (data only, spike transcripts)


@cache
def registry() -> dict[str, ErrorEntry]:
    """Every registered code, in Appendix B order."""
    text = resources.files("carter.identity").joinpath("errors.json").read_text("utf-8")
    return {
        row["code"]: ErrorEntry(**{**row, "observed": tuple(row.get("observed", ()))})
        for row in json.loads(text)["errors"]
    }


MSG_CONFIG = registry()[E_CONFIG].message
MSG_ROLE_B_TIER = registry()[E_ROLE_B_TIER].message
MSG_CI_REVIEW = registry()[E_CI_REVIEW].message


class IdentityError(Exception):
    """An identity failure with a stable ``code``.

    ``str(error)`` is the registry message. ``detail`` is a short technical hint (a key
    name, a TOML position); it never contains values read from the config, so a secret
    cannot leak through an error.
    """

    def __init__(
        self, code: str, message: str | None = None, detail: str = "", fix: str = ""
    ) -> None:
        super().__init__(message if message is not None else registry()[code].message)
        self.code = code
        self.detail = detail
        self.fix = fix  # the raising site may know a better fix than the registry's one line


# 2b (plan 005 step 6 rule): the agent table lists what an agent can meet; these are shown to the
# human at a terminal and live in the docs and `carter` output instead.
HUMAN_FACING = frozenset(
    {
        "E-UNLOCK-TTY", "E-UNLOCK-OPENCODE", "E-UNLOCK-PATH", "E-UNLOCK-BADPASS",
        "E-SIGN-HUMAN-FALLBACK", "E-SSH-OLD", "E-IDENTITY-CHECK", "E-GITHUB-UNREACHABLE",
    }
)  # fmt: skip


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_error_table(current: str = CURRENT_SLICE) -> str:
    """The marked Markdown table of the codes slice ``current`` raises or carries.

    ``blocks.py`` keeps the carter-ops skill's copy equal to this rendering."""
    lines = [ERRORS_BEGIN, "| Code | Where | Message | What to do |", "|---|---|---|---|"]
    for entry in registry().values():
        if entry.code not in HUMAN_FACING and SLICES.index(entry.slice) <= SLICES.index(current):
            lines.append(
                f"| `{entry.code}` | {_cell(entry.where)} | {_cell(entry.message)} "
                f"| {_cell(entry.remediation) or '—'} |"
            )
    lines.append(ERRORS_END)
    return "\n".join(lines) + "\n"
