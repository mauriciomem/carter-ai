---
step: 1
status: pending
depends_on: []
files_modified: []
---

## Step 1 — Recovery integrity (Tier 1)

The two findings that change observable agent behaviour. Both need the validator
to see the plans-root it currently lacks (a small signature change).

### #1 — Dangling checkpoint pointer
`validate_checkpoint` passes a checkpoint whose `active_plan: 001-foo` points at a
plan dir that does not exist. The cursor's whole job is to point into a live plan;
a stale pointer passes `carter check` and misdirects the maestro's "where were we?"
at session start — breaking the feature Phase 3 exists for.

- **Change**: give `validate_checkpoint` the plans-root (or the set of active plan
  ids) so it can verify `active_plan` resolves to an existing `active/<id>/`.
- **Done when**: a checkpoint pointing at a missing plan yields a `carter check`
  error; one pointing at a real active plan stays clean; `active_plan: null` stays clean.

### #2 — Folder ↔ status incoherence
A `status: completed` plan physically in `active/` (or an `active` plan in
`completed/`) passes validation, but the maestro reads `active/` for "in progress"
— so a finished plan resurfaces as active. (`proposed`/`blocked` in `active/` are
sanctioned by the skill and must stay clean.)

- **Change**: in `validate_plans_dir`, flag a plan whose frontmatter status
  contradicts its bucket — `completed` must not sit in `active/`, and a
  non-`completed` status must not sit in `completed/`.
- **Done when**: the two contradictions are flagged; proposed/active/blocked in
  `active/` and completed in `completed/` stay clean.

### Test
Red-then-green: dangling pointer, valid pointer, null; completed-in-active,
active-in-completed, and the sanctioned-status cases.
