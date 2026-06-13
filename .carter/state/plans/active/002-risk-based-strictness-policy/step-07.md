---
step: 7
status: pending
depends_on: [1, 3, 4]
files_modified: [carter/cli.py, carter/plans.py, tests/test_install.py]
---

## Step 7 — `carter check` policy lint + hard ack + redaction WARN (P3)

The deterministic, offline lint that verifies the emitted config matches the
declared policy (ADR-0005 D2/D3). It **cannot** verify runtime denial — documented
out of scope (Q17).

### Tasks
- Lint emitted agent frontmatter ↔ declared allowlist + the active level's gate
  map; flag category↔gate mismatches.
- Detect **drift** between `carter.yaml policy` and the installed agent/MCP files.
- **HARD ACK (Q15):** strict on a non-enforcing target requires an explicit ack;
  add the non-interactive `--accept-degraded` flag; **fail closed** without it.
- **Redaction WARN (Q16):** WARN on `strict|guarded` + `redaction.enabled: false`.
- Fold **N2**: do **not** false-WARN "server not wired" when `--mcp` is omitted.

### Done when (TDD red → green)
- Tests: a matching install passes; an allowlist/gate mismatch and a drift case
  fail; strict-on-weak-target without `--accept-degraded` fails closed, with it
  passes; the redaction contradiction WARNs; `--mcp`-omitted does **not**
  false-WARN.
- Ties back to must_haves: the `carter check` lint truth + the redaction WARN truth.
