---
id: RFC-0004
status: accepted              # draft | review | accepted | rejected | withdrawn
revision: 4
created: 2026-06-14
decided: 2026-06-15
updated: 2026-07-06
author: mauriciomem
adr: ADR-0008
plan: 003-mcp-cost-and-security
supersedes: []
tags: [cost, tokens, context, mcp, models, performance, harness, billing]
---

# RFC-0004: Cost & context optimization — measure before cutting

**Status:** Accepted — lever 1 (model-tier discipline) scoped & sequenced first (r4);
r3 MCP decisions recorded but **not yet implemented** (plan 003)
**Revision:** 4
**Author:** mauriciomem

> **Revision 4 (2026-07-06) — reconciled against the code; the biggest cost lever
> shipped elsewhere and is unused.**
> A deep re-audit of the tree found three things the earlier revisions got wrong or
> could not have known:
>
> 1. **The r3 "Decision" was never executed.** Plan `003-mcp-cost-and-security` is still
>    `active` with **all six steps `pending`**. MCP servers are **still wired globally**
>    (`MCP_SERVERS = ("github","terraform","atlassian")`, `carter/install/mcp.py`), and
>    the GitHub server is **still the archived** `@modelcontextprotocol/server-github`
>    over `npx` with **no `--read-only` and no `--tools` allowlist** (`mcp/copilot/github.json`,
>    `mcp/opencode/github.json`). ADR-0008 is "Accepted" but **unimplemented**. r4 marks
>    this honestly instead of implying it is done.
> 2. **`AGENT_MCP_SCOPE` is no longer inert.** The P1 claim "per-agent MCP scope is
>    modeled but never shrinks the surface" is **stale**. `AGENT_MCP_SCOPE`
>    (`carter/config.py`) is now consumed by `policy_native_keys` and emitted as a
>    per-agent `tools: [carter-<server>/*]` allowlist on every VS Code/Copilot agent —
>    the surface *is* scoped per agent in the frontmatter. What is **not** scoped is the
>    **install** (all three servers are still wired regardless of per-agent scope).
> 3. **The real cost lever now exists — and RFC-0004 predates it.** Per-agent model
>    tiering (`models:` block, `MODEL_TIERS`, `resolve_model`) shipped on **2026-06-27**
>    via plan 005 / ADR-0010 — **13 days after** this RFC deprioritized "model choice
>    discipline" as a small-effort lever. **6 of 8 agents run Opus 4.8** today
>    (`thinkers` tier); only engineer/devops run Sonnet. On token-metered harnesses this
>    is the **largest recurring spend Carter controls**, and it is un-exploited. r4
>    promotes model-tier discipline to the top lever. r3→r4 diff in git.

> **Fresh-session grounding (read first).** This RFC answers *"is it worth continuing to
> optimize Carter for token/cost, and where?"* Verified findings as of **2026-07-06**:
> **(1)** Both harnesses (Copilot AI Credits + OpenCode BYO-key) are **token-metered**, so
> token reduction lowers cost on both [B1]. **(2)** Carter is a **scaffolder**: it controls
> only its static payload (agent prompts, skill bodies, MCP schemas) **and the model each
> agent binds to**. Runtime levers (compaction, cache, JIT retrieval) are harness-owned.
> **(3)** The two highest-leverage levers are (a) **model-tier discipline** — most agents
> do not need Opus; and (b) **MCP server opt-in** — don't ship schemas a workspace never
> uses. **Neither is implemented yet.** The GitHub-server swap is a **security** decision
> that *costs* tokens (priced honestly here), not a cost win.

## Summary

Carter is a **scaffolder, not a runtime**: it emits static agent/skill/MCP files and
exits ([carter/resources.py](../../../carter/resources.py); [ADR-0005](../../adr/0005-risk-based-strictness-policy.md)).
It shapes only the **static payload** (agent system prompts, skill bodies, instructions,
MCP tool schemas) **and the per-agent model binding**. Every *runtime* cost lever —
compaction, KV-cache management, tool-result clearing, just-in-time retrieval, subagent
summary distillation — is owned by the **harness** (Copilot / OpenCode), not by Carter.

This RFC (a) establishes the cost model per harness — **both token-metered**; (b) ran a
verification spike that **falsified** the original "swap the GitHub server to shrink
tokens" premise ([verification.md](verification.md)); and, in r4, (c) **reconciles the
decision against the code**: the r3 decisions were recorded but never built, and the
model-tiering machinery that shipped afterward makes **model-tier discipline the top
token lever** — bigger, simpler, and lower-risk than the MCP work.

## Problem

### P1 — Verified current state (audited 2026-07-06)

| Claim | Reality | Evidence |
|---|---|---|
| Carter can manage runtime context | No — it is a scaffolder; emits files then exits | [carter/resources.py](../../../carter/resources.py); [ADR-0005](../../adr/0005-risk-based-strictness-policy.md) |
| Most agents run the frontier model | **True — 6 of 8 on Opus 4.8** (`thinkers` tier); only engineer/devops on Sonnet | `MODEL_TIERS` ([carter/config.py](../../../carter/config.py)) |
| Per-agent model binding is configurable | **True** — `models:` block, `overrides > tier > default` | `resolve_model` ([carter/config.py](../../../carter/config.py)); `tests/test_models.py` |
| Model-tier discipline is exploited for cost | **False** — machinery exists; the default keeps 6/8 on Opus | `DEFAULT_CONFIG["models"]` |
| GitHub MCP server is the maintained one | **False** — ships the **archived** `@modelcontextprotocol/server-github` via `npx`, full write surface, no `--read-only` | [mcp/copilot/github.json](../../../mcp/copilot/github.json), [mcp/opencode/github.json](../../../mcp/opencode/github.json) |
| MCP servers are **installed** opt-in per workspace | **False** — hardcoded triple wired globally to every target | `MCP_SERVERS` ([carter/install/mcp.py](../../../carter/install/mcp.py)); `configure_mcp_servers` ([carter/installer.py](../../../carter/installer.py)) |
| Per-agent MCP scope is inert (r3 claim) | **Stale — now emitted** as per-agent `tools: [carter-<server>/*]` | `AGENT_MCP_SCOPE` + `policy_native_keys` ([carter/config.py](../../../carter/config.py)) |
| The r3 GitHub-swap + opt-in decision shipped | **False — plan 003 is `active`, all 6 steps `pending`** | `.carter/state/plans/active/003-mcp-cost-and-security/` |
| `--mcp` gates all MCP | Gates **server install** only; agent files (with their `tools:` scope) install regardless | `installer.py` (`--mcp` branch) |

### P2 — Measured static token footprint (bytes/4; real tokenizers run ~10–15% higher)

Counts refreshed 2026-07-06 (now **8 agents, 28 skills** — was 7/23 in r3).

| Surface | Load timing | Tokens (order of magnitude) |
|---|---|---|
| One agent system prompt | on `@`-mention / delegation | ~0.4k–1.3k |
| All 8 agents | (never all at once) | ~5k |
| `copilot-instructions.md` | auto-loaded every request | ~0.5k |
| **All 28 skill descriptions** | **always-on (router sees these)** | **~0.8k** |
| Skill *bodies* | **on-demand only** | ~26k+ if all loaded |
| Skill sub-reference files | **lazy — only when needed** | ~13k |
| **Archived GitHub MCP tool schema** | **per request when wired** | **~4.0k** (V3) |

> Re-run V2 for exact figures if a hard baseline is needed; the shape is unchanged
> from r3 (prose is lean, ~1.6k–2.5k per request), only the counts grew. The
> **MCP tool schema remains the largest single static surface**, and the **model
> binding — a per-request *rate multiplier* on all of it — is the largest cost lever.**

### P3 — Both harnesses are token-metered (cost models converged)

| | **GitHub Copilot** (AI Credits) | **OpenCode** (BYO key) |
|---|---|---|
| Billing unit | **tokens** → AI Credits (1 credit = $0.01) [B1] | raw input + output **tokens** |
| Do input tokens cost? | **Yes** — cost = model rate × tokens [B1] | **Yes** — linear |
| Tool calls / subagent hops cost? | **Yes** — agentic features "consume significantly more" [B1] | **Yes** — each hop re-sends context |
| Cached tokens? | **Priced explicitly** [B1] → cache hygiene matters | **~10×** cheaper cached prefix [A2] |
| **Model choice** | **Directly scales cost** (rate is per-model) [B1] | **Directly scales cost** |
| What lowers cost | cheaper **model**; fewer tokens; fewer hops; cache reuse | cheaper **model**; fewer tokens; stable prefix; fewer hops |

> The meter converged: Copilot AI Credits price *tokens* × *model rate*, exactly like
> OpenCode. Because the rate is **per-model**, the model each agent binds to is a
> **multiplier on every token that agent processes** — which is why r4 elevates
> model-tier discipline above the MCP prose/schema levers.

## Proposal

### Part A — The lever inventory (re-ranked r4)

| # | Lever | Wins on | Effort | Payoff | Status |
|---|---|---|---|---|---|
| 1 | **Model-tier discipline** — move agents whose work is well-structured off Opus → Sonnet/Haiku; reserve Opus for genuine frontier reasoning. Gate each downgrade with the **adherence eval** ([evals/adherence.py](../../../evals/adherence.py)). | **both $** (rate multiplier) | S | **Highest** | **machinery ships; unused** |
| 2 | **MCP server opt-in per workspace** — install only selected servers; unused servers add zero schema tokens. | **both $**, latency, accuracy | S–M | High | **not implemented** (plan 003 step 1) |
| 3 | **Reduce agent hops + retries** — tighter specs, TDD-first, sharper routing; one thinker decomposes, cheap implementers execute. | **both $** | M | High | partial (skills encode discipline) |
| 4 | **GitHub server swap → official + surgical `--tools` + `--read-only`** | **security**, maintenance (NOT tokens — *costs* +68% min, V3) | M–L | Security only | **not implemented** (plan 003 step 2) |
| 5 | KV-cache hygiene (byte-stable install output; stable→volatile ordering) | **both $**, latency | S | Medium | partial |
| 6 | Per-agent MCP **install** minimisation (install scope follows `AGENT_MCP_SCOPE`, not just frontmatter) | both $, accuracy, security | M | Medium | frontmatter done; install not |
| 7 | Prose trim of agents/skills | both $ (marginal) | M | **Low — skip** | — |

**Lever 1 (model-tier discipline) is the new top lever.** It is a config-only change
(`MODEL_TIERS` / `models` in `carter.yaml`), it multiplies cost on *every* token an
agent touches, and Carter already has the **eval instrument to prove a downgrade is
safe** — `evals/adherence.py` grades whether a cheaper implementer faithfully executes a
plan (`adherence ≥ 0.90 AND critical_failures == 0`, deterministic, no live API cost).
Lever 7 stays skipped: prose is near the good part of the curve (*"minimal ≠ short"* [A1]).

### Part B — Verification (RAN 2026-06-15; still valid) ([verification.md](verification.md))

- **V1 — Billing class:** token-metered AI Credits [B1] (settled). Per-model credit rates
  not captured (needs live dashboard). **Open, non-blocking.**
- **V2 — Static baseline:** shape unchanged; counts grew to 8 agents / 28 skills (P2). **Re-run for exact figures if needed.**
- **V3 — MCP schema cost (decisive):** archived GitHub = **3,963 tok** (leanest useful,
  ~152 tok/tool); official surgical read-only = **6,650 (+68%)**; scoped+read-only =
  **13,977 (+253%)**; default = **26,537**. The swap costs tokens at every useful tool
  count. **Done.**
- **V4 — Transport:** archived `npx`-stdio and official `docker`-stdio both start + list
  tools; official adds a **Docker prereq**. Remote-HTTP + per-target `carter install`
  wiring not yet exercised. **Partial.**
- **V5 — Hop cost:** not instrumented. **Deferred / open (OQ3).**
- **V6 (NEW, r4) — model-rate saving:** NOT yet run. Price the credit/token delta of
  moving each candidate agent from Opus → Sonnet on the plan in use, and run the
  adherence eval per downgrade. **Blocks lever 1 sizing, not lever 1 direction.**

### Part C — GitHub MCP server swap as a SECURITY trade-off (unchanged from r3; still unbuilt)

> V3 proves migrating to the official server *increases* tokens. This is **not** a cost
> optimization — it is **security + maintenance**, priced honestly. Pure
> token-minimisation argues to **keep the archived server** (it is the floor); the
> counter-argument is that it is **archived/unmaintained** and exposes all 26 tools
> (incl. writes) with **no read-only switch**.

Scope: **GitHub MCP server only**; terraform/atlassian token cost is addressed by
**lever 2 (opt-in)**, not a server swap.

**Recommendation: A′** — single official `github/github-mcp-server`, **surgical `--tools`
read-only** (~6,650 tok, V3), MCP writes disabled, shell/`gh` writes left to RFC-0002's
bash gate. Lowest token cost of the official options, simplest installer change, and the
MCP write surface genuinely shrinks. **Go/no-go:** proceed only if the security value is
judged worth the measured **+~2,700 tok/request (+68%)**; else stay on the archived
server and record that. **"Read-only" is MCP-surface only** — shell `gh`/`git`/`terraform`
writes against the same token remain governed by RFC-0002.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Lever 1 (model-tier discipline) first, then lever 2 (MCP opt-in)** (r4 recommendation) | Biggest, simplest, config-only win; adherence-eval de-risks it | Requires per-agent judgement + eval runs |
| **Swap GitHub server to "shrink tokens"** (r2 premise) | — | **Falsified** — official server *adds* +68% to +570% tokens (V3) |
| **Aggressively trim all prompts/skills** | Saves a little | Low leverage; risks accuracy (*minimal≠short* [A1]) |
| **Keep archived server, add nothing** | Zero effort; token floor | Ships an unmaintained server with no read-only switch — standing security risk |
| **Do nothing (status quo)** | Zero effort | Pays Opus rates on 6/8 agents and ships 3 MCP servers to every workspace — the two costs r4 targets |

## Trade-offs / Impact

- **Lever 1 touches:** `MODEL_TIERS` / `DEFAULT_CONFIG["models"]` ([carter/config.py](../../../carter/config.py))
  and/or `carter.yaml` `models.overrides`; `tests/test_models.py`; a `carter.yaml`
  preset (`budget` vs `quality`) if offered. Gated by [evals/adherence.py](../../../evals/adherence.py).
- **Lever 2 touches:** `MCP_SERVERS` ([carter/install/mcp.py](../../../carter/install/mcp.py)),
  `configure_mcp_servers` + its uninstall twin ([carter/installer.py](../../../carter/installer.py)),
  and MCP-wiring tests. `AGENT_MCP_SCOPE` frontmatter emission already exists.
- **Lever 4 (GitHub swap) is a net token COST** (+~2,700/request surgical read-only, V3),
  accepted only for security. Adds a **Docker dependency** (or remote-HTTP fallback).
- **Relationship to neighbours (no overlap):** RFC-0002 = *policy/enforcement* (incl. the
  bash path); RFC-0003 = *credential blast radius (scoped tokens)*, **withdrawn** — see
  its status; **RFC-0004 = *token/context cost, model binding & MCP tool surface*.**

## Open questions

- **OQ1 — Billing magnitude.** Per-model token→credit rates for the plan in use, to price
  lever 1's saving and §C's cost in $ (V1).
- **OQ2 — Downgrade set (RESOLVED, r4).** First cut = **narrator + pm → Sonnet 4.6**
  (redaction is rule-bound; planning follows `carter-plan`'s schema). **learner stays
  Opus** for now (more open-ended prose — revisit as a `budget`-profile candidate once its
  own adherence scenario exists). **maestro / architect / security stay Opus** (routing
  quality-gates everything; deep reasoning). Each downgrade is gated by a recorded
  adherence scenario (OQ7).
- **OQ3 — Hop cost.** Extra tokens a maestro multi-agent chain adds per task (V5).
- **OQ4 — A′ vs B.** Does any workflow need a **native MCP** write path (forcing two
  server instances), or is shell/`gh` (A′) sufficient for devops/narrator?
- **OQ5 — terraform/atlassian opt-in weight.** Confirm lever 2 mechanics and measure each
  server's schema token weight (only GitHub was measured in V3).
- **OQ6 — Transport.** Docker vs remote-HTTP for the official server, wired through
  `carter install` on both targets (V4 completion).
- **OQ7 — Adherence eval coverage (RESOLVED, r4).** Each downgraded agent gets **one
  deterministic adherence scenario** (evidence_any/all/none patterns, per-PR replay) with
  a fixture **recorded live on Sonnet** (`EVAL_RECORD=1`), mirroring the engineer scenario.
  narrator's scenario asserts **redaction holds** (`evidence_none` of the seeded secrets)
  plus required structure; pm's asserts the **plan shape** (`must_haves`/steps present).
  The live weekly cron re-records; the PR gate replays offline. One scenario per agent is
  the accepted floor; a broader matrix is deferred unless a scenario proves flaky.
- **OQ8 — Harness-free portability (NEW, r4).** Model binding, tool scope, and policy are
  emitted per-harness today. Could a vendor-neutral render target (AGENTS.md / Agent
  Format) carry them, so cost levers apply across harnesses? Scoped out of this RFC;
  flagged for a successor.
- **OQ9 — Plan 003 disposition (RESOLVED, r4).** Lever 1 is **split into its own plan**
  (model-tier discipline + `profile:` key + narrator/pm adherence scenarios) and sequenced
  **first**. Plan 003 keeps the MCP work (levers 2 + 4) and is executed **after**. The two
  are independent — lever 1 touches `config.py`/`carter.yaml`/`evals/`; plan 003 touches
  the installer + MCP JSON.
- **OQ10 — `profile:` key semantics (NEW, r4).** A `profile: quality | budget` key in
  `carter.yaml` (+ `carter init --profile`) resolves to a model-override set layered
  **`models.overrides` > `profile` > tier > default**. `quality` = all-Opus (restores the
  pre-r4 default); unset/`budget` follows the new cheaper default (`budget` additionally
  moves learner → Sonnet). Open sub-question: does `profile` write concrete
  `models.overrides` into the scaffolded `carter.yaml` (visible, greppable) or resolve
  lazily at render time (cleaner file)? **Lean: resolve at render** — keep `carter.yaml`
  minimal and the profile a single readable key. Settle in the plan's step 1.

## Decision

**Accepted 2026-06-15; reconciled 2026-07-06 (r4).** The r3 decision below stands as the
*intended* direction, but **none of it is implemented** — plan 003 is `active` with all
steps `pending`. r4 **re-sequences** the work and adds the model lever the earlier
revisions could not have known about:

- **Lever 1 — model-tier discipline (NEW top priority, r4 scope resolved).** Move
  well-structured agents off Opus, **gated per-agent by a recorded adherence scenario**.
  Largest cost multiplier, lowest risk. **Adopt; sequence first.** Resolved scope:
  - **First cut = narrator + pm → Sonnet 4.6** (`implementers` tier). `learner` and
    `security` **stay on Opus** for now (learner's prose is more open-ended; security is
    deep-reasoning). See OQ2.
  - **Delivered two ways at once:** (a) the shipped **default** re-tiers narrator/pm to
    Sonnet, so everyone saves by default; (b) a first-class **`profile: quality | budget`**
    key in `carter.yaml` (+ `carter init --profile`) resolves to a model-override set —
    `quality` restores all-Opus, `budget` pushes further (adds learner). Precedence:
    explicit `models.overrides` > `profile` > tier > default. See OQ10.
  - **Gate (per your safety choice):** author + record **deterministic** adherence
    scenarios for narrator and pm **before** flipping the default, recorded **live on
    Sonnet** (`EVAL_RECORD=1`) and replayed offline on the PR gate — same pattern as the
    engineer scenario. See OQ7.
- **Lever 2 — MCP server opt-in (still the top *MCP* token win).** Install only the servers
  a workspace selects. **Adopt; unchanged from r3; still unbuilt.**
- **Lever 4 — GitHub server swap (§C) — SECURITY only, A′.** Official server, Docker
  (digest-pinned), read-only, surgical `--tools`. Accept the measured **+68%** token cost
  for a maintained server + write-tool removal. **Adopt as security; unchanged; unbuilt.**
- **Levers 3/5 — round-trip + cache guardrails.** Reinforce spec/TDD-first and byte-stable
  install output. **Adopt the low-effort half.**
- **Declined / deferred:** prose-trim (lever 7); model-choice *automation* (manual +
  eval-gated for now); V5 hop-cost; per-agent MCP *install* minimisation (lever 6).

---

### References

- [A1] Anthropic — *Effective context engineering for AI agents* (2025): minimal-but-
  sufficient context; *"minimal ≠ short"*; bloated tool sets degrade tool choice.
  <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- [A2] Manus — *Context Engineering: Lessons from Building Manus* (2025): KV-cache hit
  rate as the dominant cost/latency metric; ~10× cached vs uncached.
  <https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus>
- [B1] GitHub Docs — *Usage-based billing for individuals* (2026): Copilot bills **GitHub
  AI Credits**; cost = model × (input+output+cached) tokens; 1 credit = $0.01; agentic
  features "consume significantly more"; 10% auto-model-selection discount.
  <https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-individuals>
- [G1] GitHub — *github/github-mcp-server* (`--toolsets`, `--tools`, `--read-only`).
  <https://github.com/github/github-mcp-server>
