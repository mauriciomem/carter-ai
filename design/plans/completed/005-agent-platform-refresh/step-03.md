---
step: 3
status: done
depends_on: [2]
files_modified: [carter/config.py, carter/scaffold.py, templates/agents/carter-narrator.md.j2, templates/agents/carter-maestro.md.j2, templates/instructions/copilot-instructions.md.j2, agents/carter-narrator.md, tests/test_config.py, tests/test_scaffold.py, tests/test_policy_lint.py, docs/strictness-policy.md, docs/reference/frontmatter.md]
---

## Step 3 — P2: 4-category taxonomy + first-class narrator + enforced redaction

Biggest blast radius. **Entry-gate (ADR-0010 / RFC R2): the 4-category allowlist table must exist in
the RFC** — it does (RFC §4) — so this may start. Collapse the taxonomy and re-derive everything from
the printed allowlist; name redaction as an enforced gate-tier handoff.

### Tasks
- `carter/config.py`: collapse `RISK_TAXONOMY` to **4 categories** — `read`, `local-write`,
  `remote-write` (secret-access/old R4 **merged in**), `dangerous` (R3+R5). Delete the standalone
  secret-access category and the **R6 overlay**.
- Re-derive `AGENT_ALLOWLIST` to the ADR-0010 D4 table: maestro/architect/learner = `{read}`;
  pm/narrator/engineer = `{read, local-write}`; devops = all four. Re-derive bash-globs + the policy
  lint from it.
- **First-class narrator:** remove the R6-only special-casing (sole-R6-author, the narrator no-MCP
  scope exception); narrator participates in dispatch like any specialist.
- **Enforced redaction (D5):** at `guarded`/`strict`, substantive outward content is a **`gate`-tier
  narrator handoff encoded in the allowlist** (one-liners = `ask` + inline check). Keep
  `redaction.enabled` + the force-the-pass-at-`guarded`/`strict` fix ([scaffold.py:237-240]), decoupled
  from R6. Update the narrator + maestro templates to express the handoff as a gate, not prose.

### Done when (TDD red → green)
- A test asserts the taxonomy has exactly 4 categories and secret-access resolves to `remote-write`
  (`ask` at guarded, `gate` at strict).
- A test asserts the per-agent allowlist matches the D4 table (devops sole `remote-write`/`dangerous`
  holder; engineer no `remote-write`; pm/narrator hold `local-write`, not `remote-write`).
- A test asserts substantive outward content emits a `gate`-tier narrator handoff in the allowlist, and
  that `guarded`/`strict` force the redaction pass even when `redaction.enabled: false`.
- `grep -rn 'R6\|R4\|secret-access' carter/` shows no standalone category survives.
- 2-level × 4-category gate map re-baselined across the 3 test files; `python -m pytest tests/ -q
  -p no:cacheprovider` green.
