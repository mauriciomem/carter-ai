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

```markdown
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
- Always check `~/.copilot/knowledge/decisions.md` for related past decisions.
- After creating an ADR, offer to record the decision in `~/.copilot/knowledge/decisions.md` via carter-distill.
- ADRs should be stored in the project repository (e.g., `docs/adr/` or `adr/`).
- Number ADRs sequentially within the project.
- Keep the Context section factual — save opinions for the Rationale.
- List at least 2 options considered, even if the choice seems obvious.
- Reference: Michael Nygard's ADR format (https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).
</guidelines>
