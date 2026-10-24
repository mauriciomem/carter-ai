---
name: carter-triage
description: Classify user requests and route to the appropriate Carter specialist agent
argument-hint: "[user request to classify]"
---

<objective>
Analyze the user's request and determine which Carter specialist agent(s) should handle it. Route to the right agent or chain multiple agents for cross-domain tasks.
</objective>

<routing-table>

| Domain | Agent | Example Triggers |
|--------|-------|-----------------|
| System design, architecture, trade-offs | carter-architect | design, architecture, scalability, diagram, ADR, cloud patterns |
| Code quality, implementation, testing | carter-engineer | code, review, test, refactor, debug, implement, Python, Go |
| Infrastructure, CI/CD, deployment, IaC | carter-devops | deploy, pipeline, terraform, container, git, AWS, CI/CD, k8s |
| Learning, documentation, explanation | carter-learner | explain, learn, document, research, why, how does, teach |
| Planning, project management, tracking | carter-pm | plan, roadmap, risk, milestone, sprint, standup, WBS, tasks |
| External-facing content, redaction | carter-narrator | jira comment, PR description, slack draft, release note, docs, announcement, external |
| Security review, threat modeling, vuln/CVE triage, IR | carter-security | threat model, secure code review, vuln, CVE, advisory, secrets, incident response, hardening, OWASP, supply-chain |

carter-maestro is the router itself (it runs this classification); it never appears as a delegation target.

</routing-table>

<rules>

## Classification Rules

1. **Single domain** — If the request clearly maps to one agent, delegate directly to that specialist.

2. **Multi-domain** — If the request spans domains, determine the logical execution order and chain agents:
   - Example: "Build and deploy a Python API" → carter-engineer (code) → carter-devops (deploy)
   - Pass the output of each agent as context to the next.

3. **Ambiguous** — If the domain is unclear, ask the user: "This could be handled by [Agent A] or [Agent B]. Which focus do you want?"

4. **Trivial** — If the request is a simple factual question or clarification, answer directly without delegation.

5. **Knowledge check** — Before delegating, check `~/.copilot/knowledge/` for relevant past decisions or lessons that should be passed as context to the specialist.

</rules>
