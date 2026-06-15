# Review: RFC-0004 — architect

## Round 2 — 2026-06-15 — reviewed revision 3 — verdict: approve

Revision 3 resolves all four r1 findings, and the verification spike materially
improved the proposal's honesty.

- **B1 (blocking) — RESOLVED.** A vs B is no longer presented as independent. r3 adopts
  **A′** (single read-only server; writes via bash/`gh` under RFC-0002) and states the
  Copilot global-merge consequence explicitly. B is correctly held as the fallback iff a
  native MCP write path is needed (OQ4). Good.
- **B2 — RESOLVED.** Levers 3–6 now have homes; 7–8 explicitly declined in Decision.
- **B3 — RESOLVED.** P3/Decision now distinguish allowance-bounded (Copilot) vs
  marginal-from-zero (OpenCode); verification.md V1 carries the allowance figures.
- **B4 — RESOLVED, and then some.** §C.3 now carries a quantified go/no-go threshold —
  and V3 supplies the actual number (+68%), which is exactly the discipline I asked for.

**Why I'm approving rather than requesting more:** the spike did the one thing a design
review cannot — it *falsified the premise*. r3 reframes §C from a (false) token-shrink to
an honestly-priced security trade-off, and even offers "stay on archived" as a legitimate
outcome. That is the right shape. Remaining opens (OQ6 transport, V5 hop cost) are
implementation-gating, not design-blocking — correct to carry into the plan.

One non-blocking note for the ADR: make the headline finding unmissable — *"the official
GitHub MCP server costs 68–570% more tokens than the archived one; we adopt it for
security, not cost."* That sentence will stop a future session from "optimizing" by
swapping servers expecting a saving.

## Round 1 — 2026-06-15 — reviewed revision 2 — verdict: request-changes

Design is coherent, evidence-grounded, and well-separated from RFC-0002 (policy) and
RFC-0003 (credential scope). The r1→r2 billing correction is handled honestly. Four
findings before this can advance to `accepted`; one is **blocking**.

### B1 — BLOCKING: read-only default (option A) has no MCP write path on Copilot

§5.3 makes `GITHUB_READ_ONLY=1` the global default, and §5 sub-option **A** is "single
reduced global server." But Copilot wires MCP **globally** (the RFC itself establishes
this — `configure_mcp_servers`, flat merge, no agent dimension). A single global
read-only server therefore leaves **`devops`/`narrator` with no MCP write capability at
all** — the write opt-in §5.3 promises has nowhere to live under option A on Copilot.

So A and B are **not independent**: a read-only default *requires* a second write
instance (option B) to preserve any MCP write path, OR the RFC must explicitly accept
"**no MCP writes; writes go through the bash/`gh` path only**" (which then leans on
RFC-0002's bash gating, not this RFC). Pick one and state it:

- **A′** — single global **read-only** server + writes via bash/`gh` (simplest; MCP is
  read-only everywhere; document the bash dependency for devops/narrator), or
- **B** — `github-ro` + `github-rw` instances, write reachable only where per-agent
  frontmatter scoping applies (OpenCode/Copilot-CLI; not VS Code global merge).

The current "start with A, revisit B later" is under-specified because A-as-written
silently removes a capability. Resolve before plan.

### B2 — SHOULD-FIX: the broad levers (3–8) have no home after this RFC

The RFC is "broad analysis + narrow decision" by design — good — but levers 3, 4, 5, 6
are analyzed and then orphaned. Without an explicit destination they evaporate (the
exact drift this RFC fights). Recommend: on acceptance, Kei files levers 3–6 as
`.backlog`/follow-up items (or a tracked "future work" subsection), and 7–8 are recorded
as **declined** (already stated in Decision — good). Name the destination.

### B3 — SHOULD-FIX: "both token-metered" hides a unit-economics difference

True that both meters price tokens, but the **optimization incentive curve differs**:

- **Copilot AI Credits** = a *prepaid monthly allowance* (Pro 1,500 … Max 20,000). Below
  the allowance, token optimization buys **headroom + latency + accuracy**, not dollars;
  it only converts to **$** once you exceed the allowance and draw on budget.
- **OpenCode BYO-key** = **marginal $ from token zero** — every token saved is money saved
  immediately.

This nuance changes prioritization (on Copilot-below-allowance the case for levers 7–8 is
*even weaker*; the case for accuracy/latency from lever 1 is unchanged). Add one line to
P3 distinguishing **allowance-bounded** vs **marginal-from-zero** metering so a fresh
session doesn't over-rotate on Copilot dollar-savings that only exist past the allowance.

### B4 — SHOULD-FIX: add a quantified go/no-go threshold to V3

V3 says the MCP-schema number "justifies or kills §5" but gives no decision rule. The
Docker/remote prereq (OQ6) is a real cost; trading it for a trivial saving is a bad deal.
Add a threshold, e.g. *"proceed only if the official scoped+read-only server reduces the
GitHub tool-schema payload by ≥ N% (or ≥ M tokens/request) vs the archived server;
below that, the install-complexity cost outweighs the saving."* Pick N/M at review.

### Endorsements
- Scaffolder-vs-runtime framing correctly bounds scope — strong.
- No-overlap statement vs RFC-0002/0003 is accurate and necessary.
- Keeping the verification gate (V2–V3 mandatory) rather than declaring victory on the
  re-wire is the right discipline.

**To clear to `approve`:** resolve B1 (pick A′ or B), and address B2–B4 inline.
