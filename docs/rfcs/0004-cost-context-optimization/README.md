---
id: RFC-0004
status: accepted              # draft | review | accepted | rejected | withdrawn
revision: 3
created: 2026-06-14
decided: 2026-06-15
author: mauriciomem
adr: ADR-0008
plan: 003-mcp-cost-and-security
supersedes: []
tags: [cost, tokens, context, mcp, performance, harness, billing]
---

# RFC-0004: Cost & context optimization — measure before cutting

**Status:** Accepted
**Revision:** 3
**Author:** mauriciomem

> **Revision 3 (2026-06-15) — verification ran; §5 premise falsified, now reframed.**
> The §4 spike measured the GitHub MCP tool-schema token weight ([verification.md](verification.md),
> V3). Result inverts r2's §5: the **archived** server is the **leanest** (26 tools,
> ~3,963 tok); the **official** server's schemas are ~4× more verbose per tool, so
> migrating *increases* the surface at every useful tool count (surgical 10-tool
> read-only = ~6,650 tok, **+68%**; scoped+read-only = ~13,977, **+253%**). “Swap to
> official to *shrink* the surface” is **false** — the swap is a token **cost**, justified
> only by **security** (real write-tool removal via `--read-only`) and **maintenance**
> (reference server is archived). §5 is reframed from a token-shrink play to an explicit
> security/maintenance trade-off. Also resolves architect B1 (read-only write-path),
> engineer B1–B4 (transport, installer shape, V3 method, bash bypass). r2→r3 diff in git.

> **Fresh-session grounding (read first).** This RFC answers *"is it worth continuing to
> optimize Carter for token/cost, and where?"* — self-contained to prevent drift.
> Two verified findings: **(1)** both harnesses (Copilot AI Credits + OpenCode BYO-key)
> are **token-metered**, so token reduction lowers cost on both [B1]. **(2)** The largest
> Carter-controlled surface (MCP tool schemas) is *already at its floor* on the archived
> GitHub server; moving to the official server **costs** tokens, buying security +
> maintenance instead ([verification.md](verification.md)). Net: the highest-leverage
> *token-cost* lever is **not** the GitHub-server swap — it is **MCP server opt-in**
> (don't ship terraform/atlassian schemas a workspace never uses; §Part A lever 2) plus
> avoiding the official server's bloat. The GitHub swap is a **security** decision priced
> honestly here, not a cost win.

## Summary

Carter is a **scaffolder, not a runtime**: it emits static agent/skill/MCP files and
exits ([carter/resources.py](../../../carter/resources.py); [ADR-0005](../../adr/0005-risk-based-strictness-policy.md)).
It can only influence the **static payload** it ships (agent system prompts, skill
bodies, instructions, MCP tool schemas). Every *runtime* cost lever — compaction,
KV-cache management, tool-result clearing, just-in-time retrieval, subagent summary
distillation — is owned by the **harness** (Copilot / OpenCode), not by Carter.

This RFC (a) establishes the cost model per harness — **both token-metered** (Copilot AI
Credits [B1], OpenCode BYO-key); (b) **ran** the verification spike, which measured the
MCP tool-schema weight and **falsified** the original "swap to shrink" premise
([verification.md](verification.md)); and (c) reframes the narrow decision: the GitHub
server swap is a **security/maintenance** change that *costs* tokens (priced honestly
here), while the real *token-cost* win is **not shipping MCP schemas a workspace doesn't
use**. It closes a security gap [RFC-0002](../0002-risk-based-strictness-policy/) flagged,
without pretending to be a cost optimization it is not.

## Problem

### P1 — Verified current state (grounding facts)

| Claim | Reality | Evidence |
|---|---|---|
| Carter can manage runtime context | It is a scaffolder; emits files then exits | [carter/resources.py](../../../carter/resources.py); [ADR-0005](../../adr/0005-risk-based-strictness-policy.md) |
| GitHub MCP server is the maintained one | Ships the **archived** `@modelcontextprotocol/server-github` | [mcp/copilot/github.json](../../../mcp/copilot/github.json), [mcp/opencode/github.json](../../../mcp/opencode/github.json) |
| Official server would shrink the token surface | **FALSE** — official schemas ~4× more verbose/tool; swap *adds* tokens (V3) | [verification.md](verification.md) V3 |
| Archived server is wastefully large | **FALSE** — it is the leanest useful config (~152 tok/tool) | [verification.md](verification.md) V3 |
| MCP servers are scoped per agent | Wired **globally**; hardcoded triple, flat-merged | `configure_mcp_servers` (`carter/installer.py` ~L786), `["github","terraform","atlassian"]` |
| Per-agent MCP scope is unused | Modeled in config but never shrinks the surface | `AGENT_MCP_SCOPE` (`carter/config.py` ~L293) |
| `--mcp` gates everything MCP | Gates **server defs** only; agent files install always | `installer.py` ~L1115 vs ~L1106 |

### P2 — Measured static token footprint (bytes/4; real tokenizers run ~10–15% higher)

| Surface | Load timing | Tokens |
|---|---|---|
| One agent system prompt | on `@`-mention / delegation | 437–1,290 (maestro 1,162; narrator 1,290) |
| All 7 agents | (never all at once) | ~4,908 |
| `copilot-instructions.md` | auto-loaded every request | ~535 |
| **All 23 skill descriptions** | **always-on (router sees these)** | **~660** |
| Skill *bodies* (avg ~1,100; max golang 2,148) | **on-demand only** | 25,927 if all loaded |
| Skill sub-reference files (11) | **lazy — only when needed** | ~12,705 |

**Carter's per-request static cost ≈ 1.6k–2.5k tokens** (one agent + instructions +
skill descriptions). This is *small* and already follows progressive-disclosure best
practice [A1]. The MCP tool schemas are a **larger** per-request surface than all of
Carter's prose: the archived GitHub server alone is ~3,963 tok (V3), and terraform +
atlassian add more on top when wired — which is why **not shipping unused MCP servers**
(Part A lever 2) outweighs trimming prose (levers 7–8).

### P3 — Both harnesses are now token-metered (cost models converged)

| | **GitHub Copilot** (AI Credits) | **OpenCode** (BYO key) |
|---|---|---|
| Billing unit | **tokens** → AI Credits (1 credit = $0.01) [B1] | raw input + output **tokens** |
| Do input tokens cost more? | **Yes** — cost = model × tokens [B1] | **Yes** — linear |
| Tool calls / subagent hops cost? | **Yes** — agentic features = multiple model calls, "consume significantly more" [B1] | **Yes** — each hop re-sends context |
| Cached tokens? | **Priced explicitly** (input/output/cached) [B1] → KV-cache hygiene matters | **~10×** cheaper cached prefix [A2] |
| What lowers cost | fewer **tokens**; fewer hops/retries; cheaper model (10% auto-select discount); cache reuse | fewer **tokens**; stable cacheable prefix; fewer hops |

> **Resolved (r2): the meter converged.** The legacy request-metered model (1 prompt =
> 1 premium request, tool calls free) is **superseded** for usage-based plans [B1].
> Copilot AI Credits price *tokens* (input + output + cached) × model rate, exactly
> like OpenCode. The Copilot column **is** the OpenCode column now. Consequence: every
> token lever (MCP surface, cache hygiene, fewer hops, leaner prose) cuts real money on
> **both** harnesses — §4 now measures *how much*, not *whether*.

## Decision driver: the question to answer first

**Resolved in r2:** token volume *does* cost real money on both harnesses (Copilot AI
Credits [B1]; OpenCode BYO-key). The remaining question is **magnitude** — *how many
tokens (and credits) does the current MCP tool surface cost, and how much does the §5
re-wire save?* §4 stays a **prerequisite gate**, but it now measures the saving (V2/V3)
rather than the billing class; no §5 implementation is approved until V2–V3 carry real
numbers.

## Proposal

### Part A — Broad analysis: the lever inventory (ranked)

| # | Lever | Wins on | Effort | Payoff |
|---|---|---|---|---|
| 1 | **MCP servers opt-in per workspace** (don't ship terraform/atlassian schemas if unused) | **both $**, both latency, accuracy | S | **Highest** — the real token win |
| 2 | **Reduce agent hops + retries** (tighter specs, TDD-first, sharper routing) | **both $** | M | High |
| 3 | **Model choice discipline** (trivial→cheaper model; reserve frontier; 10% auto-select discount) | **both $** | S | High |
| 4 | **GitHub server swap → official + surgical `--tools` + `--read-only`** | **security**, maintenance (NOT tokens — *costs* +68% min, V3) | M–L | Security only |
| 5 | KV-cache hygiene (byte-stable install output; stable→volatile ordering) | **both $** (cached tokens priced [B1]), latency | S | Medium |
| 6 | Per-agent MCP minimisation (read agents get fewer tools) | both $, accuracy, security | M | Medium (limited by Copilot global merge) |
| 7 | Light trim of maestro/narrator prose *iff* redundant | both $ (small) | S | **Low** |
| 8 | General shrink of skill bodies / agent prose | both $ (marginal) | M | **Low — skip** |

**Lever 1 (MCP opt-in) is now the highest-leverage token win** — verification showed the
GitHub-server swap (old lever 1, now lever 4) *adds* tokens, so it drops to a
security-only justification. Levers 7–8 stay **deprioritized**: Carter's prose is near
the good part of the curve and over-trimming trades accuracy for marginal tokens
(Anthropic's *"minimal ≠ short"* failure mode [A1]).

### Part B — Verification Protocol — RAN 2026-06-15 ([verification.md](verification.md))

V1–V4 executed; V5 deferred. The MCP measurement (V3) **falsified** the original §5
"swap shrinks the surface" premise, which is why Part C below is reframed.

- **V1 — Billing magnitude.** Class = token-metered AI Credits [B1] (settled). Per-model
  credit rates not yet captured (needs live dashboard). **Open, non-blocking.**
- **V2 — Static baseline.** Re-confirmed unchanged from P2. **Done.**
- **V3 — MCP schema cost (decisive).** Serialized schema bytes/4, 6 configs. Archived =
  **3,963 tok** (leanest useful, ~152 tok/tool); official surgical read-only =
  **6,650 (+68%)**; official scoped+read-only = **13,977 (+253%)**; official default =
  **26,537**. **The swap costs tokens at every useful tool count.** **Done.**
- **V4 — Transport.** Archived `npx`-stdio and official `docker`-stdio both start + list
  tools on this host; official adds a **Docker prereq**. Remote-HTTP + per-target
  `carter install` wiring not yet exercised. **Partial.**
- **V5 — Hop cost.** Not instrumented (needs live harness tracing). **Deferred / open.**

### Part C — Narrow decision: GitHub MCP server swap as a SECURITY trade-off (not a token cut)

> **Reframed in r3 from the evidence.** V3 proves migrating to the official server
> *increases* tokens. So this is **not** a cost optimization — it is a **security +
> maintenance** decision, priced honestly. Pure token-minimisation argues to **keep the
> archived server** (it is the floor); the counter-argument is that it is
> **archived/unmaintained** and exposes all 26 tools (incl. writes) with **no read-only
> switch**. The decision is which risk to carry, with eyes open.

Scope: **GitHub MCP server only**; terraform/atlassian are out of scope here (their
token cost is addressed by **lever 1 — opt-in**, not a server swap).

**Resolved sub-option (architect B1 + engineer B2).** Options A and B from r2 are not
independent: under Copilot's **global** MCP merge a single read-only server leaves
`devops`/`narrator` with **no MCP write path**. Two coherent shapes remain:

| | **A′ — single read-only server; writes via bash/`gh`** | **B — `github-ro` + `github-rw` instances** |
|---|---|---|
| MCP surface | read-only everywhere (~6,650 tok surgical) | ro for most; rw only where per-agent frontmatter scopes it |
| Writes | through the shell/`gh` path, governed by **RFC-0002** bash gating | native MCP write tools for devops/narrator |
| Copilot global-merge fit | yes (one server) | only via per-agent frontmatter (not VS Code global merge) |
| Token cost | lowest official option | rw instance adds its write-tool schema where wired |
| Complexity | low | higher (two defs; per-agent `tools:`/`mcp-servers`; uninstall list) |

**Recommendation: A′** — single official server, **surgical `--tools` read-only** (the
~6,650-tok config, V3), MCP writes disabled, shell/`gh` writes left to RFC-0002's bash
gate. Lowest token cost of the official options, simplest installer change, and the
MCP write surface (an accidental-write vector) genuinely shrinks. Adopt **B** only if a
native MCP write path proves necessary for devops/narrator.

**Concrete change (A′):**
1. Replace `@modelcontextprotocol/server-github` with official `github/github-mcp-server`
   (Docker `ghcr.io/github/github-mcp-server`; remote-HTTP as the Docker-free fallback,
   pending V4 completion) in [mcp/copilot/github.json](../../../mcp/copilot/github.json)
   and [mcp/opencode/github.json](../../../mcp/opencode/github.json) [G1].
2. Set `GITHUB_TOOLS` to Carter's real read-only need (V3 set: `get_me, get_file_contents,
   search_code, search_repositories, list_commits, get_commit, pull_request_read,
   issue_read, list_issues, list_pull_requests`) **+** `GITHUB_READ_ONLY=1`. Prefer
   surgical `--tools` over `--toolsets` (V3: 10 surgical tools = 6,650 vs 24 scoped = 13,977).
3. **Go/no-go threshold (architect B4):** proceed only if the security value (write-tool
   removal + maintained server) is judged worth the **measured +~2,700 tok/request**
   (+68%) cost. If not, **stay on the archived server** and record that as the decision.
4. **Bash bypass clause (engineer B4):** read-only removes the **MCP** write surface
   only; shell `gh`/`git`/`terraform` writes against the same token remain governed by
   **RFC-0002**, not this RFC. State this in the agent docs so "read-only" is not misread
   as "cannot write."
5. **Transport gate (engineer B1):** before coding, finish V4 — prove the chosen
   transport (Docker vs remote-HTTP) wires through `carter install` on **both** copilot
   and opencode targets. The installer change (engineer B2) and the test updates
   (engineer B5: MCP-wiring asserts + hardcoded server list at `installer.py` ~L786/~L948)
   are explicit plan tasks, not discoveries.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Lever 1 (MCP opt-in) + A′ GitHub swap (this RFC)** | Opt-in is the real token win; GitHub swap buys security honestly | Two distinct changes; GitHub swap *costs* tokens (accepted for security) |
| **Swap GitHub server to “shrink tokens” (r2 premise)** | — | **Falsified** — official server *adds* +68% to +570% tokens (V3); rejected as a cost play |
| **Aggressively trim all prompts/skills now** | Saves a little on both meters | Low leverage vs MCP surface; risks accuracy (*minimal≠short* [A1]); high effort |
| **Keep archived server, add nothing** | Zero effort; already the token floor | Ships an **archived/unmaintained** server with no read-only switch — a standing security/maintenance risk |
| **Switch default harness to optimize billing** | Could pick the cheaper meter | Out of scope; product decision, not a Carter-config change |

## Trade-offs / Impact

- **Touches:** [mcp/copilot/github.json](../../../mcp/copilot/github.json),
  [mcp/opencode/github.json](../../../mcp/opencode/github.json), the hardcoded server
  list in `configure_mcp_servers` (`carter/installer.py` ~L786) **and its uninstall
  twin** (~L948), and tests asserting MCP wiring (engineer B5). `AGENT_MCP_SCOPE`
  (`carter/config.py`) only for sub-option B.
- **The GitHub swap is a net token COST** (+~2,700/request surgical read-only, V3),
  accepted in exchange for security (write-tool removal) + a maintained server. It is
  **not** filed as a cost optimization. The token *win* is lever 1 (MCP opt-in).
- **Official server adds a Docker dependency** (or remote-HTTP + OAuth/PAT) vs the
  current `npx` server — a real install-prereq trade-off (engineer B1 / OQ6), gated on
  V4 completion before implementation.
- **"Read-only" is MCP-surface only.** Shell `gh`/`git`/`terraform` writes against the
  same token are out of scope here and remain governed by RFC-0002 (engineer B4).
- **Relationship to neighbours (no overlap):** RFC-0002 = *policy/enforcement* (incl.
  the bash path); RFC-0003 = *credential blast radius (scoped tokens)*; **RFC-0004 =
  *token/context cost & MCP tool surface*.** §C shrinks the *exposed MCP write surface*;
  it does **not** replace RFC-0003's credential scoping. RFC-0004 partially advances
  RFC-0002's accepted "drop false read-only" and does not supersede either.

## Open questions

- **OQ1 — Billing magnitude (class resolved, magnitude open).** Class = token-metered
  (AI Credits [B1]). Open: per-model token→credit rates for the plan in use, to price
  lever 1's saving and §C's cost in $ (V1).
- **OQ2 — Tool minimum.** Is the V3 10-tool read-only set the right Carter footprint, or
  do some agents need more/fewer? Audit actual tool usage across agents/skills.
- **OQ3 — Hop cost.** How many extra tokens does a maestro multi-agent chain add per
  task (each hop re-sends + regenerates context)? (V5, deferred.)
- **OQ4 — A′ vs B.** Does any workflow genuinely need a **native MCP** write path
  (forcing B), or is shell/`gh` writing (A′) sufficient for devops/narrator?
- **OQ5 — terraform/atlassian opt-in.** Confirm lever 1 mechanics: does skipping their
  servers per workspace cleanly remove their schema cost, and what is each server's
  weight? (Generalises the token win; independent of the GitHub swap.)
- **OQ6 — Transport.** Docker vs remote-HTTP for the official server, wired through
  `carter install` on both targets (V4 completion) — and is the prereq acceptable for
  Carter's install UX, or is a fallback needed?

## Decision

**Accepted 2026-06-15** (reviews: architect approve, engineer approve — both Round 2 /
revision 3). Records → [ADR-0008](../../adr/0008-mcp-cost-and-security.md); executed by
plan `003-mcp-cost-and-security`. The verification gate (§4) ran and inverted the r2
premise, so the decision splits:

- **Token win — adopt lever 1 (MCP server opt-in).** Carter installs only the MCP
  servers a workspace selects; unused servers add zero tool-schema tokens. The real
  cost lever.
- **GitHub server swap (§C) — adopt A′ as a SECURITY decision.** Replace the archived
  server with the official `github/github-mcp-server` via **Docker** (digest-pinned),
  **read-only** with a surgical `--tools` allowlist. **Security is preferred over token
  cost here** (user decision): accept the measured **+68%** GitHub-server token cost for
  a maintained server + MCP write-tool removal. GitHub writes go via the shell/`gh` path
  under RFC-0002. **B (ro/rw instances) is dropped.**
- **Round-trip guardrails — adopt the low-effort half of levers 2–3.** Reinforce
  spec/TDD-first to cut **retry loops**, and usage-doc guidance to cut **redundant**
  hops. **Defer** the Maestro delegation-economy rule (driver 1).
- **Transport — Docker** (proven V4); remote-HTTP documented as the no-Docker fallback.
- **Declined / deferred:** prose-trim levers 7–8 (skip unless an obvious win appears);
  terraform/atlassian opt-in measurement (OQ5, follow-up); model-choice automation; V5
  hop-cost measurement; per-agent MCP minimisation (lever 6).

---

### References

- [A1] Anthropic — *Effective context engineering for AI agents* (2025): minimal-but-
  sufficient context; *"minimal ≠ short"*; bloated tool sets degrade tool choice.
  <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- [A2] Manus — *Context Engineering: Lessons from Building Manus* (2025): KV-cache hit
  rate as the dominant cost/latency metric; ~10× cached vs uncached; tool defs sit at
  the cache-sensitive prefix. <https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus>
- [B1] GitHub Docs — *Usage-based billing for individuals* (current, 2026): Copilot
  bills **GitHub AI Credits**; "interaction consumes tokens: input, output, and cached…
  each token priced by model"; cost = model × tokens; 1 credit = $0.01; agentic features
  "consume significantly more"; allowances Pro 1,500 / Pro+ 7,000 / Max 20,000; 10%
  auto-model-selection discount. <https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals>
  · Superseded legacy request-metered model (grandfathered annual plans only):
  <https://docs.github.com/en/copilot/concepts/billing/copilot-requests>
- [G1] GitHub — *github/github-mcp-server* (`--toolsets`, `--tools`, `--read-only`;
  default = context,repos,issues,pull_requests,users; toolset scoping reduces context
  size). <https://github.com/github/github-mcp-server>
