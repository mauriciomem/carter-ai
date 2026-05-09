---
name: carter-risk
description: Identify risks, assess impact and probability, and design mitigation strategies
argument-hint: "[project or initiative to assess risks for]"
---

<objective>
Perform structured risk identification and assessment. Produce a risk register with impact/probability ratings and concrete mitigation strategies.
</objective>

<risk-framework>

## Risk Assessment Process

1. **Identify risks** — Brainstorm potential risks across categories:
   - **Technical** — Technology choices, complexity, dependencies, performance
   - **Schedule** — Estimation errors, scope creep, dependency delays
   - **Resource** — Team availability, skill gaps, key person dependencies
   - **External** — Vendor changes, API deprecations, compliance requirements
   - **Security** — Vulnerabilities, data exposure, access control gaps
   - **Operational** — Deployment failures, monitoring gaps, incident response

2. **Assess each risk:**
   - **Probability:** Low (< 20%) | Medium (20-60%) | High (> 60%)
   - **Impact:** Low (minor inconvenience) | Medium (significant delay/cost) | High (project failure/security breach)
   - **Risk Score:** Probability × Impact → Priority ranking

3. **Design mitigation** — For each medium/high-scoring risk:
   - **Avoid** — Eliminate the risk by changing approach
   - **Mitigate** — Reduce probability or impact
   - **Transfer** — Shift risk to another party (insurance, SLA, vendor)
   - **Accept** — Acknowledge and monitor (only for low-scoring risks)

4. **Define triggers** — What signals indicate a risk is materializing?

</risk-framework>

<output-format>

## Output Format

```markdown
# Risk Assessment: [Project/Initiative]

## Risk Register

| # | Risk | Category | Probability | Impact | Score | Strategy | Mitigation |
|---|------|----------|------------|--------|-------|----------|------------|
| R1 | ... | Technical | High | High | Critical | Mitigate | ... |
| R2 | ... | Schedule | Medium | Medium | Medium | Avoid | ... |
| R3 | ... | Security | Low | High | Medium | Mitigate | ... |

## Critical Risks (Detailed)

### R1: [Risk Title]
- **Description:** ...
- **Trigger:** What signals this risk is materializing
- **Mitigation plan:** Step-by-step actions
- **Owner:** Who monitors this risk
- **Contingency:** What to do if mitigation fails

## Risk Matrix

|            | Low Impact | Medium Impact | High Impact |
|------------|-----------|---------------|-------------|
| **High P** | Medium    | High          | Critical    |
| **Med P**  | Low       | Medium        | High        |
| **Low P**  | Low       | Low           | Medium      |

## Recommendations
1. [Prioritized actions to address top risks]
```

</output-format>

<guidelines>
- Check `~/.copilot/knowledge/mistakes.md` for risks based on past failures.
- Be specific — "something might go wrong" is not a risk. "Terraform state corruption during concurrent applies" is.
- Every critical risk must have a mitigation plan AND a contingency plan.
- Review risks periodically — suggest adding risk reviews to sprint ceremonies.
</guidelines>
