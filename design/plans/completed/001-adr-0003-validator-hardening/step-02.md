---
step: 2
status: done
depends_on: []
files_modified: [carter/plans.py, tests/test_plans.py]
---

## Step 2 — Validator strict mode (Tier 2)

Lenient validation lets malformed input through. Tighten without changing the
schema.

### #3 — Unknown must_haves sub-key counts as zero (misleading O6)
`must_haves: {truth: [...]}` (singular typo) counts 0 entries, so an active plan
gets "must declare at least one must_haves entry" even though the author wrote
some — the error actively misleads.
- **Done when**: an unrecognized `must_haves` sub-key is reported as unknown; the
  O6 message fires only when truths/artifacts/key_links are genuinely all empty.

### #4 — created / updated unvalidated
Required as keys, but `created: not-a-date` / `created: null` pass. The schema
says these are dates.
- **Done when**: a non-date `created`/`updated` is flagged.

### #5 — step value not integer / not matched to filename
`_validate_step_file` accepts `step: "two"` or `step: 99` inside `step-01.md`;
`depends_on` elements aren't checked as ints.
- **Done when**: non-int `step`, `step` ≠ filename number, and non-int
  `depends_on` elements are flagged.

### #6 — the >3-steps threshold is bypassable
`_count_step_rows` only counts a Markdown table; a plan listing 5 steps in prose
returns None, so the split rule is silently skipped. The `## Steps` matcher also
requires "steps" (plural) and miscounts on a second table / an h3 subsection.
- **Done when**: the heuristic's limits are documented and (where cheap) a prose
  step list no longer silently bypasses the split rule.

### Test
One red-then-green case per finding.
