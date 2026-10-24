---
id: ADR-0006
status: accepted
created: 2026-06-13
decided: 2026-06-13
supersedes: []
superseded_by: ADR-0007§D1§D2
rfc: null
tags: [repo, docs, organization, adr, rfc, plans]
---

# ADR-0006: Relocate carter-ai's own design records to `design/`

> **Status note (2026-10-24):** Partially superseded by ADR-0007 (§D1, §D2). The `design/` tree no longer exists — its completed plans were deleted in 2026-10.

**Status:** Accepted
**Date:** 2026-06-13
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** [ADR-0003](0003-knowledge-adr-rfc-plan-storage.md) (product storage layout — unchanged), [ADR-0004](0004-rfc-system.md) (RFC system — unchanged)

---

## Context

carter-ai's repository had accumulated three different kinds of Markdown under
`docs/`, intermixed:

1. **Permanent product documentation** — how to *use* Carter (`getting-started.md`,
   `carter-ops.md`, `testing.md`, `strictness-policy.md`, `reference/`).
2. **The project's own design records** — its ADRs (`docs/adr/`), RFCs
   (`docs/rfcs/`), and the dogfooded execution plans (`.carter/state/plans/`).
3. **Pre-build scratch** — exploratory analysis, conversation logs, and example
   files (`docs/analysis/`, `docs/interactions/`, `docs/examples/`).

This mixed three audiences in one tree and made `docs/` a poor "permanent product
docs" home. A reader could not tell product documentation from project history
from throwaway notes.

A subtlety: the `carter-adr` / `carter-rfc` / `carter-plan` skills (and the agent
templates) define where the **Carter tool** scaffolds these artifacts in an
*end-user* workspace — `docs/adr/`, `docs/rfcs/`, `.carter/state/plans/`. That is a
**product** decision (ADR-0003/0004) and is **not** in scope here.

## Decision

A carter-ai-**repository-only** reorganization. The conventions the tool ships are
unchanged.

- **D1 — `design/` holds the project's own design records.** carter-ai's ADRs,
  RFCs, and execution plans move to a single top-level folder:
  `design/adr/`, `design/rfcs/`, `design/plans/`. ADRs and RFCs move *together* so
  their relative cross-links remain valid.
- **D2 — `docs/` holds only permanent product documentation.** After the move,
  `docs/` contains the user-facing Markdown at its root plus `docs/reference/`.
- **D3 — Scratch leaves git.** `docs/analysis/`, `docs/interactions/`, and
  `docs/examples/` move to a top-level `notes/` directory that is git-ignored —
  kept on disk for reference, out of version control.
- **D4 — The shipped tool conventions are intentionally unchanged.** The
  `carter-adr` / `carter-rfc` / `carter-plan` skills and the agent templates still
  scaffold end-user ADRs to `docs/adr/`, RFCs to `docs/rfcs/`, and plans to
  `.carter/state/plans/`. carter-ai deliberately stops dogfooding those exact
  paths for its *own* meta-records; the tool's behavior for users is untouched.

## Options Considered

### Option 1: `design/` umbrella (chosen)
- **Pros:** one obvious home for all project records; clean `docs/` = product docs;
  adr↔rfc cross-links survive; no change to the shipped tool.
- **Cons:** carter-ai no longer mirrors its own scaffolding paths; frozen ADRs that
  cite the old layout now read as historical.

### Option 2: Keep everything under `docs/`, just delete scratch
- **Pros:** smallest change; preserves dogfooding of `docs/adr` / `docs/rfcs`.
- **Cons:** `docs/` stays a mix of product docs and project history; the plans
  remain in `.carter/`, which the maintainer wanted out.

### Option 3: Change the tool conventions too (ship `design/` to users)
- **Pros:** carter-ai would keep dogfooding its own paths.
- **Cons:** a product-behavior change affecting every workspace — out of proportion
  to a repo cleanup, and would itself warrant an RFC.

## Rationale

`docs/` should answer "how do I use Carter?" and nothing else. Project records are
a different audience (contributors/historians) and belong in their own clearly
named home. Keeping the move repo-only (Option 1, not Option 3) avoids changing
the product for a housekeeping goal, honoring the principle that a reorganization
of one repo should not ripple into every user's workspace.

## Consequences

### Positive
- `docs/` is now purely permanent product documentation.
- All project design records live under one discoverable `design/` tree.
- Scratch is retained on disk but no longer clutters the repo or its history.

### Negative / Risks
- carter-ai no longer dogfoods the exact `docs/adr` / `.carter/state/plans` paths it
  ships — a deliberate, documented divergence (D4).
- Frozen ADR-0003/0004 reference the old layout and link to
  `docs/analysis/implementation-plan.md` (now in git-ignored `notes/`). Per the
  immutability rule, those ADRs are **not** edited; this ADR records the relocation
  so the history stays honest.

## References

- [ADR-0003](0003-knowledge-adr-rfc-plan-storage.md) — product storage layout (unchanged for end-user workspaces)
- [ADR-0004](0004-rfc-system.md) — RFC system (unchanged)
- design/README.md (record removed 2026-10) — index of the relocated records
