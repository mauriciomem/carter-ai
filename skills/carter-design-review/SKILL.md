---
name: carter-design-review
description: Analyze a proposed architecture for patterns, anti-patterns, scalability, and security
argument-hint: "[architecture description or repo to review]"
---

<objective>
Perform a structured review of a proposed or existing architecture, identifying strengths, weaknesses, risks, and recommendations.
</objective>

<review-framework>

## Review Dimensions

Evaluate the architecture across these dimensions:

### 1. Component Design
- Are responsibilities clearly separated?
- Are there single points of failure?
- Is the coupling between components appropriate (loose where possible)?

### 2. Scalability
- Which components are stateful vs stateless?
- Where are the bottlenecks under load?
- Can components scale independently?

### 3. Reliability
- What happens when each component fails?
- Are there retry/fallback mechanisms?
- Is there circuit-breaking for external dependencies?

### 4. Security
- Is the attack surface minimized?
- Are authentication and authorization properly placed?
- Is data encrypted in transit and at rest?
- Are secrets managed properly (not hardcoded)?

### 5. Operability
- Can the system be monitored and observed?
- Are logs structured and actionable?
- Can deployments be rolled back?

### 6. Cost
- Are resources right-sized?
- Are there cost traps (e.g., unbounded queues, unthrottled APIs)?

## Output Format

```markdown
# Architecture Review: [Name]

## Summary
[1-2 sentence assessment]

## Strengths
- ...

## Concerns
| # | Area | Severity | Description | Recommendation |
|---|------|----------|-------------|----------------|
| 1 | ...  | High/Med/Low | ... | ... |

## Recommendations
1. [Prioritized list]

## Questions for the Team
- [Open questions that need answers before finalizing]
```

</review-framework>

<guidelines>
- Always check `~/.copilot/knowledge/decisions.md` for prior related decisions.
- Cite relevant architecture patterns by name (e.g., "Strangler Fig", "CQRS", "Event Sourcing").
- Consider the team's operational capacity — a perfect architecture they can't operate is worse than a good-enough one they can.
- Recommend the `carter-diagram` skill if a visual would help.
- Recommend the `carter-adr` skill if a decision needs formal recording.
</guidelines>
