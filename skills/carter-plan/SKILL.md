---
name: carter-plan
description: Create project plans, work breakdown structures, and task dictionaries
---

<objective>
Produce a structured plan **written to disk** under
`.carter/state/plans/active/<NNN-slug>/`, with machine-readable frontmatter and
verifiable `must_haves`. A plan is a directory, not a chat message — this is what
makes session recovery and the quality gate work.

**Language:** write in the workspace `docs_language` (`.carter/carter.yaml`); if it is absent, English unless the user chose another language.
</objective>

<canonical-schema>
The frontmatter schema is defined once in
[docs/reference/frontmatter.md](../../docs/reference/frontmatter.md). Follow it
exactly; `carter check` validates every plan against it and **rejects an
`active` plan that has empty `must_haves`** (the O6 rule). When in doubt, run
`carter check` and fix what it reports.
</canonical-schema>

<planning-framework>

## 1. Think first (this feeds the files, it is not the output)

1. **Scope** — what is the project, its goals, and constraints?
2. **Milestones** — key deliverables and checkpoints.
3. **Work Breakdown Structure** — decompose into work packages → deliverables →
   tasks. Keep tasks small enough to finish in 1–3 days.
4. **Dependencies** — they determine the critical path.
5. **`must_haves`** — the objective, verifiable definition of done. Every plan
   needs at least one (truths / artifacts / key_links). A plan with none is a
   checklist, not a plan, and the validator will reject it.

## 2. Write the plan to disk

**Every plan is a directory** `.carter/state/plans/active/<NNN-slug>/` containing
a `README.md`. Pick the next free `NNN` (001, 002, …); the `<NNN-slug>` directory
name MUST equal the `id` in the frontmatter.

**Tiered structure (thresholds come from `carter.yaml`
`plans:`, defaults shown):**

- **1–3 steps:** keep them inline in the README's Steps table. No step files.
- **> 3 steps (`step_file_threshold`):** each step becomes its own
  `step-NN.md` (frontmatter + tasks + done-criteria); the README Steps table
  links to them.
- **Size budgets:** `README.md` ≤ 150 lines (`readme_max_lines`); each
  `step-NN.md` ≤ 80 lines (`step_max_lines`). Over budget → split detail out.

</planning-framework>

<output-format>

## Plan `README.md`

```markdown
---
id: 001-feature-name
status: active            # proposed | active | blocked | completed | abandoned
created: 2026-06-09
updated: 2026-06-09
adr: null                 # ADR-NNNN if this plan executes an accepted ADR
ai-usage: ai-assisted     # optional: ai-assisted | ai-generated | human-only
tags: []
repos: []
must_haves:               # MANDATORY: >= 1 entry total
  truths:
    - "Observable behaviour that must be true when done"
  artifacts: []
  key_links: []
---

# Plan: [Name]

## Objective
[What this plan achieves, in 1–3 sentences.]

## Milestones
| # | Milestone | Deliverables |
|---|-----------|--------------|
| M1 | ... | ... |

## Steps
| # | Step | Status | File |
|---|------|--------|------|
| 1 | [Task] | pending | — |

## Risks
[Summary; suggest carter-risk for deep analysis.]
```

When a plan has more than 3 steps, the `File` column links each row to its
`step-NN.md` instead of `—`.

## Step file `step-NN.md` (only when > 3 steps)

```markdown
---
step: 2
status: pending           # pending | in-progress | done | blocked
depends_on: [1]
files_modified: []
---

## Step 2: [Name]
[Tasks and done-criteria.]
```

</output-format>

<lifecycle>
- New plans land in `active/<id>/` with `status: active` (or `proposed` while
  still drafting `must_haves`).
- When all `must_haves` are satisfied, the pm verifies and moves the directory
  to `completed/<id>/` and sets `status: completed`. The folder is a coarse
  index; **frontmatter `status` is the source of truth.**
- A blocked plan sets `status: blocked`; never delete a plan — abandon it
  (`status: abandoned`) so the history survives.
</lifecycle>

<guidelines>
- **Fetch the current date before writing the plan.** The frontmatter `created:`/
  `updated:` fields must use the real current date — get today's date with
  `date +%F`. Do this **before writing any dated frontmatter**; never guess from your training cutoff.
- Start from the end state: what does "done" look like? That is your `must_haves`.
- The directory name and the `id` frontmatter MUST match (NNN-kebab).
- Run `carter check` after writing a plan; fix every reported violation before
  calling the plan `active`.
- 1–3 steps inline; > 3 steps get per-step files. Respect the size budgets.
- `carter-plan` owns plan files; `carter-adr` owns ADRs — no overlap.
- Use Jira (via carter-atlassian MCP) to mirror issues when a plan is approved.
- Reference `~/.carter/knowledge/project-history.md` for estimation calibration.
</guidelines>
