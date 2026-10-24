---
id: ADR-0005
status: superseded
created: 2026-06-13
decided: 2026-06-13
supersedes: []
superseded_by: ADR-0010
rfc: RFC-0002
tags: [strictness, enforcement, security, agents, mcp, policy]
---

# ADR-0005: Risk-Based Strictness Policy

> **Status note (2026-10-24):** Superseded by ADR-0010. The MCP env-var list (`REQUIRED_ENV_VARS`) now lives in `carter/install/prereqs.py` and is `GITHUB_TOKEN`, `TFE_TOKEN` (Atlassian uses OAuth). `redaction.enabled` was removed in 2026-10 and is ignored if present: the narrator's redaction pass is always on, and `carter check` no longer warns about it.

**Status:** Superseded by [ADR-0010](0010-agent-platform-refresh.md) (2026-06-26)
**Date:** 2026-06-13
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro (synthesis of architect/engineer/devops/narrator/pm reviews)
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** Records the decision of RFC-0002 (record removed 2026-10);
[ADR-0004](0004-rfc-system.md) defined the RFC system that produced it.

---

## Context

Carter is a **scaffolder**: it emits agent and MCP configuration for OpenCode,
VS Code custom agents, and Copilot CLI, then exits. Its safety posture today is
**advisory prose**, not enforcement — verified against the codebase:

- **Tool scoping is described, never emitted.** `templates/agents/*.j2`
  frontmatter carries only `description` / `mode` / `temperature`; no `tools` or
  `permission` field is rendered.
- **"Read-only" is a false guarantee.** Four static agents claim read-only MCP
  access in body prose, but MCP servers are wired **globally** —
  `configure_mcp_servers` (`carter/installer.py:782`) hardcodes
  `["github","terraform","atlassian"]` into every target with no agent dimension,
  and `REQUIRED_ENV_VARS` (`carter/installer.py:271`) ships one full-scope token
  per service, shared by every agent. A "read-only" agent can still write.
- **Risky-action confirmation is conditional prose.** The maestro "Skepticism
  Calibration" table only nudges, and only when `personality.skepticism == "scaled"`
  (`templates/agents/carter-maestro.md.j2:~170`).
- **There is no pre-action gate.** The quality gate runs *post-implementation*
  review; nothing stops an agent from pushing, applying Terraform, or reading
  secrets *before* review, and nothing restricts *which* agent may do so.

The maintainer wants Carter **less "loose"** without killing the speed of the
low-risk chain, and wants any claim of "enforcement" to be **honest** about what
the underlying target can and cannot guarantee at runtime.

---

## Decision

Adopt a **risk-based strictness policy**: one coherent policy boundary expressed
as seven interdependent sub-decisions (D1–D7). They share a single rationale and
seam, so they live in one ADR; any one may later be superseded by reference
(`ADR-0005§Dn`). Full design detail and `file:line` grounding live in RFC-0002 —
this ADR records *what was decided and why*, not the whole proposal.

### D1 — Three pillars

The policy stands on three composing pillars:

1. **Per-agent tool allowlists — deny-by-default.** A category not listed for an
   agent is denied for that agent, at every level (e.g. only devops holds R2/R3/R5;
   narrator is the only R6 author).
2. **A fixed risk taxonomy R0–R6** with a four-word gate vocabulary —
   `allow` (silent) · `ask` (human confirm) · `gate` (ask + handoff/checkpoint) ·
   `deny` (blocked, override required). R0–R5 are mutually-exclusive
   transport/action categories; **R6 (external-publish) is a content overlay**
   (see D4). Multiple matches resolve **most-restrictive-wins**.
3. **Strictness levels** `loose | guarded | strict` (L0/L1/L2) mapping categories
   to gates, configured by a new backward-compatible `policy` block in
   `carter.yaml`. `loose` = today's behavior exactly; `guarded` = recommended
   default; `strict` = regulated/prod-critical.

### D2 — Enforcement model: emit native interceptors, degrade honestly

The Carter *process* cannot intercept a tool call (it exits after scaffolding) —
but the *config Carter emits* **can**, because modern targets ship native
interceptors: OpenCode `permission`, Copilot CLI `hooks` (preToolUse), VS Code
`tools:` allowlists + `sandbox`. "Enforcement" is therefore defined as: **emit
platform-native interceptors and allowlists where the target supports them,
degrade to clearly-labelled advisory prose where it does not, and ship a
deterministic `carter check` lint** that verifies the emitted config matches the
declared policy. The emission ladder, per category, is
**native-deny → native-ask → prose backstop** — a `deny` prefers a native
interceptor (blocked) over a mere allowlist omission (unlisted).

### D3 — Per-target capability is unequal, and surfaced not hidden

Verified against 2026 target docs: OpenCode `permission` and VS Code/Copilot
`tools:` allowlists are **enforced**; per-category ask/deny gating is **strongest
on OpenCode** (`permission` + bash globs) and **Copilot CLI** (`hooks`
preToolUse), and **weakest on VS Code** (no declarative per-category gate; `hooks`
still Preview; bash cannot be gated declaratively). This inequality is **made
visible, never hidden**: when the active target cannot natively enforce a declared
`strict` policy, install and `carter check` require an explicit **HARD ACK** of
the degraded guarantee, with a non-interactive `--accept-degraded` flag for
CI/automation. Absent the ack in a non-interactive context, the command **fails
closed**.

### D4 — R6 external-publish is a content overlay; single-pusher preserved

R6 composes with the transport gate rather than replacing it (an outward
`gh pr comment` is both an R2 transmit **and** R6 content). **Narrator is the sole
external author** — it drafts and runs the redaction pass on R6 content;
**devops performs the transmit under its R2 gate** via a narrator→devops handoff.
No single agent holds both categories, preserving the **single-pusher invariant**.
R6 has two lanes: short-form low-risk outward content = `ask` + an inline
redaction check; substantive outward content (release notes, Slack, Jira bodies,
PR descriptions) = full `gate(narrator)`. At `guarded` and `strict`, R6 **forces a
redaction pass regardless of `redaction.enabled`**, and `carter check` WARNs on
the `redaction.enabled: false` contradiction.

### D5 — Token blast radius: ship guarded now, defer the real fix

The shared full-scope MCP token is **not** fixed here. This policy ships
`guarded`, **drops the false "read-only" wording** from all four static agents
that carry it (body prose, not frontmatter — so the `test_parity` check won't catch
it; P1 must edit both statics and templates), and **defers genuine per-agent
scoped tokens to RFC-0003 (record removed 2026-10)**.
Accepted residual risk: **medium**.

### D6 — Reconciliations with existing seams

- **`push_policy`** generalizes into the policy model: effective R2 gate =
  `max(workspace level, plan push_policy)`; `push_policy: manual` only ever
  *tightens* R2, never loosens it.
- **Orthogonal to `personality.skepticism`** (tone only — on conflict, policy
  gates win) and to **`quality_gate`** (post-review, a different seam from
  pre-action authorization; severity vocabulary is reused).
- **Global agents have no `carter.yaml` in scope.** Build-time generation is
  WON'T-DO ([ADR-0002:37](0002-single-source-agent-generation.md); statics are
  raw-copied at `installer.py:498`), so global agents carry **baked hand-edited
  `guarded` defaults** in the static `agents/*.md`, kept honest by a
  `test_parity.py` extension (dual-source hand-edit, not generation).

### D7 — Phasing with a P2→P3 gate

- **P1 — model + docs (no behavior change):** `policy` block (dict-shaped maps, to
  survive `_deep_merge`'s wholesale list replacement) in `config.py`; risk
  taxonomy + tool→risk map; frontmatter schema; default `guarded` for new installs,
  `loose` for existing/omitted config; drop the "read-only" prose.
- **P2 — emission:** templates and statics emit `permission` / enforced `tools:` /
  `hooks` + per-agent MCP scope; maestro risk table becomes policy-driven; the
  "you're guarded now" migration message surfaces here (where enforcement is real).
- **P3 — lint + escape hatch + tests:** `carter check` policy lint (incl. the D3
  hard ack and D4 WARN); single-action override ledger via `carter ops`; emission +
  lint unit tests.
- **Gate:** `strict` enforcement **ships only after P3 lands.** The execution plan
  decomposes the phases into milestones with an explicit **P2→P3 gate**.

---

## Options Considered

### Option 1: Risk-based hybrid — native enforcement where supported, honest prose elsewhere (chosen)
- **Pros:** keeps low-risk speed; hard gates only where they matter; emits the
  target's *native* interceptors (hooks / `permission: deny`) for real runtime
  enforcement; honestly labels the gaps.
- **Cons:** per-target divergence; more config surface to maintain.

### Option 2: Globally rigid — everything gated
- **Pros:** simplest mental model.
- **Cons:** kills the loose-chain speed; users disable it wholesale — worse than
  `loose`.

### Option 3: Prompt-only "be stricter"
- **Pros:** zero code.
- **Cons:** unenforceable — it *is* the problem we have today.

### Option 4: Carter as a runtime proxy intercepting calls itself
- **Pros:** true enforcement on any target.
- **Cons:** huge complexity; Carter would become a runtime, not a scaffolder.
  **Rejected** — we emit the target's native interceptors instead.

### Option 5: Reuse `quality_gate` for pre-action authorization
- **Pros:** no new concept.
- **Cons:** the quality gate is *post-implementation review*, a different seam from
  *per-action* authorization.

### Option 6: Per-agent scoped MCP tokens
- **Pros:** fixes the shared full-scope token at its root.
- **Cons:** out of scope here — **split into RFC-0003 (record removed 2026-10)**
  (see D5).

---

## Rationale

The hybrid wins because it is the only option that is simultaneously **fast,
enforceable, and honest**. Low-risk work (R0/R1) stays `allow`, so the chain keeps
its speed; hard gates land only on R2–R6 where a mistake is expensive. Crucially,
the enforcement is **real where the target permits it** — emitting OpenCode
`permission: deny` or a Copilot `hooks` preToolUse genuinely blocks the action at
runtime — and **honestly labelled where it does not** (the D3 hard ack), so a user
always knows whether they are getting an enforced gate or a prose nudge. The
runtime-proxy alternative was rejected on principle: intercepting calls ourselves
would turn a scaffolder into a runtime, multiplying complexity and operational
surface for a guarantee the targets already offer natively. Deferring scoped
tokens to RFC-0003 keeps this decision shippable while removing the dishonest
"read-only" claim immediately.

---

## Consequences

### Positive
- A **pre-action** safety seam exists for the first time; review is no longer the
  only checkpoint, and it moves *before* the expensive action.
- Enforcement is **genuine** on OpenCode and Copilot CLI (native interceptors),
  not advisory.
- The false **"read-only"** claim is removed at all four static agents.
- Backward-compatible: `policy` is additive; existing installs default to `loose`
  (no behavior change until the user opts in).

### Negative
- A new config surface (`policy` block, tool→risk map, per-agent allowlist) to
  document and maintain.
- Per-target divergence means the same policy yields different real guarantees on
  different targets.
- Touches > 3 files (config, all agent templates, static agents, installer MCP
  wiring, `carter check`, frontmatter docs).

### Risks
- **Per-target inequality** — VS Code's weaker gating could lull users into a false
  sense of strictness; mitigated by the D3 hard ack surfaced at install and lint.
- **Residual token risk** — the shared full-scope MCP token remains until RFC-0003;
  accepted at **medium**.
- **Reliance on emitted-config correctness** — enforcement is only as good as the
  emitted native config; `carter check` lints config↔policy drift but **cannot**
  verify the platform actually denies at runtime (explicitly out of scope).

---

## References

- RFC-0002 — Risk-Based Strictness Policy (record removed 2026-10) — the proposal this ADR records (revision 3, accepted 2026-06-13).
- [ADR-0004 — RFC system](0004-rfc-system.md) — the process that produced RFC-0002.
- [ADR-0002 §37 — single-source agent generation](0002-single-source-agent-generation.md) — build-time generation is WON'T-DO (statics are raw-copied; D6).
- RFC-0003 — Per-agent scoped MCP tokens (record removed 2026-10) — deferred token fix (D5).
- [Frontmatter reference](../reference/frontmatter.md) — canonical schema for the `policy` block and agent frontmatter.
