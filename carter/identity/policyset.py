"""The statements Carter writes into the OpenCode config, from ``g2_rules.json``.

RFC-0007 App C.1 (``policy_set``, ``gh_read_allowlist``) and C.6.3. The data file is the
only source: the policy writer, ``check --host`` and the parity tests all read it through
here. Stdlib-only, like the rest of ``carter.identity``.

Shapes (plan 003, step 6 F3-F6):

- ``policy_set`` entries are ``tool.use`` **denies** with a stable ``id`` and a consent
  ``group``; ``<home>`` in a resource is replaced at render time.
- The gh allows are *generated* from ``gh_read_allowlist`` (id ``allow-gh-<verb-slug>``),
  not repeated in ``policy_set``. They belong to ``g2`` and come last: denies, then allows
  (OpenCode policies are last-match-wins, so an allow only lifts an earlier deny).
- Per-agent ``carter_push``/``carter_pr`` denies are *not* policies (D46): see
  ``agent_permission_denies``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, replace
from functools import cache
from importlib import resources
from typing import Any

HOME_PLACEHOLDER = "<home>"
GH_GROUP = "g2"


@dataclass(frozen=True)
class Statement:
    id: str
    group: str
    action: str
    resource: str
    effect: str
    rfc: str


@dataclass(frozen=True)
class ConsentGroup:
    id: str
    live: bool
    effect: str
    rev: int = 1  # bumped when a group gains content that needs a fresh yes (D65)
    explain: tuple[str, ...] = ()  # printed before the question when this revision is offered
    optional: bool = False  # never accepted by a bare --yes, only by --only <id> or a TTY yes


@dataclass(frozen=True)
class GhVerb:
    verb: str
    pattern: str
    pending: str = ""

    @property
    def slug(self) -> str:
        return self.verb.replace(" ", "-")


@cache
def _data() -> dict[str, Any]:
    text = resources.files("carter.identity").joinpath("g2_rules.json").read_text("utf-8")
    return json.loads(text)


def consent_groups() -> tuple[ConsentGroup, ...]:
    """The seven consent groups of C.6.1, in order; ``live`` ones have content in 1G."""
    return tuple(
        ConsentGroup(
            g["id"],
            g["live"],
            g["effect"],
            g.get("rev", 1),
            tuple(g.get("explain", ())),
            g.get("optional", False),
        )  # fmt: skip
        for g in _data()["consent_groups"]
    )


def policy_set() -> tuple[Statement, ...]:
    """The data-file statements, unrendered (``<home>`` still in place)."""
    return tuple(Statement(**e) for e in _data()["policy_set"])


def gh_allowlist() -> tuple[GhVerb, ...]:
    return tuple(
        GhVerb(e["verb"], e["pattern"], e.get("pending", "")) for e in _data()["gh_read_allowlist"]
    )


def _check_home(home: str) -> str:
    if not home.startswith("/"):
        raise ValueError(f"home must be an absolute path, got {home!r}")
    if "*" in home or "?" in home:
        raise ValueError("home contains a glob character (* or ?); it would widen a deny")
    return home.rstrip("/") or "/"


def policy_statements(groups: Iterable[str] | None = None, *, home: str) -> tuple[Statement, ...]:
    """Rendered statements for ``groups`` (default: every live group), denies then gh allows.

    Raises ``ValueError`` for an unknown group or a ``home`` that is not absolute or holds
    a glob character. A reserved group (no content in this version) yields nothing."""
    known = {g.id for g in consent_groups()}
    chosen = list(dict.fromkeys(groups if groups is not None else _live_ids()))
    unknown = [g for g in chosen if g not in known]
    if unknown:
        raise ValueError(f"unknown consent group(s): {', '.join(unknown)}")
    root = _check_home(home)
    denies = tuple(
        replace(s, resource=s.resource.replace(HOME_PLACEHOLDER, root))
        for s in policy_set()
        if s.group in chosen
    )
    allows: tuple[Statement, ...] = ()
    if GH_GROUP in chosen:
        allows = tuple(
            Statement(
                f"allow-gh-{v.slug}",
                GH_GROUP,
                "tool.use",
                f"shell:{v.pattern}",
                "allow",
                "4.5 gh read allowlist",
            )  # fmt: skip
            for v in gh_allowlist()
        )
    return denies + allows


def _live_ids() -> list[str]:
    return [g.id for g in consent_groups() if g.live]


def render_policies(statements: Iterable[Statement]) -> list[dict[str, str]]:
    """The statements as OpenCode's ``policies`` entries (no ids)."""
    return [{"action": s.action, "resource": s.resource, "effect": s.effect} for s in statements]


def agent_permission_denies() -> tuple[str, ...]:
    """Tool names denied per agent (D46), not as global policies."""
    return tuple(_data()["agent_permission_denies"])


def agent_permission_exempt() -> tuple[str, ...]:
    """Roles that keep the tools in ``agent_permission_denies`` (devops, the only B caller)."""
    return tuple(_data()["agent_permission_exempt"])


def agent_mcp_denies() -> tuple[str, tuple[str, ...]]:
    """``(action pattern, roles)``: the GitHub MCP tools hidden from roles that do not need them."""
    block = _data()["agent_mcp_denies"]
    return block["action"], tuple(block["roles"])
