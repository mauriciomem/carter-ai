"""Consent groups: who decided what, and which statements follow (RFC-0007 App C.6.2).

Pure decisions, no I/O and no prompting: the CLI passes ``ask`` (a ``click.confirm``) and
saves the result. Rules, from the plan-003 freeze (F3):

- A group is **live** (has content in this version) or **reserved** (``hooks``,
  ``alias``, ``repo_hooks``). A reserved group is never prompted and never recorded,
  even with ``--only``: a consent given for nothing must not later count as consent for
  new content.
- No TTY and no ``--yes``: nothing is decided and nothing is written (``skipped``).
- ``--yes`` accepts every live group in scope; a TTY asks per group with its one-line effect.
- A recorded decision stands unless the group is named in ``--only``, which asks again.
- A group that is not recorded yet gets no statements: a new group needs its own consent.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from carter.guard.state import GuardState
from carter.identity.policyset import ConsentGroup, Statement, consent_groups, policy_statements

CONFIG_EDIT = "config-edit"


def group_names() -> tuple[str, ...]:
    return tuple(g.id for g in consent_groups())


def parse_only(csv: str | None) -> list[str] | None:
    """``--only a,b`` → ``["a", "b"]``; ``None`` when not given. Unknown names raise
    ``ValueError`` listing the valid ones."""
    if csv is None:
        return None
    names = [n.strip() for n in csv.split(",") if n.strip()]
    unknown = [n for n in names if n not in group_names()]
    if unknown or not names:
        raise ValueError(
            f"unknown group(s): {', '.join(unknown) or '(none given)'}; "
            f"valid groups: {', '.join(group_names())}"
        )
    return list(dict.fromkeys(names))


@dataclass
class ConsentPlan:
    accepted: list[str] = field(default_factory=list)  # decided or recorded as accepted
    declined: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)  # decided in this run (to be recorded)
    reserved: list[str] = field(default_factory=list)  # named by --only, nothing to install
    skipped: bool = False  # no TTY and no --yes: nothing decided, nothing to write

    def notices(self) -> list[str]:
        out = [f"nothing to install for `{g}` in this version" for g in self.reserved]
        if self.skipped:
            out.append(
                "no terminal and no --yes: policies, per-agent permissions and Carter's git "
                "config were NOT installed; run `carter guard install` in your own terminal"
            )
        return out


def resolve_consents(
    state: GuardState,
    *,
    only: Sequence[str] | None,
    assume_yes: bool,
    interactive: bool,
    ask: Callable[[ConsentGroup], bool] | None = None,
) -> ConsentPlan:
    """Decide the live groups in scope. Does not touch ``state``; see ``record``."""
    plan = ConsentPlan()
    groups = {g.id: g for g in consent_groups()}
    scope = list(only) if only is not None else [g.id for g in groups.values() if g.live]
    plan.reserved = [g for g in scope if only is not None and not groups[g].live]
    live = [g for g in scope if groups[g].live]
    if not assume_yes and not interactive:
        plan.skipped = True
        return plan
    for name in live:
        prior = state.consents.get(name, {}).get("decision")
        explicit = only is not None
        if prior and not explicit:
            decision = prior
        elif assume_yes:
            decision = "accepted"
        else:
            if ask is None:
                raise ValueError("an interactive decision needs an `ask` callable")
            decision = "accepted" if ask(groups[name]) else "declined"
        if decision != prior or explicit:
            plan.asked.append(name)
        (plan.accepted if decision == "accepted" else plan.declined).append(name)
    return plan


def record(state: GuardState, plan: ConsentPlan, *, today: str | None = None) -> None:
    """Write the decisions made in this run into ``state`` (never reserved groups)."""
    day = today or datetime.now(UTC).date().isoformat()
    for name in plan.asked:
        state.consent(name, "accepted" if name in plan.accepted else "declined", day)


def accepted_groups(state: GuardState) -> list[str]:
    """Live groups the state records as accepted, in canonical order."""
    live = {g.id for g in consent_groups() if g.live}
    return [
        g
        for g in group_names()
        if g in live and state.consents.get(g, {}).get("decision") == "accepted"
    ]


def declined_groups(state: GuardState) -> list[str]:
    return [g for g in group_names() if state.consents.get(g, {}).get("decision") == "declined"]


def desired_statements(
    state: GuardState, *, home: str, optouts: Sequence[Statement] = ()
) -> list[Statement]:
    """Statements for the accepted groups: denies, gh allows, then D52 opt-out allows
    (only while ``config-edit`` is accepted, since they lift that group's denies)."""
    accepted = accepted_groups(state)
    out = list(policy_statements(accepted, home=home))
    if CONFIG_EDIT in accepted:
        out += list(optouts)
    return out
