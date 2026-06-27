---
step: 4
status: done
depends_on: [3]
files_modified: [carter/config.py, carter/scaffold.py, templates/agents/carter-maestro.md.j2, agents/carter-maestro.md, tests/test_parity.py, tests/test_policy_lint.py, docs/reference/frontmatter.md]
---

## Step 4 — P3: native dispatch + fail-closed allowlist lint + `/fleet` rule

Emit the real dispatch primitive per target. Independent of P1/P2 (could precede them) but placed here
so the policy seam is settled first. ADR-0010 D1.

### Tasks
- **VS Code / Copilot (maestro frontmatter):** emit `tools: ['agent']`, an **explicit** `agents:
  [carter-architect, carter-engineer, carter-devops, carter-learner, carter-pm, carter-narrator]`, and
  `handoffs:` (the gate-confirm surface for gate-tier actions). Never `'*'` or a glob.
- **OpenCode (maestro `permission`):** emit a `permission.task` block with `'*': deny` + an **explicit
  per-specialist allow entry** for each Carter specialist. Never a `carter-*` glob.
- **Flat chain:** specialists carry `agents: []`.
- **Fail-closed dispatch lint:** extend `carter check` to **error (exit non-zero)** if the primary's
  emitted `agents:`/`permission.task` is `'*'`, a glob, or absent. Not a warning.
- **`/fleet` context rule (Copilot CLI):** the maestro template prose MUST instruct injecting the
  active-plan + knowledge context into every `/fleet` prompt (subagents don't inherit chat history).
- Extend `policy_native_keys` + parity for the new keys; document `/fleet` + `@`-mention as the runtime
  Copilot-CLI orchestration path (no frontmatter change there).

### Done when (TDD red → green)
- A test asserts the maestro emits `agent`+`agents:`+`handoffs:` (copilot) and `permission.task`
  (opencode) as **explicit per-specialist lists**; specialists emit `agents: []`.
- A `carter check` lint test asserts it **fails (non-zero)** when `agents:`/`permission.task` is `'*'`,
  a glob, or absent on the primary — and passes on the explicit list.
- A test asserts the maestro Copilot-CLI prose contains the `/fleet` context-injection instruction.
- `python -m pytest tests/ -q -p no:cacheprovider` green.
