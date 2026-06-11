# Review: RFC-0002 — pm

## Round 1 — 2026-06-11 — reviewed revision 1 — verdict: request-changes

Advisory, sequencing-only. The three-phase skeleton (model → emission → lint/tests) is directionally sound and one phased RFC is the right delivery vehicle. But **P2 lands behavior-changing enforcement before P3 provides the lint, escape hatch, and tests that make it safe and verifiable** — a window where drift is undetectable and `strict`-level `deny` gates can hard-block users with no audited override. Pull the escape hatch and emission tests into P2, and ship the lint *with* (not after) emission.

## Sequencing concerns

- **P2-before-P3 inverts the safety net.** P2 emits enforcement (the actual behavior change) while the drift lint, escape hatch, and emission tests all sit in P3. The Summary itself defines "enforcement" as *emission **plus** a deterministic `carter check` that the emitted config matches policy* — so P2 without P3 ships half the definition. → Lint (or at minimum the Q15 install-time degradation WARN) should accompany P2.
- **`deny` emission before escape hatch = hard block.** P2 makes `strict` selectable (R3/R5 = `deny`), but the single-action override + `carter ops` audit is P3. A user choosing `strict` in the P2→P3 window is blocked with **no audited override** — the exact "users disable the whole thing" failure the Trade-offs section warns about. → Ship the escape hatch *with* P2, **or** gate `strict` selection behind P3. (Mitigant: `guarded` default has no `deny`, so this bites only explicit `strict` adopters.)
- **P2 changes behavior untested.** Emission tests are deferred to P3, inverting Carter's own TDD discipline (tests first, then emit). → Move emission unit tests into P2 alongside the templates they cover.
- **Partial-landing posture.** If P3 slips after P2 ships: emitted enforcement with no drift detection, no audit, no tests. Acceptable **only** if P2's default stays `loose`/`guarded` and `strict` is held back; otherwise not. → Add an explicit plan guardrail: *"P2 may not merge without P3's escape hatch + emission tests."*
- **One RFC — agree (Q18).** The four pillars share one config block, one effective-gate formula (`min(level, allowlist)`), and one emission pipeline; splitting them creates cross-RFC dependencies = worse delivery risk. Keep one RFC + one ADR. **But** decompose the *execution plan* into per-phase milestones with a merge gate between P2 and P3, rather than one monolithic plan — so the safety net can't be skipped.

## DECIDE items

- **Q6 — migration messaging timing — DECIDE.** `level: guarded` for new installs is **inert until P2 emits**. Decide whether the user-facing "you're guarded now" message appears in P1 (config present, no enforcement — risks over-promising) or P2 (enforcement real). *Rec:* surface only when emission is live (P2); make the existing-install nudge toward `guarded` an opt-in WARN, never silent.
- **Q19 — ADR numbering — DECIDE (not mine to call).** Accepted RFC wants **ADR-0005**, but 0005 was informally reserved for the deferred backup/durability ADR. Per ADR-0004 the number is locked at the **accept→ADR** step *before* the plan references it — so resolve this **at acceptance**, not in the plan. Risk is real: `docs/adr/` already has a collision (two `0003-*.md` files), so numbering discipline is demonstrably weak. Human call on who gets 0005.
