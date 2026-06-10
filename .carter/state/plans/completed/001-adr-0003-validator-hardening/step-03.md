---
step: 3
status: done
depends_on: []
files_modified: [carter/state.py, carter/cli.py, carter/plans.py, tests/test_state.py, tests/test_plans.py]
---

## Step 3 — Correctness nits (Tier 3)

### #7 — commit_state masks a failed git add (elevated from nit)
`commit_state` ignores `git add -A`'s return code; if it fails, `diff --cached
--quiet` sees nothing staged → returns False, and `carter save` prints "Nothing to
save" on what was actually an error. A silently-failed recovery snapshot is worse
than a loud error precisely because recovery is the feature.
- **Done when**: a failed `git add` surfaces as an error, distinct from the
  legitimate "nothing to commit" no-op.

### #8 — validate_plans_dir docstring overstates sorting
The docstring claims "sorted for stable output" but the aggregated error list is
never sorted (only the dir iteration is).
- **Done when**: the docstring matches behaviour, or the output is actually sorted.

### #9 — no numeric-id collision check
`001-foo` and `001-bar` can coexist in `active/` (distinct dirnames, same NNN).
- **Done when**: duplicate NNN prefixes within a bucket are flagged (or the rule is
  explicitly documented as name-unique, not number-unique).

### Test
Red-then-green for #7 (failed add) and #9 (collision); #8 is doc-only.
