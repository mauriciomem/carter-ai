---
step: 9
status: pending
depends_on: [4, 7, 8]
files_modified: [carter/scaffold.py, tests/test_scaffold.py, tests/test_install.py]
---

## Step 9 — Emission/lint tests + P2→P3 gate (P3)

Lands last. **This step IS the P2→P3 gate**: `strict` enforcement is enabled and
proven here, only **after** emission (step 4), the lint (step 7), and the escape
hatch (step 8) are green — hence `depends_on: [4, 7, 8]`.

### Tasks
- Enable the **`strict`** gate map (R3/R5 `deny`) in emission, now backed by the
  step-7 lint + the step-8 escape hatch.
- Complete the emission + lint unit-test matrix across all three targets; document
  that **runtime denial is manual / out of scope** (Q17).
- Fold **N3**: assert the "read-only" drop holds in **both** statics and templates
  (the parity guard from step 2 stays green).
- Optional **G1**: an R6-degradation-specific honesty WARN (folded into the Q15 ack).

### Done when (TDD red → green)
- Strict emission + lint pass on an enforcing target and **hard-ack** on a weak one.
- Full suite green: `python -m pytest tests/ evals/test_skills.py
  evals/test_routing.py -q -p no:cacheprovider` (exclude `evals/test_live.py`).
- Ties back to must_have: "`strict` enforcement ships only after P3 … (P2→P3 gate)".
