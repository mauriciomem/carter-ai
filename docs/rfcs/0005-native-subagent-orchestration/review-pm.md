# Review: RFC-0005 — pm

## Round 1 — 2026-06-26 — reviewed revision 2 — verdict: approve

*Advisory delta review (ADR-0004 §D5): informs the maestro's synthesis; not a vote. Scope: scope, sequencing, risk, and whether this decomposes into an executable plan.*

**Bottom line.** **Approve** on scope and sequencing. The P0–P5 phasing is genuinely shippable-in-slices, dependencies are ordered correctly, and the riskiest decision (cheap model) is gated behind an eval rather than asserted. My approval is on the *plan shape*; the architect/engineer/devops blockers are real spec gaps but they sharpen the plan, they don't reorder it. A few sequencing refinements below, none blocking.

### Sequencing — sound, with three refinements

| Phase | Risk | Note |
|---|---|---|
| P0 staleness | low | Correct to go first — pure correctness, no behaviour change, unblocks honest review of everything else. The `runSubagent` delete + README reconcile are the cheapest credibility wins. ✓ |
| P1 two-level | low | Self-contained; the `loose`→`guarded` migration is the only user-facing risk and it's a 1-notice fix. ✓ |
| P2 taxonomy+narrator | **med-high** | This is the **largest blast radius** (config + scaffold + 3 test files + the allowlist the architect flagged is missing). Correctly placed after P1 so the level change is absorbed first. ✓ |
| P3 dispatch | med | Independent of P1/P2; could even precede them. Fine where it is. |
| P4 model | med | Correctly gated on P4-eval. ✓ |
| P5 time | low | Independent; could move earlier — it's low-risk and high day-1 value (dated artifacts are wrong *today*). |

**R1 — move P5 (time-awareness) up.** It's low-risk, independent of everything, and fixes a correctness bug that bites on the very next ADR/plan written (this session needed the date supplied by hand). Slot it alongside P0 — it's a "stop writing wrong dates" fix, not a feature. No reason it waits behind the taxonomy rework.

**R2 — P2 needs the architect's A1 (allowlist table) resolved *before* it starts**, or the implementer has no spec. Make "4-category allowlist table exists in the RFC" a P2 entry-gate.

**R3 — P4-eval is on the critical path for the headline cost decision but has no owner/bar.** Concur with architect + devops: state the adherence pass-bar and who runs it. Without a number, "gated on the eval" is decorative.

### Scope — right-sized, one watch-item
- Five decisions + an audit is a lot for one RFC, but they're **genuinely coupled** (you can't simplify the taxonomy without touching levels, can't make the narrator first-class without dropping R6, can't drop R6 without the taxonomy change). Splitting would create artificial dependencies. One RFC is correct here. ✓
- **Watch-item (not a blocker):** the supersede-RFC-0002-in-full scope means the produced ADR is large. Make sure the execution plan, not the ADR, carries the step detail (ADR records the decision; plan carries the work) — ADR-0004 §D6 chain. The §7 `must_haves` seed is already the right move.

### Risk register (for the plan)
- **Highest risk:** the cheap-model accuracy contract (§2). Mitigated by P4-eval + Sonnet-not-Haiku + the explicit "docs stay at Opus bar" directive. Residual: medium, acceptable, watched by the eval.
- **Second:** P2 test re-baseline churn (27 `loose` refs + R-key tables). Mitigated by P1-first. Residual: low.
- **Third:** model-name drift (devops D-note). Mitigated by a sync marker + test. Residual: low.

**Verdict rationale.** Approve — the decomposition is executable, the sequencing respects the dependencies, and the riskiest call is empirically gated. The cross-team blockers are spec-tightening within the existing phase structure, not re-planning. Carry R1–R3 into the plan.
