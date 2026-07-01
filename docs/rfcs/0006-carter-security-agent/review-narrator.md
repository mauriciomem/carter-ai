# Review: RFC-0006 — narrator

## Round 2 — 2026-06-30 — reviewed revision 2 — verdict: approve

All three points resolved. **N1 (verbatim authorization line) — addressed:** §D-C now commits the exact
`<authorization>` block as copy (assist defensive / authorized-pentest / CTF / education; refuse
destructive / DoS / mass targeting / supply-chain / evasion; methodology only, never weaponized payloads),
and the §D-G test asserts that exact wording — no paraphrase-and-defer. **N2 (crew copy) — addressed:**
the Trade-offs section now commits the verbatim crew line ("any agent can flag a risk; carter-security
specializes in defensive review and *authorized* security methodology … advisory only … never a pusher")
— mirrors my RFC-0005 §6c precedent, doesn't overclaim, and won't be guessed downstream. **N3 (narrator
leg) — addressed:** §D-A.1 now names "security drafts → narrator redacts → devops transmits" for
*outward* findings, with internal-only docs exempt. The forced-redaction guarantee is preserved for
anything that leaves the workspace. Approve; I'm ready to draft the final body copy when this lands.

## Round 1 — 2026-06-30 — reviewed revision 1 — verdict: request-changes

*External-facing / redaction-impact review (ADR-0004 §D5). Triggered because the authorization posture (§D-C/§D-G) is outward-facing copy and the README crew description changes. Advisory, not a vote.*

**Bottom line.** The authorization framing is the most outward-facing thing this RFC produces — it's the line a user reads when the agent refuses, and the line the project is judged on if someone audits Carter's security posture. The design is right (defensive-by-default, explicit gate, test-asserted). Two blockers on *how the posture is worded and where it's stated*, because a dual-use security posture is exactly the kind of copy that must be precise, not paraphrased.

### Blockers

**N1 — the authorization line must be quoted verbatim and committed as the copy, not described.** §D-C describes the assist/refuse posture ("assist defensive / authorized-pentest / CTF / education; refuse destructive/DoS/mass-targeting/supply-chain/evasion") but §D-G item 1 then asks the *test* to grep for it — so the exact wording is simultaneously load-bearing (it's the gate, it's tested) and unwritten (no canonical string in the RFC). This is the §D-G/§D-C seam where the engineer (E1) and I converge: **commit the verbatim authorization block in the RFC** (or commit that the agent body owns it and the test asserts *that* body). The narrator's standing rule applies — outward content whose exact words matter (a refusal posture is exactly that) shouldn't be reconstructed downstream from a paraphrase. I'll draft the block when this lands; the RFC should reserve that the wording mirrors the Carter harness line **verbatim**, not "in posture."

**N2 — the README crew description needs a committed framing, the way RFC-0005 §6c committed the narrator-table copy.** The RFC's Trade-offs line says it touches "`README.md` (crew)" but doesn't say *what the crew copy claims*. The crew line for `carter-security` must say three things precisely and **not overclaim**: (a) **defensive-by-default, advisory** — it reviews and threat-models, it does not run attacks; (b) **authorized-only** for any offensive methodology, with the gate stated; (c) **does not push** — remediation is a handoff to devops (the single-pusher promise, identical to how the narrator line was reframed in RFC-0005 §6c without dropping the redaction promise). Commit this framing in the RFC so the crew copy isn't guessed. Candidate one-liner, parallel to RFC-0005's narrator line ("any agent can draft; the narrator specializes in redacted outward content"): **"any agent can flag a risk; carter-security specializes in defensive review and *authorized* security methodology — advisory only, never a pusher."**

### Redaction / external notes

- **The untrusted-input boundary (§D-G item 2) is also a redaction-adjacent guarantee** ✓ — a security agent that reads a leaked-secret payload and *reports* it must treat that content as data, and any *outward* report of a finding (a PR description, an advisory writeup) is substantive outward content that routes through **me** (the narrator redaction handoff, ADR-0010 D5) before devops transmits. The RFC's handoff-to-devops flow (§D-A.1) is correct but should name the **narrator** leg for *outward* findings: security drafts → narrator redacts → devops transmits, for anything that leaves the workspace. Right now §D-A.1 jumps security→devops; for outward content the redaction leg is mandatory.
- **No new redaction category** ✓ — security findings ride the existing outward-content handoff, no new taxonomy entry (consistent with ADR-0010 dropping R6).

**Verdict rationale.** N1 and N2 are both "commit the outward-facing words in the RFC, don't paraphrase-and-defer" — the discipline RFC-0005 §6c established for exactly this kind of copy. The design is sound; the gap is that the most-read words (the refusal posture, the crew line) aren't pinned. Both are one committed block each, and I'll draft them. The one design addition: name the **narrator leg** for *outward* findings (§D-A.1), not just security→devops. Re-review on r2.
