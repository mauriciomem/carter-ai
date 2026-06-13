---
step: 8
status: done
depends_on: [1]
files_modified: [carter/ops/carter_ops.py, tests/ops/test_operations.py]
---

## Step 8 — Single-action override ledger (P3)

The escape hatch. **Override ≠ authorization** (ADR-0005 §6): the `carter ops`
ledger *records*; it **cannot** lift a platform `deny`.

### Tasks
- Add a single-action override path that logs to the `carter ops` audit ledger
  (gated on `policy.audit_overrides`). No blanket/session-wide overrides
  (avoids override fatigue, Q11).
- Encode the per-tier meaning: at native-deny the user relaxes the emitted config
  (logged); at native-ask, confirm the prompt; at prose-backstop, proceed on trust
  (logged only).

### Done when (TDD red → green)
- A test asserts an override appends **one** ledger entry per action (not
  session-wide) and that the ledger never claims to lift a deny (records only).
- `carter ops` test suite green (`tests/ops/`).
