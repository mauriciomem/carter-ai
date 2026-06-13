---
step: 1
status: done
depends_on: []
files_modified: [carter/config.py, tests/test_config.py]
---

## Step 1 — P1 policy model (config + R0–R6 taxonomy + tool→risk map)

The model layer, **no behavior change** — nothing emits or enforces yet. Adds the
`policy` block and the shipped risk data, all **dict-shaped** to survive
`_deep_merge`'s wholesale list replacement (`carter/config.py` `_deep_merge`).

### Tasks
- Add a `policy` block to `DEFAULT_CONFIG` (`carter/config.py`): `level`
  (loose|guarded|strict), `unknown_tool` (allow|ask|deny), `overrides: {}`
  (category→gate), `audit_overrides: true`.
- Ship the **risk taxonomy R0–R6** (category → per-level gate), the **tool→risk
  map**, and the **per-agent allowlist** as **dicts** (`{tool: risk}`,
  `{agent: {category: bool}}`) — never lists.
- Default resolution (Q6): **new** installs resolve to `guarded`; an existing
  config with an omitted `policy` block resolves to `loose` (no behavior change).
- Add a most-restrictive-wins precedence helper for multi-category actions.

### Done when (TDD red → green)
- A test asserts a user `policy` override deep-merges **without** wiping the
  shipped tool→risk map / allowlist (the dict-shaped merge; a list shape fails it).
- A test asserts an omitted `policy` → `loose`, and a fresh install → `guarded`.
- Ties back to must_have: "carter.yaml accepts a `policy` block … dict-shaped …".
- `python -m pytest tests/ -q -p no:cacheprovider` green.
