# Review: RFC-0006 — pm

## Round 2 — 2026-06-30 — reviewed revision 2 — verdict: approve

Re-confirm approve on r2. My P1 (phase the agent ahead of the server) is now structurally guaranteed by
§D-E's severance — the agent ships on this RFC, the server is a separate later ADR, so a slow server
decision can't hold the agent hostage. My P2 (skills are the long pole; gate the highest-stakes one) is
honored: the maintainer resolved OQ-C1 to ship `carter-pentest` in the first cut **merge-gated on the §D-G
boundary tests** — the gate governs the riskiest skill exactly as I wanted. The framework-cell entry-gate
(architect A2) is satisfied — cells are named to sub-category in the RFC, ready for the skill-authoring
plan. No remaining scope or sequencing concerns. Approve.

## Round 1 — 2026-06-30 — reviewed revision 1 — verdict: approve

*Scope + sequencing review (ADR-0004 §D5). Advisory, not a vote.*

**Bottom line.** Scope is well-bounded and the decisions are cleanly separable, which is what I care about most. The agent half is a single coherent unit; the new MCP server is correctly carved out as its own gated decision. I approve, with two sequencing recommendations the execution plan should bake in — neither blocks the RFC.

### Sequencing (recommendations for the plan, not blockers)

**P1 — phase the plan so the agent ships without waiting on the MCP server.** The agent (D-A through D-G, base `["github"]` scope) and the new server (D-E.2) have a clean dependency cut: the agent needs *nothing* from the server, but the server is useless without the agent. So the plan should be **two phases**: P-agent (roster + maps + agent body + skills + boundary tests — pure config, fast, low-risk) lands first and is independently shippable; P-server (the D-E.2 ADR + wiring) is a fast-follow gated on its own cost/security review. This matches the RFC's own D-E.2 gating and means a slow/uncertain server decision can't hold the agent hostage. The architect's A1 (make severability structural) is the same point from the design side — concur.

**P2 — the skills bundle is the long pole, not the wiring.** Wiring `carter-security` into the maps is an afternoon; authoring five real `SKILL.md` files (each genuinely useful, each citing its framework cell per the engineer/architect cell-precision ask) is the actual work. The plan should treat the **defensive core (4 skills)** as the must-have and **`carter-pentest`** as a distinct sub-item — so if the authorization-gate skill needs more review iterations (it's the highest-stakes one, §D-C), it doesn't block the four defensive skills from shipping. OQ-C1's "first cut vs fast-follow" is really a plan-sequencing question; I'd answer it *in the plan*: author all five, but gate `carter-pentest`'s merge on the boundary tests (§D-G) passing.

### Scope notes

- **No scope creep in the agent half** ✓ — every item maps to an existing precedent (allowlist like engineer, dispatch like all specialists, model tier like the thinkers, boundary like the maestro). Nothing bespoke.
- **The open-questions set is honest and small** ✓ — only OQ-E1 (which server) is genuinely load-bearing, and it's correctly pushed into D-E.2 rather than blocking the agent.
- **Hard entry-gate analog (RFC-0005 P2 precedent):** before the plan's skill-authoring phase starts, the **framework-cell mapping should be named to the sub-category** (architect A2) — that's the §D-F analog of RFC-0005's "allowlist table must be in the RFC before P2." Worth making a plan entry-gate.

**Verdict rationale.** The RFC is well-scoped, the decisions are separable, and the maintainer's three rulings are recorded as decisions. My only contributions are sequencing — phase the agent ahead of the server, treat the skills as the long pole — and those belong in the plan, not as RFC blockers. Approve at r1.
