# Review: RFC-0006 — architect

## Round 2 — 2026-06-30 — reviewed revision 2 — verdict: approve

Both r1 blockers resolved. **A1 (severability) — fully addressed:** §D-E now opens with a bolded
"Accepting RFC-0006 accepts the agent + base `["github"]` scope — and *nothing* about the new server …
the agent is complete and shippable without it" callout, and the server is a separate later ADR in the
plan-003 lineage. That is exactly the structural severance I asked for, not an inference. **A2 (framework
cells) — addressed:** §D-F now names cells to sub-category (NIST CSF ID.RA/DE.CM/RS.AN/RS.MI/RC.RP, OWASP
ASVS V1/V5/V6 + Top 10 A01/A03/A08, ATT&CK TA0001–TA0011 via D3FEND) — the precision the house style
requires. The design notes (OQ-A1 closed to security→devops; pentest in first cut) were resolved by the
maintainer as I leaned. No remaining concerns; the agent design is coherent and consistent with
ADR-0010/0011/0008. Approve.

## Round 1 — 2026-06-30 — reviewed revision 1 — verdict: request-changes

*Design-coherence + alternatives review (ADR-0004 §D5): the architect reviews every RFC. Advisory, not a vote — informs the maestro synthesis before the maintainer decides.*

**Bottom line.** The 8th-agent design is coherent and correctly built *on* ADR-0010/0011 rather than re-opening them — every emission is a value for an existing map, no new machinery, exactly right. §D-A justifies the agent over skills convincingly (routing target + tested boundary + distinct posture is real, not ceremony). Two blockers, both on §D-E (the new MCP server), and one design note.

### Blockers

**A1 — §D-E couples two decisions of very different risk into one RFC, and the coupling is load-bearing.** Everything except D-E is a pure config-map addition with a tiny, well-understood blast radius. D-E introduces a **new token surface + credential path** whose actual shape (OQ-E1) is undecided. The RFC handles this honestly (D-E.2 gates it behind its own ADR-0008-style review) — but it should go one step further and make the **split structural**: the *agent* (D-A through D-G minus the new server) should be acceptable and shippable **without** D-E. As written, a reader could accept "RFC-0006" and think the server is approved. State explicitly: **accepting this RFC accepts the agent and the *base* `["github"]` scope; the new server is a separate ADR that may land later or never, and the agent is complete without it.** Right now §D-E.1 says "base scope (no new decision)" then immediately proposes the server — make the severability a first-class sentence, not an inference.

**A2 — the framework-cell mapping (§D-F) is asserted, not grounded.** §D-F maps each skill to a NIST CSF / OWASP / ATT&CK cell, which is the whole point of mirroring the reference repo's structure — but the RFC cites the framework *home pages*, not the specific cells. For an RFC whose stated value is "every skill cites which framework cell it serves," the cells should be named to the sub-category (e.g. NIST CSF 2.0 **ID.RA** for threat-model, **DE.CM**/**RS.AN** for vuln-triage), or the precision claim is aspirational. This is a doc-grounding gap, not a design flaw — but it's the kind the house style (cite the cell, not the framework) exists to catch. Resolve in r2 or explicitly defer the cell-precision to the skill-authoring plan.

### Design notes (non-blocking)

- **§D-A.1 vs OQ-A1 tension.** Granting `local-write` so the agent can *author* a findings doc, then handing the *filing* of that doc to devops, is the right shape — but OQ-A1 half-asks whether pm should own the filing. It shouldn't be open: security drafts → devops transmits is the exact narrator→devops precedent (D5), and pm owns *plan* docs, not security findings. I'd close OQ-A1 in favor of the devops handoff and drop the pm alternative.
- **§D-C / OQ-C1.** Shipping `carter-pentest` in the first cut so the authorization gate is exercised day one is the stronger call — a gate that ships untested-in-anger is a gate that rots. Concur with the lean.

**Verdict rationale.** A1 and A2 are both about *honesty of scope/precision*, the same discipline RFC-0005 earned its acceptance on. Neither is a redesign: A1 is one explicit severability sentence; A2 is naming cells (or deferring the precision with intent). The agent design itself is sound and I'd approve it the moment D-E is structurally severed and the cell mapping is either named or explicitly deferred. Re-review on r2.
