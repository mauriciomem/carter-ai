---
step: 2
status: done
depends_on: [1]
files_modified: [carter/config.py, carter/scaffold.py, tests/test_config.py, tests/test_policy_lint.py, tests/test_scaffold.py, docs/strictness-policy.md, docs/getting-started.md, docs/reference/frontmatter.md]
---

## Step 2 — P1: two strictness levels; `loose` purged entirely

`POLICY_LEVELS = ("guarded", "strict")`, default `guarded` everywhere. ADR-0010 D3: total purge of
`loose` — **no migration notice, no coercion branch**. Self-contained; lands before P2 so the
level change is absorbed before the taxonomy re-derive.

### Tasks
- `carter/config.py`: `POLICY_LEVELS → ("guarded", "strict")`; drop the `loose` column from
  `RISK_TAXONOMY`; `DEFAULT_CONFIG["policy"]["level"] → "guarded"`; remove the `loose` default-resolution
  branch and `_emit_level`'s `loose` handling — an absent/legacy level resolves to `guarded` via the
  normal default path (no dedicated `loose` case).
- `carter/scaffold.py`: delete the `config_warnings`/`policy_notice` `loose` branches; `_validate_policy`
  lists only `guarded|strict`.
- Docs: purge `loose` from [docs/strictness-policy.md], [docs/getting-started.md], README, and
  [docs/reference/frontmatter.md]. **Live surfaces only** — `design/plans/completed/002-*` is archived
  history and is NOT edited.

### Done when (TDD red → green)
- A test asserts a stale `level: loose` in a user `carter.yaml` LOADS as `guarded` with **no notice and
  no error** (resolves via the default path). There is NO `loose`→`guarded` migration message.
- A test asserts `_validate_policy` accepts only `guarded|strict`.
- `grep -rniE '\bloose\b' carter/ tests/ docs/ templates/ agents/ skills/ README.md` returns only the
  unrelated "loose coupling" prose (zero policy-level references).
- `tests/test_config.py` / `tests/test_policy_lint.py` / `tests/test_scaffold.py` re-baselined (no
  `loose` migration test — there is no migration); `python -m pytest tests/ -q -p no:cacheprovider` green.
