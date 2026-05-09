---
name: carter-code-review
description: Review code for quality, design patterns, security, and testability
argument-hint: "[file, PR, or code to review]"
---

<objective>
Perform a structured code review focusing on quality, maintainability, security, and testability. Produce actionable feedback categorized by severity.
</objective>

<review-checklist>

## Review Dimensions

### 1. Correctness
- Does the code do what it claims?
- Are edge cases handled?
- Are error paths covered?

### 2. Design
- Is the code well-structured (separation of concerns)?
- Are design patterns used appropriately?
- Is there unnecessary complexity?
- Could this be simpler without losing functionality?

### 3. Readability
- Are names descriptive and consistent?
- Is the control flow easy to follow?
- Would a junior developer understand this without extensive context?

### 4. Security (OWASP Top 10)
- Input validation at boundaries?
- SQL injection, XSS, CSRF protection?
- Secrets not hardcoded?
- Proper authentication/authorization checks?
- Dependencies scanned for vulnerabilities?

### 5. Testing
- Are tests present? Are they meaningful?
- Are edge cases tested?
- Is test coverage adequate for the risk level?
- Are tests maintainable (not brittle)?

### 6. Performance
- Any obvious N+1 queries or unnecessary allocations?
- Are data structures appropriate for the access patterns?
- Could hot paths be optimized?

</review-checklist>

<output-format>

## Output Format

```markdown
# Code Review: [File/PR/Component]

## Summary
[1-2 sentence overall assessment]

## Findings

| # | Severity | Category | Location | Finding | Suggestion |
|---|----------|----------|----------|---------|------------|
| 1 | Critical | Security | file:L42 | ... | ... |
| 2 | Major | Design | file:L15 | ... | ... |
| 3 | Minor | Readability | file:L88 | ... | ... |
| 4 | Nit | Style | file:L3 | ... | ... |

## Positive Observations
- [What's done well — always include at least one]

## Recommendations
1. [Prioritized action items]
```

Severity levels:
- **Critical** — Security vulnerability, data loss risk, or crash
- **Major** — Bug, significant design issue, or missing tests for critical path
- **Minor** — Improvement opportunity, non-critical pattern issue
- **Nit** — Style, naming, minor readability

</output-format>

<guidelines>
- For Python code, also invoke `carter-python` checklist.
- For Go code, also invoke `carter-golang` checklist.
- Read the full context (surrounding code, tests) before reviewing.
- Prioritize findings by severity — don't bury critical issues among nits.
- Always note what's done well. Reviews are for improvement, not punishment.
</guidelines>
