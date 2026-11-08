"""G2's deny set as Carter-agent permission rules (D71).

Until D71 the 1G deny set (push, gh, sudo/docker, read and edit denies, the D52 opt-outs) went
into the top-level ``policies`` of the user's OpenCode config, where it bound **every** agent.
Now it is rendered into the ``permissions:`` front matter of Carter's own agents, global and
workspace installs alike, so other agents are untouched. This module turns the consented
statements into those rules; ``carter.config.permission_rules`` appends them last (OpenCode
permissions are last-match-wins, so a deny cannot be lifted by an earlier rule, and the gh
allows and D52 opt-outs, which come after the denies, lift only what they name).

Declined consent groups yield nothing. Read-only: this module never writes.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from carter.guard import consent, optout
from carter.guard.state import GuardState, load_or_empty_readonly
from carter.identity import ConfigError, load_identity
from carter.identity.policyset import Statement
from carter.install.paths import carter_config_path, guard_state_path

Rule = dict[str, str]


def to_rule(statement: Statement) -> Rule:
    """``shell:git push *`` → ``{action: shell, resource: "git push *", effect: ...}``."""
    action, _, resource = statement.resource.partition(":")
    return {"action": action, "resource": resource, "effect": statement.effect}


def rules_for(state: GuardState, *, home: str, optouts: Sequence[Statement] = ()) -> list[Rule]:
    """The rules for the groups ``state`` records as accepted: denies, gh allows, opt-outs."""
    return [to_rule(s) for s in consent.desired_statements(state, home=home, optouts=optouts)]


def current_rules(base_dir: Path | None = None, *, home: str | None = None) -> list[Rule]:
    """The rules this machine's guard state calls for (none when nothing is installed).

    The D52 opt-outs are read live from ``config.toml``: they exist only while ``config-edit``
    is accepted, and a broken file contributes none (the denies stay)."""
    read = load_or_empty_readonly(guard_state_path(base_dir))
    if read.status != "ok":
        return []
    state = read.state
    optouts: list[Statement] = []
    if consent.CONFIG_EDIT in consent.accepted_groups(state):
        try:
            cfg = load_identity(carter_config_path(base_dir))
        except ConfigError:
            cfg = None
        if cfg is not None:
            optouts = optout.active_optouts(cfg).statements()
    return rules_for(state, home=home or str(Path.home()), optouts=optouts)


def agent_file_state(base_dir: Path | None = None) -> tuple[list[str], list[str]]:
    """``(current, drifted)`` file names of the installed global Carter agents.

    A file is current when its ``permissions:`` equal what Carter renders for this machine's
    guard state (G2's rules included). A file that is not installed is in neither list."""
    from carter.install.components import _render_opencode_agents  # noqa: PLC0415
    from carter.install.paths import _opencode_base  # noqa: PLC0415
    from carter.plans import parse_frontmatter  # noqa: PLC0415

    current: list[str] = []
    drifted: list[str] = []
    for name, content in sorted(_render_opencode_agents(base_dir).items()):
        path = _opencode_base(base_dir) / "agents" / name
        if not path.is_file():
            continue
        want = parse_frontmatter(content) or {}
        have = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace")) or {}
        same = bool(want) and have.get("permissions") == want.get("permissions")
        (current if same else drifted).append(name)
    return current, drifted
