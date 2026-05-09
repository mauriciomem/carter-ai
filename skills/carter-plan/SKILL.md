---
name: carter-plan
description: Create project plans, work breakdown structures, and task dictionaries
argument-hint: "[project or initiative to plan]"
---

<objective>
Create structured project plans with work breakdown structures (WBS), task dictionaries, milestone identification, and resource/time estimation using Agile methodology.
</objective>

<planning-framework>

## Planning Process

1. **Understand scope** — What is the project? What are the goals and constraints?

2. **Define milestones** — Identify key deliverables and checkpoints throughout the project lifecycle.

3. **Work Breakdown Structure (WBS)** — Decompose the project into manageable work packages:
   - Level 1: Major phases or epics
   - Level 2: Deliverables within each phase
   - Level 3: Tasks within each deliverable
   - Level 4: Subtasks (if needed)

4. **Task Dictionary** — For each task, define:
   | Field | Description |
   |-------|-------------|
   | ID | Unique identifier (e.g., 1.2.3) |
   | Name | Descriptive task name |
   | Description | What needs to be done |
   | Dependencies | Which tasks must complete first |
   | Acceptance criteria | How to know it's done |
   | Estimated effort | Story points or time range |
   | Priority | Must-have / Should-have / Nice-to-have |

5. **Risk identification** — Flag known risks (suggest `carter-risk` for detailed analysis).

6. **KPIs** — Define measurable success criteria for the project.

</planning-framework>

<output-format>

## Output Format

```markdown
# Project Plan: [Name]

## Overview
[Brief description, goals, constraints]

## Milestones
| # | Milestone | Target Date | Deliverables |
|---|-----------|-------------|-------------|
| M1 | ... | ... | ... |

## Work Breakdown Structure
### Phase 1: [Name]
- 1.1 [Deliverable]
  - 1.1.1 [Task] — [effort estimate]
  - 1.1.2 [Task] — [effort estimate]
- 1.2 [Deliverable]
  - 1.2.1 [Task]

### Phase 2: [Name]
...

## Task Dictionary
[Detailed table for complex tasks]

## Risks
[Summary with reference to carter-risk for deep analysis]

## KPIs
| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| ... | ... | ... |
```

</output-format>

<guidelines>
- Start with the end state: what does "done" look like?
- Keep tasks small enough to complete in 1-3 days (Agile sprint-compatible).
- Identify dependencies explicitly — they determine the critical path.
- Use Jira (via carter-atlassian MCP) to create issues when the plan is approved.
- Reference past projects in `~/.copilot/knowledge/project-history.md` for estimation calibration.
</guidelines>
