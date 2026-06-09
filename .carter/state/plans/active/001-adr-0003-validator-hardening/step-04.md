---
step: 4
status: pending
depends_on: [1, 2, 3]
files_modified: []
---

## Step 4 — Design honesty + test coverage

Lands after 1–3 so the notes reflect the final behaviour.

### A — State that validation is opt-in
Nothing runs `carter check` automatically — not `init`, no git hook; only the
maestro prompt says to. O3's determinism only bites if invoked. This is the chosen
design (O3 = validate, not generate), so it's correct — but it is the residual
risk and should be stated plainly, not discovered later.
- **Done when**: a one-line "validation is opt-in; run `carter check`" note exists
  in docs/plans-and-state.md (and/or the ADR consequences). No code change.

### B — Close the test gaps
From the first audit, still open:
- End-to-end recovery through the `carter save` CLI (today only direct
  `commit_state` + manual `git checkout`).
- `save`'s default timestamped-message branch (tests always pass `-m`).
- `commit_state(allow_empty=True)` directly; `_git_init` idempotency.
- `_count_step_rows` over-count cases (two tables / extra pipe line / no separator).
- **Done when**: each gap has a test.

### Note
No scope change anywhere in this plan — these harden and document the existing
ADR-0003 shape; they do not alter its decisions.
