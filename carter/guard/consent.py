"""Consent groups: who decided what, and which statements follow (RFC-0007 App C.6.2).

Pure decisions, no I/O and no prompting: the CLI passes ``ask`` (a ``click.confirm``) and
saves the result. Rules, from the plan-003 freeze (F3):

- A group is **live** (has content in this version) or **reserved** (``alias``). A reserved
  group is never prompted and never recorded, even with ``--only``: a consent given for
  nothing must not later count as consent for new content.
- A live group can be **unavailable on this machine** (``hooks`` on git < 2.54, ``repo_hooks``
  on git >= 2.54: the other one does the job). The caller says so with ``unavailable``; it is
  treated like a reserved group (no prompt, nothing recorded), with its own reason as notice.
- No TTY and no ``--yes``: nothing is decided and nothing is written (``skipped``).
- ``--yes`` accepts every live group in scope; a TTY asks per group with its one-line effect.
- A recorded decision stands unless the group is named in ``--only``, which asks again.
- **Revisions (D65, freeze G11).** A group whose content grew (``g2`` rev 2: the plugin) is
  *stale* when accepted at a lower revision. A stale group is upgraded only by a TTY "yes" (the
  prompt shows the group's ``explain`` text) or by ``--yes --only <group>``. A bare ``--yes``,
  ``carter update`` and every non-TTY run leave it alone and print a notice. A TTY "no" keeps the
  old consent (its denies stay) and records the refusal in ``consent_offers`` so nothing asks
  again until ``--only`` names the group. A fresh install (no record) follows the normal flow.
- A group that is not recorded yet gets no statements: a new group needs its own consent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from carter.guard.state import GuardState
from carter.identity.policyset import ConsentGroup, Statement, consent_groups, policy_statements

CONFIG_EDIT = "config-edit"
PLUGIN = "plugin"  # a component, not a group: accepted only by `guard remove --only`
PENDING_NOTICE = (
    "plugin and isolation need your confirmation (`{group}` revision 2): run "
    "`carter guard install` in your terminal, or `carter guard install --yes --only {group}`"
)


def group_names() -> tuple[str, ...]:
    return tuple(g.id for g in consent_groups())


def parse_only(csv: str | None, *, allow_plugin: bool = False) -> list[str] | None:
    """``--only a,b`` → ``["a", "b"]``; ``None`` when not given. Unknown names raise
    ``ValueError`` listing the valid ones. ``plugin`` is a component of ``g2``: ``remove`` takes
    it, ``install`` points at ``--only g2`` (G15)."""
    if csv is None:
        return None
    names = [n.strip() for n in csv.split(",") if n.strip()]
    if PLUGIN in names and not allow_plugin:
        raise ValueError(
            "`plugin` is not a group for install: use `--only g2` to confirm the plugin"
        )
    unknown = [n for n in names if n not in group_names() and not (allow_plugin and n == PLUGIN)]
    if unknown or not names:
        extra = f", {PLUGIN}" if allow_plugin else ""
        raise ValueError(
            f"unknown group(s): {', '.join(unknown) or '(none given)'}; "
            f"valid groups: {', '.join(group_names())}{extra}"
        )
    return list(dict.fromkeys(names))


@dataclass
class ConsentPlan:
    accepted: list[str] = field(default_factory=list)  # decided or recorded as accepted
    declined: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)  # decided in this run (to be recorded)
    reserved: list[str] = field(default_factory=list)  # named by --only, nothing to install
    unavailable: dict[str, str] = field(default_factory=dict)  # group -> why not on this machine
    pending: list[str] = field(default_factory=list)  # stale groups left alone (needs a TTY yes)
    refused_offers: list[str] = field(default_factory=list)  # stale groups the human said no to
    skipped: bool = False  # no TTY and no --yes: nothing decided, nothing to write

    def notices(self) -> list[str]:
        out = [f"nothing to install for `{g}` in this version" for g in self.reserved]
        out += [f"`{g}`: {why}" for g, why in self.unavailable.items()]
        out += [PENDING_NOTICE.format(group=g) for g in self.pending]
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
    unavailable: Mapping[str, str] | None = None,
) -> ConsentPlan:
    """Decide the live groups in scope. Does not touch ``state``; see ``record``."""
    plan = ConsentPlan()
    groups = {g.id: g for g in consent_groups()}
    scope = list(only) if only is not None else [g.id for g in groups.values() if g.live]
    plan.reserved = [g for g in scope if only is not None and not groups[g].live]
    live = [g for g in scope if groups[g].live]
    plan.unavailable = {g: why for g, why in (unavailable or {}).items() if g in live}
    live = [g for g in live if g not in plan.unavailable]
    if not assume_yes and not interactive:
        plan.skipped = True
        return plan
    for name in live:
        rec = state.consents.get(name, {})
        prior = rec.get("decision")
        explicit = only is not None and name in only
        stale = prior == "accepted" and int(rec.get("rev", 1)) < groups[name].rev
        if stale and not explicit:
            declined = state.offer(name) or {}
            if declined.get("rev", 0) >= groups[name].rev:
                continue  # said no already: no nagging; INFO in check --host
            if assume_yes or not interactive:
                plan.pending.append(name)
                continue
            if ask is None:
                raise ValueError("an interactive decision needs an `ask` callable")
            (plan.asked if ask(groups[name]) else plan.refused_offers).append(name)
            if name in plan.asked:
                plan.accepted.append(name)
            continue
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
    revs = {g.id: g.rev for g in consent_groups()}
    for name in plan.asked:
        accepted = name in plan.accepted
        state.consent(name, "accepted" if accepted else "declined", day, revs[name])
        state.clear_offer(name)
    for name in plan.refused_offers:
        state.record_offer(name, revs[name], "declined", day)


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


def reconsent_pending(state: GuardState) -> list[str]:
    """Groups accepted at an older revision than this version offers (and not refused)."""
    revs = {g.id: g.rev for g in consent_groups() if g.live}
    return [
        g
        for g, rev in revs.items()
        if state.consents.get(g, {}).get("decision") == "accepted"
        and int(state.consents[g].get("rev", 1)) < rev
    ]


def plugin_wanted(state: GuardState) -> bool:
    """The plugin, ``isolation.json`` and the ``run/`` files belong to ``g2`` at revision 2."""
    rec = state.consents.get("g2", {})
    needed = next(g.rev for g in consent_groups() if g.id == "g2")
    return rec.get("decision") == "accepted" and int(rec.get("rev", 1)) >= needed
