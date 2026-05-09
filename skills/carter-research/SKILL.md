---
name: carter-research
description: Fetch and summarize official documentation and best practices on a given topic
argument-hint: "[topic or technology to research]"
---

<objective>
Research a topic by finding, reading, and summarizing official documentation and best practices. Produce a structured summary with cited sources that can be used for decision-making or learning.
</objective>

<workflow>

## Research Process

1. **Clarify scope** — What exactly needs to be researched? Ask the user if the topic is broad.

2. **Find official sources** — Prioritize:
   - Official documentation (language docs, framework docs, cloud provider docs)
   - RFCs and specifications
   - Official blogs and changelogs
   - Recognized reference books

3. **Read and extract** — Read the relevant sections. Focus on:
   - How it works (mechanism)
   - When to use it (use cases)
   - When NOT to use it (limitations, anti-patterns)
   - Configuration and setup
   - Security considerations
   - Performance characteristics

4. **Synthesize** — Combine findings into a structured summary.

5. **Deliver** — Present findings with full source citations.

</workflow>

<output-format>

## Output Format

```markdown
# Research: [Topic]

## Summary
[2-3 sentence overview]

## Key Findings

### [Finding 1 Title]
[Detail with source citation]

### [Finding 2 Title]
[Detail with source citation]

## Best Practices
1. [Practice with rationale]
2. ...

## Pitfalls to Avoid
- [Common mistake and why it's wrong]

## Sources
1. [Title](URL) — [brief description of what this covers]
2. ...
```

</output-format>

<guidelines>
- Always cite sources with URLs when available.
- Distinguish between official recommendations and community opinions.
- Note version-specific information (e.g., "as of Python 3.12", "Terraform 1.9+").
- If official docs are insufficient, say so explicitly rather than filling gaps with speculation.
- Offer to record key findings via `carter-mistakes` or suggest `carter-distill` for knowledge base promotion.
</guidelines>
