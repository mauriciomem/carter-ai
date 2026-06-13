---
step: 5
status: pending
depends_on: [1, 4]
files_modified: [templates/agents/carter-maestro.md.j2, templates/agents/carter-narrator.md.j2, carter/installer.py, tests/test_scaffold.py]
---

## Step 5 — Policy-driven maestro table + migration message + R6 handoff (P2)

Replace the `skepticism`-gated prose with an always-present, policy-driven gate,
and wire the R6 content overlay (ADR-0005 D4).

### Tasks
- Upgrade the maestro "Skepticism Calibration" table (`carter-maestro.md.j2:~170`)
  to a policy-driven risk/gate table that renders regardless of
  `personality.skepticism`.
- Wire the **R6 overlay**: narrator authors + redacts R6 content → **devops
  transmits** under R2 (narrator→devops handoff); two-lane short-form vs
  substantive (D4). Single-pusher invariant preserved.
- Surface the **"you're `guarded` now"** migration message **here** (P2, where
  enforcement is real), not P1.

### Done when (TDD red → green)
- A test asserts the maestro gate table renders when `skepticism != scaled`.
- A test asserts the migration message fires for a `guarded` install and **not**
  for `loose`.
- Test suite green.
