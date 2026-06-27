---
name: carter-adr
description: Create Architecture Decision Records documenting design choices, context, and rationale
argument-hint: "[decision title or topic]"
---

<objective>
Create a structured Architecture Decision Record (ADR) that captures the context, decision, rationale, and consequences of an architectural choice.
</objective>

<template>

## ADR Template

Every ADR carries **both** a YAML frontmatter block (machine-readable) and the
human Status block (for readers). Schema source:
[docs/reference/frontmatter.md](../../docs/reference/frontmatter.md).

```markdown
---
id: ADR-[NUMBER]
status: proposed              # proposed | accepted | rejected | superseded | deprecated
created: YYYY-MM-DD
decided: null                 # date once accepted
supersedes: []                # ADR ids or "ADR-NNNN§Dn"
superseded_by: null
rfc: null                     # RFC-NNNN this ADR records (optional)
tags: []
---

# ADR-[NUMBER]: [TITLE]

**Status:** Proposed | Accepted | Deprecated | Superseded by ADR-[N]
**Date:** YYYY-MM-DD
**Deciders:** [who was involved]

## Context

[What is the issue or situation that motivates this decision? What constraints exist?]

## Decision

[What is the change or choice being made?]

## Options Considered

### Option 1: [Name]
- **Pros:** ...
- **Cons:** ...

### Option 2: [Name]
- **Pros:** ...
- **Cons:** ...

### Option 3: [Name]
- **Pros:** ...
- **Cons:** ...

## Rationale

[Why this option was chosen over the alternatives. Reference specific requirements, constraints, or trade-offs.]

## Consequences

### Positive
- ...

### Negative
- ...

### Risks
- ...

## References

- [Links to relevant documentation, RFCs, prior ADRs]
```

</template>

<guidelines>
- **Fetch the current date before writing the ADR.** The frontmatter `created:`/
  `decided:` fields and the human **Date:** line must use the real current date —
  obtain it from a native harness date variable where the target exposes one,
  otherwise run `date`. Do this **before writing any dated frontmatter**; never
  guess from your training cutoff.
- Always check `~/.copilot/knowledge/decisions.md` for related past decisions.
- After creating an ADR, offer to record the decision in `~/.copilot/knowledge/decisions.md` via carter-distill.
- ADRs should be stored in the project repository (e.g., `docs/adr/` or `adr/`).
- Number ADRs sequentially within the project.
- Keep the Context section factual — save opinions for the Rationale.
- List at least 2 options considered, even if the choice seems obvious.
- **One ADR = one coherent decision.** It MAY bundle labeled sub-decisions `D1..Dn` ONLY if they are interdependent (share one rationale/boundary). Independent decisions go in separate ADRs.
- **A change or reversal is a NEW ADR, never an edit.** An Accepted ADR is immutable; a later decision creates a new ADR with `supersedes: ADR-NNNN§Dn`. Backfilling frontmatter is a metadata addition (permitted), not a decision change.
- **Size budget: an ADR > 400 lines MUST be split** (extract a sub-area into its own ADR). This budget is a skill constant — ADRs live in the main repo, outside any `.carter/`, so `carter.yaml` does not govern them.
- Frontmatter + the human Status block are both required; keep them in sync. Schema: [docs/reference/frontmatter.md](../../docs/reference/frontmatter.md).
- Reference: Michael Nygard's ADR format (https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
</guidelines>
