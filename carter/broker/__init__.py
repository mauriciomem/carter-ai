"""B, the approval-forced push and PR broker (RFC-0007 §4.5, App C.5; plan 007).

Two verbs only: ``push`` (a fast-forward of the pinned HEAD of the current non-default branch to
an SSH ``origin``) and ``pr`` (``gh pr create`` from the handoff file). Widening B needs a new ADR.
The OpenCode plugin tools ``carter_push`` / ``carter_pr`` are thin wrappers that run
``python -I -m carter.broker_cli`` twice per use: ``--plan`` (no network, no credentials), then,
after the human's approval, ``--exec``.

Everything a refusal says goes through ``refusal()``: the registry message with its placeholders
filled and a technical ``detail`` that names keys, scopes and shas, never values.
"""

from __future__ import annotations

from carter.identity.errors import IdentityError, registry

DEVOPS_AGENT = "carter-devops"  # the only caller (D46, freeze B10); a subagent reports `general`
VERBS = ("push", "pr")


def refusal(code: str, detail: str = "", **fields: str) -> IdentityError:
    """``IdentityError`` with the registry text; ``fields`` fill the `<name>` placeholders."""
    message = registry()[code].message
    for name, value in fields.items():
        message = message.replace(f"`<{name}>`", f"`{value}`").replace(f"<{name}>", value)
    return IdentityError(code, message, detail=detail)
