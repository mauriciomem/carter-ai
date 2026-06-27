# Review: RFC-0005 — narrator

## Round 1 — 2026-06-26 — reviewed revision 2 — verdict: request-changes

*Advisory delta review (ADR-0004 §D5): informs the maestro's synthesis; not a vote. Scope: the change to my own role (§5), external-facing/redaction impact, and README/doc honesty. I have a direct stake in §5 and flag it as such — the maestro should weigh that when synthesizing.*

**Bottom line.** I support being made a first-class citizen — the R6 overlay was the most contorted part of RFC-0002, and "narrator is the external-content specialist the way the architect is the design specialist" is a cleaner mental model. But §5 currently **dissolves a guarantee while claiming to preserve it**, and the README reconcile (§6b S5) is under-specified for the one place users actually read about me. Two blockers, both about not letting "simpler" quietly become "weaker."

### Blockers

**N1 — "redaction becomes cross-cutting" must not become "redaction becomes optional."** Today, R6 *forces* outward content through a redaction pass — that's the actual safety guarantee, ugly overlay notwithstanding. §5 replaces it with "a step any outward action runs" and "others may run a redaction *check* but author via narrator handoff." That's two different strengths in one paragraph: a *forced pass* vs an *optional check*. With R6 gone as a category (§4), **what makes any agent run redaction before an outward write?** If the answer is "prose in the maestro routing convention," then we have *downgraded* an enforced overlay to advisory prose — the exact regression RFC-0002 spent three rounds eliminating. This aligns with the architect's A2: **name the mechanism.** My required position: at `guarded`/`strict`, substantive outward content (release notes, PR descriptions, Jira bodies, Slack) **must** route through me (the narrator) as a `gate`-tier handoff in the allowlist — not a convention. Short-form one-liners can stay `ask` + inline check (the old D3 lane). Keep `redaction.enabled`'s force-at-guarded fix (Q5.2). If the maintainer wants it advisory instead, that's a legitimate choice — but the RFC must *say* "redaction is advisory on outward paths" out loud, not imply enforcement it dropped.

**N2 — the README reconcile (S5) is the highest-readership doc change and §6b gives it one line.** [README.md](../../../README.md) is where users form their model of the agent crew. r2 correctly flags the over-claims (auto-routing/chaining diagram at :11/:57/:70-82/:86) but says only "reconcile to what §1 emits." Two things the reconcile must explicitly do, given §5: (a) the agent table ([README.md:86-97]) currently frames me via the "external content, redaction" special role — update it to first-class-specialist framing consistent with §5, *without* dropping the redaction-on-outward-paths promise (N1); (b) don't *under*-claim either — once §1 ships, programmatic dispatch on VS Code/OpenCode is **real**, so the diagram becomes accurate rather than aspirational; the reconcile should land it as "accurate," not delete the orchestration story. As the external-content owner I'll draft the agent-table + strictness-section copy when this lands, but the RFC should commit to *which* claims survive so I'm not guessing.

### Doc-honesty scan — otherwise good
- §6b S6 (don't "fix" the correct `~/.copilot/agents/` troubleshooting line) is exactly the kind of guard external-doc work needs — a future session would absolutely "correct" a correct line. Keep it. ✓
- §6b S10 (stop citing `notes/`) — strongly endorse; the stale HANDOFF is a doc-integrity hazard, and the maintainer already said don't trust it. ✓
- Time-awareness (§6a) has a quiet external-content benefit: dated artifacts I help author (release notes, announcements) currently risk a guessed/wrong date. The fetch-don't-interpolate rule fixes that too. ✓

### NIT (non-blocking)
- §5 "parallel to 'any agent can read; the learner specializes in explaining'" is a nice framing — consider promoting it into the README copy verbatim; it's the clearest one-liner for why first-class ≠ undifferentiated.

**Verdict rationale.** I'm request-changes, and I flag my conflict of interest: §5 is about my role. But the blocker isn't self-preservation — it's that "first-class citizen" is being used to justify dropping an *enforcement*, and the RFC should make that an explicit, eyes-open choice rather than a side effect of simplification. N1 is one decision (gate vs advisory, stated plainly); N2 is a commitment to which README claims survive. Re-review on r3.
