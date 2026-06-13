---
id: RFC-0001
status: accepted
revision: 2
created: 2026-06-10
decided: 2026-06-10
author: mauriciomem
adr: ADR-0004
plan: null
supersedes: []
tags: [rfc, process]
---

# RFC-0001: A lightweight RFC system for Carter

**Status:** Accepted
**Revision:** 2
**Author:** mauriciomem

## Summary

Add a Request-for-Comments process so designs are proposed and contrasted by
multiple expert agents *before* a plan or code exists. RFCs borrow the ADR regime
(main repo, frontmatter status, freeze-on-decide) but are stored as **directories**
so each reviewing agent contributes a first-class, attributable review.

This RFC is the dogfood of its own proposal — it is written in the structure it
describes and recorded as the durable decision in [ADR-0004](../../adr/0004-rfc-system.md).

## Problem

Carter records decisions *after the fact* (ADRs) and executes work (plans), but
has no **pre-decision** step where a design is explored and multiple experts weigh
in. The quality gate already runs multi-agent review — but only on *code*,
post-implementation, when changing course is expensive. There was no equivalent
for *designs*, where review is cheapest.

## Proposal

A `carter-rfc` skill and a `docs/rfcs/` home:

- Each RFC is a directory `docs/rfcs/NNNN-name/` with a `README.md` proposal and
  one `review-{agent}.md` per reviewing agent. The directory never moves; status
  lives in frontmatter (no status folders).
- Lifecycle `draft → review → accepted/rejected`, plus `withdrawn`. An accepted
  RFC yields an **ADR** (durable decision) and then a **plan** (execution),
  cross-linked by frontmatter ids.
- **Any relevant subagent reviews from its expertise** (domain-triggered):
  architect always; engineer/devops/pm/narrator by domain; maestro and learner
  never. Reviews are **advisory** — the maestro synthesizes, the user decides.
- **Iterative re-review (lightweight):** bump `revision: N` on a material change;
  reviewers append newest-first `## Round N — reviewed revision M` sections. A
  review is current iff its latest reviewed revision equals the RFC's `revision`;
  missing markers default to stale. Git is the authoritative history.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Directory-per-RFC, frontmatter status (chosen)** | first-class per-agent reviews; no folder ceremony | slightly heavier than a flat file |
| Bare single file + inline reviews | simplest | loses attribution and independent re-review |
| yui-soul 4 status folders + dir moves | full lifecycle | over-engineered for one user; move ceremony |
| Fold into `carter-adr` | one skill | conflates propose (explore) with record (decide) |

## Trade-offs / Impact

- New `carter-rfc` skill + a `docs/rfcs/` index to maintain.
- Additive, backward-compatible `rfc:` field on ADR and plan frontmatter.
- **Skill-governed, not Python-validated** — an RFC with a malformed header isn't
  caught by `carter check` (RFCs live in the main repo, like ADRs). The
  review-revision discipline relies on reviewer diligence, mitigated by template
  forcing + fail-safe-default-to-stale + the maestro synthesis gate + git.

## Open questions

- *(resolved in review)* Multi-crew review vs. ceremony — keep the experts, drop
  the status folders (revision 2).
- Whether the maestro should *auto-trigger* domain reviewers or the architect
  invokes them — deferred to the skill's operation; the synthesis gate is required
  either way.

## Decision

**Accepted.** Recorded as [ADR-0004](../../adr/0004-rfc-system.md) (D1–D8), grounded
in the Rust RFC and Python PEP processes (git-as-history; newest-first change log;
pre-FCP sign-off as the synthesis gate). The `carter-rfc` skill, `docs/rfcs/`, and
the `rfc:` schema links implement it.
