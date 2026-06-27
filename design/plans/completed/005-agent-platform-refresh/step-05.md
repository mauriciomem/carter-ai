---
step: 5
status: done
depends_on: [4]
files_modified: [carter/config.py, carter/scaffold.py, templates/agents/*.j2, agents/*.md, tests/test_config.py, tests/test_parity.py, tests/test_policy_lint.py, docs/reference/frontmatter.md]
---

## Step 5 — P4: per-agent model (`models:` block, name table, advisory)

Per-agent model emission. **Gated on Step 6 for the cheap-tier default** — this step ships the
mechanism; Step 6's eval decides whether Sonnet 4.6 is the shipped implementer default. ADR-0010 D2/D7.

### Tasks
- Add a **`models:` block** to `DEFAULT_CONFIG` (dict-shaped, to survive `_deep_merge`): `default`,
  `thinkers`, `implementers`, `overrides`. Resolution **`overrides` > tier > `default`** (`default` =
  un-tiered catch-all). thinkers = {maestro, architect, pm, learner, narrator} = Opus 4.8; implementers
  = {engineer, devops} = Sonnet 4.6; Haiku is opt-in via `overrides` only.
- **Emit a single per-target `model:` string** per agent (NOT an array — breaks Copilot CLI): display
  name for VS Code/Copilot, `provider/model` ID for OpenCode.
- **Carter→target model-name table**: one home, a `MODEL LAUNCH` sync marker, and a non-empty-per-role
  test so a model rename can't silently produce a dead agent.
- **Required `carter check` advisory:** always print "agent X pins model Y; Carter cannot verify your
  subscription includes it" — Carter emits anyway (can't verify subscription).
- **No effort key emitted** — document the global `--effort high` default (per-session overridable) in
  the strictness/getting-started docs. No `temperature` (already dropped in Step 1).

### Done when (TDD red → green)
- A test asserts model resolution order `overrides > tier > default` (an override wins over the tier;
  the tier wins over default; an un-tiered agent gets default).
- A test asserts each agent emits exactly one per-target `model:` string (not an array), correct per
  target shape (display name vs `provider/model`).
- A test asserts the model-name table is non-empty for every shipped role and the `MODEL LAUNCH` marker
  is present; a test asserts `carter check` prints the unverifiable-model advisory.
- `grep -rn 'temperature' templates/ agents/` is clean; `python -m pytest tests/ -q
  -p no:cacheprovider` green.
