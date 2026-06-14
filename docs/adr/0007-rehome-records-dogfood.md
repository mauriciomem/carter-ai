---
id: ADR-0007
status: accepted
created: 2026-06-14
decided: 2026-06-14
supersedes: ["ADR-0006§D1", "ADR-0006§D2"]
superseded_by: null
rfc: null
tags: [repo, docs, organization, adr, rfc, plans, dogfooding]
---

# ADR-0007: Re-home ADRs/RFCs to `docs/` for convention dogfood; plans to a private `.carter/`

**Status:** Accepted
**Date:** 2026-06-14
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** Partially supersedes [ADR-0006](0006-repo-records-relocation.md) (§D1 location, §D2 docs-only). [ADR-0003](0003-knowledge-adr-rfc-plan-storage.md) defines the product storage layout this restores dogfooding of.

---

## Context

[ADR-0006](0006-repo-records-relocation.md) moved carter-ai's own ADRs, RFCs, and
plans into a single `design/` folder so `docs/` could be product-documentation
only. That cleanly separated audiences, but it had a cost the maintainer chose to
revisit: carter-ai stopped being a **live example of the storage conventions the
tool ships**.

Two layers of "dogfooding" exist (established when ADR-0006 was discussed):

- **Discipline** — using the ADR/RFC/plan *formats* (frontmatter, review rounds,
  `must_haves`). This was never lost; it is format-, not location-, dependent.
- **Location** — the project's records living at the exact paths the
  `carter-adr` / `carter-rfc` / `carter-plan` skills tell *users* to use:
  `docs/adr/`, `docs/rfcs/`, `.carter/state/plans/`. ADR-0006 broke this.

The maintainer's goal: **restore location dogfooding where the convention says
"tracked" (ADRs/RFCs in `docs/`), and restore it as "private/untracked" where the
convention already says so (plans in `.carter/`)** — without tracking the latter in
the public repo.

A decisive fact about Carter's design ([ADR-0003](0003-knowledge-adr-rfc-plan-storage.md) §D5):
the tool **already** splits git regime by artifact. ADRs/RFCs are *shared,
reviewable* documents kept in the main repo; plans/sessions/knowledge are
*per-workspace execution state* kept in a nested, private `.carter/.git` (or
git-ignored). So "tracked ADRs, untracked plans" is not a compromise — it is the
shipped model.

## Decision

- **D1 — ADRs and RFCs return to `docs/`.** `design/adr/` → `docs/adr/`,
  `design/rfcs/` → `docs/rfcs/` (tracked, reviewable in PRs). This restores
  location dogfooding of the `carter-adr` / `carter-rfc` conventions. It reverses
  ADR-0006 §D2's "`docs/` holds product documentation only" — `docs/` again carries
  the project's design records alongside the product docs, which is acceptable
  because those records *are* the convention being demonstrated.
- **D2 — Plans live in a private, git-ignored `.carter/` workspace.** carter-ai
  gets a real `.carter/` (created via the tool's own `init_workspace`): a
  `carter.yaml`, `state/plans/{active,completed}/`, and a nested `.carter/.git`.
  `.carter/` is added to the main `.gitignore` (root-anchored), so plan history is
  versioned **privately** in the nested git and never enters the public repo —
  exactly Carter's designed private regime (ADR-0003 §D5).
- **D3 — Full `carter init` is deliberately NOT run.** carter-ai is the *tool
  source*, not a consumer workspace; `carter init` would scaffold consumer-facing
  `carter-*-local.md` agents into the source tree (the recursion that is the
  original reason carter-ai was never a workspace). Only `init_workspace` (the
  `.carter/` skeleton + nested git) is used. Consequence: `carter check` does not
  fully run here; plans are validated with `validate_plans_dir` (the same validator
  `carter check` calls internally).
- **D4 — The two completed plans stay tracked in `design/plans/`.** They are the
  public execution record of ADR-0003 (plan 001) and RFC-0002/ADR-0005 (plan 002).
  *New* plans dogfood the private `.carter/` path. `design/` therefore persists as a
  small tracked archive of historical plans.
- **D5 — Unchanged from ADR-0006:** scratch stays in the git-ignored `notes/`
  (ADR-0006 §D3); the shipped skills/templates still scaffold `docs/adr`,
  `docs/rfcs`, `.carter/state/plans` for end users (ADR-0006 §D4).

## Options Considered

### Option 1: ADRs/RFCs to `docs/`, plans to private `.carter/` (chosen)
- **Pros:** restores location dogfood for ADRs/RFCs (tracked, as the convention
  says) and for plans (private, as the convention says); honors "don't track the
  rest" using Carter's own nested-git regime; no consumer-agent scaffolding.
- **Cons:** `docs/` is no longer product-only (reverses ADR-0006 §D2); `carter check`
  isn't a full pass on the repo (D3); two plan homes (tracked archive + private new).

### Option 2: Keep everything in `design/` (ADR-0006 status quo)
- **Pros:** `docs/` stays product-only; one home for records.
- **Cons:** no location dogfooding at all; plans tracked in the public repo, against
  the maintainer's "don't track the rest" intent.

### Option 3: Full `carter init` for true functional dogfood
- **Pros:** `carter check` runs end-to-end on the repo.
- **Cons:** scaffolds consumer `carter-*-local.md` agents + instructions into the
  tool source — recursive and noisy even if git-ignored. Disproportionate.

## Rationale

Carter's own design already answers "dogfood but don't track": ADRs/RFCs are the
*shared* tier (tracked), plans are the *private* tier (nested `.carter/.git`).
Option 1 simply realigns carter-ai with that split. Restoring ADR/RFC location
dogfood is cheap (a file move) and high-value (the repo becomes a live example of
the shipped layout); restoring plan dogfood privately costs nothing extra because
`.carter/` is built to be git-ignored. Full `carter init` (Option 3) is rejected
as disproportionate for a tool-source repo.

## Consequences

### Positive
- carter-ai again demonstrates the `carter-adr` / `carter-rfc` / `carter-plan`
  storage conventions: ADRs at `docs/adr/`, RFCs at `docs/rfcs/`, plans at
  `.carter/state/plans/`.
- New plan history is versioned privately and never reaches the public repo.
- The discipline dogfood (formats) remains intact — including this ADR.

### Negative / Risks
- `docs/` mixes product docs and design records again (the ADR-0006 §D2 goal is
  given up). Mitigated: ADRs/RFCs are clearly subdirectoried (`docs/adr/`,
  `docs/rfcs/`) and are themselves the convention on display.
- `carter check` is not a full pass on this repo (D3); plan validation is via
  `validate_plans_dir`.
- `.carter/` carries a nested git inside the working tree; it must stay
  git-ignored from the main repo (enforced in `.gitignore`).

## References

- [ADR-0006](0006-repo-records-relocation.md) — the relocation this partially supersedes (§D1 location, §D2 docs-only)
- [ADR-0003 §D5](0003-knowledge-adr-rfc-plan-storage.md) — the shared-vs-private git-regime split this realigns with
- [docs/plans-and-state.md](../plans-and-state.md) — the plan/ADR storage workflow guide
