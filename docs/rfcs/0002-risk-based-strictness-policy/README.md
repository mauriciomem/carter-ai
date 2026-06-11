---
id: RFC-0002
status: review                # draft | review | accepted | rejected | withdrawn
revision: 1
created: 2026-06-11
decided: null
author: mauriciomem
adr: null                     # set when accepted (likely ADR-0005 — see Q19)
plan: null
supersedes: []
tags: [strictness, enforcement, security, agents, mcp, policy]
---

# RFC-0002: Risk-Based Strictness Policy

**Status:** Review
**Revision:** 1
**Author:** mauriciomem

> **Execution note.** This RFC is written to be picked up in a **fresh session**.
> It embeds the verified current state (with `file:line` grounding) so the
> implementer need not re-discover it. Every doubt is captured in **Open
> questions** (Q1–Q20) with a recommended default *and* a `DECIDE` flag where a
> human call is required before coding. Resolve the `DECIDE` items first.

## Summary

Make Carter **a little less "loose"** without killing the speed of the current
chain. Today Carter's safety posture is **advisory prose** in agent prompts: tool
scoping, "read-only" access, and "require confirmation for risky actions" are
*described*, never *enforced*. This RFC proposes a **risk-based strictness policy**
with three pillars:

1. **Per-agent tool allowlists** (deny-by-default outside an agent's role).
2. **A risk taxonomy + gates** (read / local-write / remote-write / infra-mutate /
   secret-access / destructive / external-publish → allow / ask / gate / deny).
3. **Strictness levels** (`loose` | `guarded` | `strict`) that map categories to
   gates, emitted as **platform-native enforcement where supported** and advisory
   prose elsewhere — *honestly labelled* so a user knows which they're getting.

The unifying honest premise: **Carter is a scaffolder, not a runtime.** It cannot
intercept a tool call. "Enforcement" therefore means *emitting platform-native
config that the target (OpenCode / VS Code / Copilot CLI) enforces*, plus a
deterministic `carter check` lint that the emitted config matches the declared
policy. Where a target can't enforce, the policy degrades to prose and says so.

## Problem

Carter's current strictness is **declarative, not enforceable** — verified:

| Claim in Carter today | Reality | Evidence |
|---|---|---|
| Agents have scoped tool access ("read-only github") | Prose only; no `tools`/`permission` frontmatter is emitted | `templates/agents/*.j2` frontmatter = `description`/`mode`/`temperature` only; `agents/carter-architect.md` `<mcp>` says "read-only access" |
| MCP servers are scoped per agent | Wired **globally**; any agent can call any server | `configure_mcp_servers` hardcodes `["github","terraform","atlassian"]` into VS Code `settings.json`, `copilot mcp add`, `opencode.json` — flat merge, no agent dimension (`carter/installer.py:782`) |
| "read-only" MCP access | Tokens are full-scope and shared globally — a "read-only" agent can still write | `REQUIRED_ENV_VARS` = `GITHUB_TOKEN`/`TF_TOKEN`/`ATLASSIAN_*`; one token per service, no per-agent scope (`carter/installer.py`) |
| Risky actions require confirmation | Advisory prose, gated on `personality.skepticism == "scaled"` | maestro "Skepticism Calibration" table: *"Risky → Full pushback. Require confirmation."* (`templates/agents/carter-maestro.md.j2:170`) |
| Remote writes need approval | Exists only as a **plan-level** `push_policy: manual` field, read as prose | `docs/reference/frontmatter.md:25` |

The quality gate already does **post-implementation** multi-agent review with
blocking severities (`carter-maestro.md.j2` `<quality_gate>`), but there is **no
pre-action gate**: nothing stops an agent from pushing, applying Terraform, or
reading secrets *before* review, and nothing restricts *which* agent may do so.
Review is cheapest before the action; today it only happens after.

## Proposal

A single coherent **policy** model with one config block, a fixed risk taxonomy, a
per-agent allowlist, and a target-aware emission + lint pipeline.

### 1. Config: a `policy` block in `carter.yaml`

Added to `DEFAULT_CONFIG` (`carter/config.py`), backward-compatible (merged with
defaults like every other section):

```yaml
policy:
  level: guarded          # loose | guarded | strict  (a.k.a. L0 | L1 | L2)
  unknown_tool: ask       # gate for tools not in the risk map (allow | ask | deny)
  overrides: {}           # category -> gate, explicit per-category override
  audit_overrides: true   # log escape-hatch overrides via `carter ops`
```

- **`loose` (L0)** = today's behavior exactly (advisory prose; nothing blocks).
- **`guarded` (L1)** = recommended default for *new* installs.
- **`strict` (L2)** = regulated / prod-critical work.

### 2. Risk taxonomy (fixed, shipped with Carter)

Seven categories; every tool/MCP action maps to exactly one. Gate vocabulary:
`allow` (silent) · `ask` (human confirm) · `gate` (ask **+** required handoff to
the owning agent / checkpoint artifact) · `deny` (blocked; override required).

| # | Category | Examples | loose | guarded | strict |
|---|---|---|---|---|---|
| R0 | read | file read, `git status/log/diff`, `tf plan`(no-refresh), MCP GET | allow | allow | allow |
| R1 | local-write | file edit/create, `git add/commit` (local), run tests | allow | allow | allow |
| R2 | remote-write | `git push`, PR/issue create·merge·comment, workflow dispatch, release publish, MCP POST/PATCH/PUT/DELETE | allow* | ask | gate |
| R3 | infra-mutate | `terraform apply/destroy`, `kubectl apply`, `helm upgrade`, deploy scripts | allow* | gate | deny |
| R4 | secret-access | read secret files / `.env` with tokens, vault reads | allow | ask | gate |
| R5 | destructive | `rm -rf`, `git reset --hard`, `git push --force`, drop table, branch delete | allow* | gate | deny |
| R6 | external-publish | outward content (Slack, PR description, release notes, Jira comment) | allow* | gate (narrator) | gate (narrator) + ask |

\* `loose` keeps the existing **advisory** skepticism nudge — it does not silence it.

### 3. Per-agent tool allowlist (deny-by-default)

Independent of level: a category **not** listed for an agent is **denied** for that
agent, always. This is the "tool allowlist per agent" pillar.

| Agent | Allowed categories | Rationale |
|---|---|---|
| maestro | R0 | routes; never mutates directly |
| architect | R0 | design/review; reads only |
| engineer | R0, R1 | codes/tests locally; R2 only via a devops handoff |
| devops | R0, R1, R2, R3, R5 | the **only** infra-mutator / pusher |
| pm | R0, R1 | plans; local artifacts only |
| learner | R0 | explains; reads only |
| narrator | R0, R1, R6 | the **only** external publisher |

### 4. Emission — enforce natively where supported, label the rest

The effective policy = `min(level gate, per-agent allowlist)` per category,
translated per target:

| Mechanism | OpenCode | VS Code / Copilot agents | Copilot CLI |
|---|---|---|---|
| Per-agent tool allow/deny | `tools: {name: bool}` (enforced) | `tools:` frontmatter list | **verify (Q2)** |
| Per-action gate (ask/deny) | `permission: {edit,bash,webfetch,...}` (enforced) | partial — **verify (Q2)** | **verify (Q2)** |
| Per-agent MCP server scope | via tools/permission | **verify (Q2)** | **verify (Q2)** |
| Prose `<policy>` backstop | yes | yes | yes |

Rules:
- **OpenCode**: emit `tools`/`permission` in each agent's frontmatter → genuine
  runtime enforcement.
- **VS Code/Copilot**: emit `tools:` list where supported; otherwise prose backstop.
- **All targets**: emit a `<policy>` block in the agent body (allowlist + gates) and
  **upgrade the maestro risk table** from `skepticism`-gated prose to a policy-driven
  gate that is always present (not conditional on `personality.skepticism`).
- **MCP**: where per-agent server scoping is supported, emit it; otherwise restrict
  by **denying the server's write tool names** and **drop the "read-only" wording**
  wherever it cannot be enforced (no false guarantees — Q3).

### 5. Static validation (`carter check` extension)

Deterministic, testable, runs offline:
- Lint that each **installed** agent's emitted frontmatter matches its declared
  allowlist + the active level's gate map.
- Detect **drift** between `carter.yaml policy` and the installed agent/MCP files.
- **WARN** when the active target cannot natively enforce the declared level
  (degradation transparency).
- It **cannot** verify that the platform actually denies at runtime — explicitly
  out of scope and documented (Q17).

### 6. Escape hatch

A `deny`-gated action proceeds only with an **explicit, single-action override**
recorded via `carter ops` audit (reuse the existing audit path shown in the
session terminal). No blanket/session-wide overrides — overrides are per action to
avoid override fatigue (Q11).

### 7. Phasing (so a fresh session can land it incrementally)

- **P1 — model + docs (no behavior change):** `policy` block in `config.py`; risk
  taxonomy + tool→risk map (shipped, user-extensible); agent-frontmatter schema
  added to `docs/reference/frontmatter.md`; default level for *existing/omitted*
  config = `loose` (Q6).
- **P2 — emission:** agent templates + static `agents/*.md` emit `tools`/`permission`
  (OpenCode) and `tools:`/`<policy>` (Copilot); `configure_mcp_servers` gains
  per-agent scoping where supported; maestro risk table becomes policy-driven.
- **P3 — lint + escape hatch + tests:** `carter check` policy lint; override audit;
  unit tests for emission + lint (runtime denial is manual/out of scope).

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Risk-based hybrid (chosen)** | speed for low-risk; hard gates only where it matters; native enforcement where possible | per-target divergence; more config surface |
| Globally rigid (everything gated) | simplest mental model | kills the loose-chain speed; users disable it (worse than loose) |
| Prompt-only "be stricter" | zero code | unenforceable; the exact problem we have now |
| Runtime proxy/wrapper intercepting tool calls | true enforcement on any target | huge complexity; Carter would become a runtime — rejected |
| Reuse `quality_gate` pre-action | no new concept | gate is post-implementation review, not per-action authorization (different seam) |

## Trade-offs / Impact

- **New config surface** (`policy` block) — additive, backward-compatible.
- **Touches > 3 files** (config, all agent templates, static agents, installer MCP
  wiring, `carter check`, frontmatter docs) → justifies an RFC + ADR + plan.
- **Per-target inequality:** OpenCode gets real enforcement; Copilot/VS Code may be
  advisory-only until verified — `carter check` must surface this, not hide it.
- **`carter update` re-emits agents** (they say "do not edit directly") — policy
  customization must live in `carter.yaml`, never in hand-edited agent files (Q12).
- **Reconciliations:** generalizes plan `push_policy`; sits orthogonal to
  `personality.skepticism` (tone) and `quality_gate` (post-review); overlaps
  `redaction` for R6.
- **Risk of friction:** an over-strict default makes users disable the whole thing
  → default `guarded`, single-action overrides, clear WARNs.

## Open questions

Each: **doubt → options → recommended default** (`DECIDE` = needs a human call
before coding).

- **Q1 — Enforcement locus.** Carter is a scaffolder, not a runtime; can it enforce
  at all? → *Rec:* "enforce" ≝ emit platform-native config + lint; advisory
  elsewhere. No proxy. **(framing — confirm)**
- **Q2 — Per-target capability.** Which of OpenCode / VS Code agents / Copilot CLI
  truly enforce per-agent `tools`, per-action `permission`, and per-agent **MCP
  server** scoping in 2026? → *Rec:* verify against current docs before P2; OpenCode
  `tools`+`permission` assumed enforcing; VS Code `tools:` assumed list-only.
  **DECIDE after verification.**
- **Q3 — MCP token blast radius.** "read-only" is fiction while tokens are
  full-scope + shared. → *Rec:* deny write **tool names** where supported; drop
  "read-only" wording where unenforceable; per-agent scoped tokens = out of scope.
  **DECIDE** (accept residual risk vs. invest in scoped tokens).
- **Q4 — vs `personality.skepticism`.** Overlap/contradiction (e.g.
  `skepticism: off` + `level: strict`). → *Rec:* orthogonal — skepticism = **tone**,
  policy = **enforcement**; on conflict, **policy gates win**, skepticism only
  shapes prose.
- **Q5 — vs `quality_gate` / `tdd.strict`.** Is "approval checkpoint" just the
  quality gate pre-action? → *Rec:* keep separate seams; reuse the severity
  vocabulary; policy = pre-action authorization, quality gate = post-implementation
  review.
- **Q6 — Default level.** New vs existing installs. → *Rec:* new installs default
  `guarded`; omitted/existing config defaults `loose` to preserve behavior.
  **DECIDE:** `loose`-preserve vs `guarded`-nudge-with-migration-note.
- **Q7 — Level scope.** Global only, or per-agent / per-category overrides? → *Rec:*
  global `level` + optional `overrides` map (category→gate); per-agent allowlist
  always applies.
- **Q8 — Taxonomy edge cases.** Is `git commit --amend` on a *published* commit R5?
  Is `terraform plan` R0 even though it can refresh state / read secrets? Is reading
  `.env` R4? → *Rec:* amend-published = R5; `tf plan` default R0 but `-refresh`/state
  write = R2; `.env` read = R4. **Review the table.**
- **Q9 — Tool→risk map ownership.** Hardcoded vs user-extensible; unknown tool/MCP
  server default. → *Rec:* shipped map, user-extensible in `carter.yaml`;
  `unknown_tool` defaults `ask` at guarded, `deny` at strict.
- **Q10 — Handoff is advisory.** Models can ignore prompt protocol. What's the real
  backstop? → *Rec:* backstop = platform `ask` (human-in-loop) for R2+; the handoff
  protocol layers on top; label it advisory where not natively enforced.
- **Q11 — Override UX.** How to override a `deny` without override fatigue? → *Rec:*
  explicit single-action override + `carter ops` audit entry; no session-wide
  overrides.
- **Q12 — `carter update` clobbering.** Re-render wipes hand-edits. → *Rec:* all
  policy customization lives in `carter.yaml`; agents are always re-emitted from it.
- **Q13 — Lint scope.** What can `carter check` actually verify? → *Rec:* emitted
  frontmatter ↔ declared allowlist; category↔gate per level; carter.yaml↔installed
  drift. Runtime denial not verifiable.
- **Q14 — Global vs workspace install.** `install_agents` copies static
  `agents/*.md` globally with **no `carter.yaml`** in scope; workspace agents are
  templated. What policy do *global* agents carry? → *Rec:* bake `guarded` defaults
  into the static `agents/*.md` at build time. **DECIDE:** baked-default vs a global
  policy file read at install.
- **Q15 — Multi-target consistency.** A Copilot-only user may silently get weaker
  guarantees than OpenCode. → *Rec:* install + `carter check` WARN when the target
  lacks native enforcement for the declared level.
- **Q16 — vs `redaction`.** R6 overlaps `redaction.enabled`. → *Rec:* R6 requires a
  narrator handoff only when `redaction.enabled`; else `ask`.
- **Q17 — Testing.** Enforcer is external. → *Rec:* unit-test emission
  (policy→frontmatter/MCP) + lint + prose text; runtime denial = manual / out of
  scope, documented.
- **Q18 — One RFC vs split.** Allowlists / risk-tiers / gates / levels separable? →
  *Rec:* one RFC, one coherent policy, **phased** (P1–P3).
- **Q19 — ADR numbering.** An accepted RFC yields an ADR; the next number is
  **ADR-0005**, but ADR-0005 was informally reserved for off-machine backup/
  durability (deferred). → **DECIDE:** which decision takes ADR-0005 (recommend this
  one; backup takes the next free number when written).
- **Q20 — Reconcile `push_policy`.** Plan frontmatter already has
  `push_policy: manual|auto`. → *Rec:* fold into the model — `manual` ⇒ R2=`gate`
  for that plan; keep the field as a per-plan override; document the relationship in
  `frontmatter.md`.

## Decision

[Pending — filled when accepted/rejected. On acceptance: record as an ADR (Q19),
then create an execution plan covering P1–P3, then implement. Per ADR-0004, an
accepted RFC yields an ADR before a plan executes it.]
