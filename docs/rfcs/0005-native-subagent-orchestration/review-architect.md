# Review: RFC-0005 — architect

## Round 1 — 2026-06-26 — reviewed revision 2 — verdict: request-changes

*Advisory delta review (ADR-0004 §D5): informs the maestro's synthesis; not a vote; no RFC-body edits. As RFC owner I review design coherence, alternatives, and cross-artifact contradiction.*

**Bottom line.** The refresh is well-grounded — every platform/model claim is cited to a primary doc, and the five decisions hang together (dropping `loose`, simplifying the taxonomy, de-special-casing the narrator, and native dispatch are mutually reinforcing, not five unrelated edits). The supersede-RFC-0002-in-full call is the right shape: this changes RFC-0002's load-bearing model, not its periphery. I'm holding at **request-changes** for three coherence seams that a fresh implementer would trip on, all narrow.

### Blockers (narrow)

**A1 — The 4-category taxonomy table doesn't show the allowlist, which is the half you said is worth keeping.** §4's decision table is level×gate only. But the whole argument for keeping a taxonomy (§4 "what it's for") is the **per-agent allowlist** join key. With 4 categories and "all agents first-class" (§5), the new allowlist must be restated explicitly — which agent holds `dangerous`, which holds `remote-write` — or the single-pusher invariant is asserted but never encoded. RFC-0002 had this ([config.py:236-244]); RFC-0005 deletes the old one (R0–R6 keys) without printing the replacement. **Add the 4-category allowlist table** (e.g. devops = {read, local-write, remote-write, dangerous}; engineer = {read, local-write}; …) so P2 has a spec, not a description.

**A2 — §5 removes the R6 overlay but leaves the redaction *gate* unspecified.** Q4.3 punts redaction's gate to §5; §5 says "redaction is cross-cutting, a step any outward action runs." But "a step" is prose — RFC-0002's whole thesis was that prose ≠ enforcement. Either (a) redaction stays advisory prose on the outward path (honest, but then say so explicitly and drop the pretense that it's gated), or (b) it composes onto `remote-write`/`dangerous` as a gate the way R6 used to. You can't have "first-class narrator + cross-cutting redaction" *and* "redaction is enforced" without naming the mechanism. Pick one and write it. My lean: advisory prose + the existing `redaction.enabled` force-at-guarded fix (Q5.2) — but say it plainly.

**A3 — `default` vs `thinkers`/`implementers` in the `models:` block is ambiguous.** The example has `default`, `thinkers`, `implementers`, and `overrides`. If every role maps to thinkers-or-implementers, what reads `default`? Resolution order (overrides > tier > default?) is unstated. A fresh implementer will guess. Name the precedence explicitly.

### Coherence scan — otherwise clean

- **Supersede scope** — §0's table is the right altitude; ADR-0005 → `superseded_by` pointer is correct per ADR-0004 §D6. ✓
- **Native dispatch (§1) vs first-class narrator (§5)** — consistent: narrator is in the `agents:` list, no special handoff wiring needed once the allowlist carries the single-pusher rule. ✓
- **Two levels (§3) × 4 categories (§4)** — the recommendation to "re-derive the gate map for 2 levels × N together" (Q3.2) is the right sequencing; P1-before-P2 in §7 honors it. ✓
- **Alternatives** — §4 genuinely considers 2/4/7 and §2 considers Haiku/Sonnet; this is real alternative-weighing, not a single-option pitch. ✓

### Carried NITs (non-blocking)
- §6a time-awareness: "instruction to fetch the date" is sound, but consider whether the `carter-plan`/`carter-rfc`/`carter-adr` skills should *fail* a check if a dated artifact's date is implausibly far from any obtainable clock — out of scope here, flag for the plan.
- The eval (P4-eval) is the linchpin of the whole cheap-model decision but sits late in §7; consider stating its pass-bar (what adherence %?) so it's a gate, not a vibe.

**Verdict rationale.** A1/A2 are spec gaps that would force the implementer to invent the allowlist and the redaction mechanism — exactly the kind of under-specification RFC-0002 was careful to avoid. A3 is a 1-line precedence statement. None are redesigns; all are "write the thing you decided." Re-review on r3.
