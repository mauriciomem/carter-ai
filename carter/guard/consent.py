"""Consent groups: who decided what, and which statements follow.

Pure decisions, no I/O and no prompting: the CLI passes ``ask`` (a ``click.confirm``) and
saves the result. Rules:

- A group can be **unavailable on this machine** (``hooks`` on git < 2.54, ``repo_hooks`` on
  git >= 2.54: the other one does the job). The caller says so with ``unavailable``; it is never
  prompted or recorded, and its reason is shown as a notice.
- No TTY and no ``--yes``: nothing is decided and nothing is written (``skipped``).
- ``--yes`` accepts every group in scope; a TTY gets one question for all of them (``to_offer``
  says which), and its yes is the consent for each group, revisions included.
- A recorded decision stands unless the group is named in ``--only``, which asks again.
- **Revisions.** A group whose content grew (``g2`` rev 2: the plugin) is *stale* when accepted
  at a lower revision. A stale group is upgraded only by a TTY "yes" (the prompt shows the
  group's ``explain`` text) or by ``--yes --only <group>``. A bare ``--yes``, ``carter update``
  and every non-TTY run leave it alone and print a notice. A TTY "no" keeps the old consent (its
  denies stay) and records the refusal in ``consent_offers`` so nothing asks again until
  ``--only`` names the group. A fresh install (no record) follows the normal flow.
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
BROKER = (
    "broker"  # a component of g2 (revision 3): `guard remove --only broker` turns the push tool off
)
PLUGIN_REV = 2  # the plugin and isolation.json belong to g2 from this revision on
BROKER_REV = 3  # the push tool (carter_push) needs g2 at this revision
PENDING_TEXT = {
    "g2": "the plugin and isolation, and the push tool (carter_push) for devops, "
    "need your confirmation",
    "hooks": "the commit checks need your confirmation",
    "repo_hooks": "the commit hooks need your confirmation",
}
PENDING_NOTICE = (
    "{what}: run `carter guard install` in your terminal, "
    "or `carter guard install --yes --only {group}`"
)
OPTIONAL_NOTICE = (
    "`{group}` is optional and was not installed: `carter guard install --only {group}` "
    "(or answer yes in a terminal)"
)


def group_names() -> tuple[str, ...]:
    return tuple(g.id for g in consent_groups())


def parse_only(csv: str | None, *, allow_plugin: bool = False) -> list[str] | None:
    """``--only a,b`` → ``["a", "b"]``; ``None`` when not given. Unknown names raise
    ``ValueError`` listing the valid ones. ``plugin`` and ``broker`` are components of ``g2``:
    ``remove`` takes them, ``install`` points at ``--only g2``."""
    if csv is None:
        return None
    names = [n.strip() for n in csv.split(",") if n.strip()]
    components = (PLUGIN, BROKER)
    for component in components:
        if component in names and not allow_plugin:
            raise ValueError(
                f"`{component}` is not a group for install: use `--only g2` to confirm it"
            )
    unknown = [
        n for n in names if n not in group_names() and not (allow_plugin and n in components)
    ]
    if unknown or not names:
        extra = f", {PLUGIN}, {BROKER}" if allow_plugin else ""
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
    unavailable: dict[str, str] = field(default_factory=dict)  # group -> why not on this machine
    pending: list[str] = field(default_factory=list)  # stale groups left alone (needs a TTY yes)
    optional_skipped: list[str] = field(default_factory=list)  # optional groups a bare --yes skips
    refused_offers: list[str] = field(default_factory=list)  # stale groups the human said no to
    skipped: bool = False  # no TTY and no --yes: nothing decided, nothing to write

    def notices(self) -> list[str]:
        out = [f"`{g}`: {why}" for g, why in self.unavailable.items()]
        out += [
            PENDING_NOTICE.format(
                what=PENDING_TEXT.get(g, f"`{g}` has new content that needs your confirmation"),
                group=g,
            )
            for g in self.pending
        ]
        out += [OPTIONAL_NOTICE.format(group=g) for g in self.optional_skipped]
        if self.skipped:
            out.append(
                "no terminal and no --yes: the agent rules, per-agent permissions and Carter's git "
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
    """Decide the groups in scope. Does not touch ``state``; see ``record``."""
    plan = ConsentPlan()
    groups = {g.id: g for g in consent_groups()}
    scope = list(only) if only is not None else list(groups)
    plan.unavailable = {g: why for g, why in (unavailable or {}).items() if g in scope}
    scope = [g for g in scope if g not in plan.unavailable]
    if not assume_yes and not interactive:
        plan.skipped = True
        return plan
    for name in scope:
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
        elif assume_yes and groups[name].optional and not explicit:
            plan.optional_skipped.append(name)  # optional: a bare --yes never says yes for you
            continue
        elif assume_yes:
            decision = "accepted"
        elif ask is None and groups[name].optional and not explicit:
            plan.optional_skipped.append(name)  # the one question never covers an optional group
            continue
        else:
            if ask is None:
                raise ValueError("an interactive decision needs an `ask` callable")
            decision = "accepted" if ask(groups[name]) else "declined"
        if decision != prior or explicit:
            plan.asked.append(name)
        (plan.accepted if decision == "accepted" else plan.declined).append(name)
    return plan


COMMIT_GUARDS = ("hooks", "repo_hooks")  # the groups that install the commit hooks


def declined_commit_guards(
    state: GuardState, unavailable: Mapping[str, str] | None = None
) -> list[str]:
    """The declined commit-hook groups, while no commit-hook group is accepted.

    With the LLM signing key (T2) configured, these are what a RED "no commit hooks" needs;
    a group that cannot work on this git (``unavailable``) is not counted.
    """
    if set(COMMIT_GUARDS) & set(accepted_groups(state)):
        return []
    return [
        g
        for g in COMMIT_GUARDS
        if state.consents.get(g, {}).get("decision") == "declined" and g not in (unavailable or {})
    ]


def to_offer(
    state: GuardState,
    *,
    only: Sequence[str] | None,
    unavailable: Mapping[str, str] | None = None,
    reoffer: Sequence[str] = (),
) -> list[str]:
    """The groups the single install question covers: the ones in scope that are undecided,
    named in ``--only``, or accepted at an older revision and not refused. A group declined
    earlier stays declined unless the caller says the configuration needs it (``reoffer``),
    and an optional group needs ``--only``."""
    groups = {g.id: g for g in consent_groups()}
    scope = list(only) if only is not None else list(groups)
    out = []
    for name in scope:
        group = groups[name]
        if name in (unavailable or {}):
            continue
        rec = state.consents.get(name, {})
        prior = rec.get("decision")
        stale = prior == "accepted" and int(rec.get("rev", 1)) < group.rev
        refused = (state.offer(name) or {}).get("rev", 0) >= group.rev
        explicit = only is not None and name in only
        needed = name in reoffer and prior == "declined"
        if explicit or (prior is None and not group.optional) or (stale and not refused) or needed:
            out.append(name)
    return out


def record(state: GuardState, plan: ConsentPlan, *, today: str | None = None) -> None:
    """Write the decisions made in this run into ``state``."""
    day = today or datetime.now(UTC).date().isoformat()
    revs = {g.id: g.rev for g in consent_groups()}
    for name in plan.asked:
        accepted = name in plan.accepted
        state.consent(name, "accepted" if accepted else "declined", day, revs[name])
        state.clear_offer(name)
    for name in plan.refused_offers:
        state.record_offer(name, revs[name], "declined", day)


def accepted_groups(state: GuardState) -> list[str]:
    """Groups the state records as accepted, in canonical order."""
    return [g for g in group_names() if state.consents.get(g, {}).get("decision") == "accepted"]


def declined_groups(state: GuardState) -> list[str]:
    """Groups the human declined and that protect something (an optional group, such as the
    ``alias``, is a convenience: declining it leaves no residual)."""
    optional = {g.id for g in consent_groups() if g.optional}
    return [
        g
        for g in group_names()
        if g not in optional and state.consents.get(g, {}).get("decision") == "declined"
    ]


def desired_statements(
    state: GuardState, *, home: str, optouts: Sequence[Statement] = ()
) -> list[Statement]:
    """Statements for the accepted groups: denies, gh allows, then the opt-out allows
    (only while ``config-edit`` is accepted, since they lift that group's denies)."""
    accepted = accepted_groups(state)
    out = list(policy_statements(accepted, home=home))
    if CONFIG_EDIT in accepted:
        out += list(optouts)
    return out


def reconsent_pending(state: GuardState) -> list[str]:
    """Groups accepted at an older revision than this version offers (and not refused)."""
    revs = {g.id: g.rev for g in consent_groups()}
    return [
        g
        for g, rev in revs.items()
        if state.consents.get(g, {}).get("decision") == "accepted"
        and int(state.consents[g].get("rev", 1)) < rev
    ]


def _g2_at_least(state: GuardState, rev: int) -> bool:
    rec = state.consents.get("g2", {})
    return rec.get("decision") == "accepted" and int(rec.get("rev", 1)) >= rev


def plugin_wanted(state: GuardState) -> bool:
    """The plugin, ``isolation.json`` and the ``run/`` files belong to ``g2`` from revision 2."""
    return _g2_at_least(state, PLUGIN_REV)


def broker_wanted(state: GuardState) -> bool:
    """The push tool needs ``g2`` accepted at revision 3 (never moved by a bare ``--yes``)."""
    return _g2_at_least(state, BROKER_REV)
