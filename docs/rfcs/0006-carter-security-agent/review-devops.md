# Review: RFC-0006 — devops

## Round 2 — 2026-06-30 — reviewed revision 2 — verdict: approve

Both r1 blockers resolved, and resolved the *right* way — by severing, not by hand-waving. **D1
(measured cost) — addressed:** §D-E now makes "a *measured* tool-schema token figure" a hard gate the
D-E.2 ADR must clear before the server ships (with the RFC-0004 3,963/6,650/13,977 precedent cited and
"value is triage, **not** savings" stated). That's the ADR-0008 discipline. **D2 (one shape) — addressed:**
§D-E now explicitly picks the **read-only CVE/SCA feed (public, no-auth preferred)** as v1 and carves the
**SAST *runner*** out as a separate, heavier "closer to a CI job, may not belong in MCP" decision — exactly
the split I asked for. The whole server is severed to its own ADR in the plan-003 lineage (OQ-E2), so it
ships on its own measured authority, not this RFC's. The agent half remains infra-clean and the
single-pusher monopoly is untouched. Approve.

## Round 1 — 2026-06-30 — reviewed revision 1 — verdict: request-changes

*CI/CD + infra + cost + credential-path review (ADR-0004 §D5). Triggered by §D-E (a new MCP server). Advisory, not a vote.*

**Bottom line.** The agent half is infra-free — no deploy, no CI change beyond test rows. My whole review is §D-E, the new SAST/SCA/CVE MCP server, which is squarely devops/infra territory. The RFC handles it more honestly than most ("propose but gate behind its own ADR-0008-style review") — but two cost/credential blockers, because a new MCP server is exactly the surface ADR-0008 spent a whole RFC getting right.

### Blockers

**D1 — the cost accounting must follow ADR-0008's "separate cost from security" rule explicitly, and the RFC half-does.** ADR-0008's load-bearing lesson was that swapping/adding an MCP server **costs** tokens (the official GitHub server was +68%) and the "it'll save tokens" premise was *falsified by measurement*. §D-E's table says "it costs tokens; its value is triage capability, not savings" — good, that's the right framing. But it asserts the cost with no number. The D-E.2 ADR **must** carry a measured tool-schema token count for the chosen server (like RFC-0004 §V3 measured 3,963 vs 6,650 vs 13,977), because a verbose SAST server could be the single largest per-request surface in a security workspace. Commit in the RFC that **D-E.2 carries a measured token figure**, not a hand-wave — otherwise we repeat the exact mistake ADR-0008 documented.

**D2 — "read-only SAST/SCA" is doing two very different infra jobs and the RFC blurs them.** An **SCA/CVE feed** (query OSV, look up a CVE, read an advisory) is a lightweight read-only API — the natural, low-risk fit, often **no credential** (public OSV/CVE), and it inherits ADR-0008's posture cleanly. A **SAST runner** (static analysis of source) is a *different animal*: it needs the code mounted, real compute, a Docker image that runs an analyzer, and it's effectively a build step, not a read API. The RFC's "SAST/SCA/CVE" label collapses these. **The D-E.2 review should pick ONE shape first** — my strong lean: a **read-only CVE/SCA feed (public, no-auth)** as the v1 server, and treat a SAST *runner* as a separate, heavier decision (it's closer to a CI job than an MCP read-server, and may not belong in MCP at all). Naming the shape matters because the transport, credential, and cost answers are completely different between them.

### Infra notes (non-blocking)

- **Transport / Docker digest-pin** ✓ — inheriting ADR-0008 D2 (Docker, image pinned by digest, remote-HTTP fallback) is correct and I'd hold D-E.2 to it.
- **Opt-in (ADR-0008 D1) is the cost backstop** ✓ — a GitHub-only workspace that doesn't select the security server pays zero tool-schema tokens for it. The RFC notes this; the D-E.2 ADR should make the server **opt-in by default**, not wired globally.
- **OQ-E2 is the right call** — the D-E.2 review belongs **inside the plan-003 (`mcp-cost-and-security`) lineage**, not a parallel track, so the cost accounting stays consistent with ADR-0008. I'd make landing it there a hard requirement, not an open question.
- **Single-pusher unaffected** ✓ — `carter-security` holds no `remote-write`/`dangerous`; nothing about it touches my pusher monopoly. Remediation it recommends is a handoff to me (devops), which is the correct flow.

**Verdict rationale.** D1/D2 are both "a new MCP server is a cost+credential+infra decision, treat it like ADR-0008 did, with measurement and a single chosen shape." The agent itself I'd approve today. The new server should not ship on this RFC's authority — gate it behind a measured D-E.2 ADR in the plan-003 lineage. Re-review on r2.
