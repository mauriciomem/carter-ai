---
id: ADR-0010
status: accepted
created: 2026-06-26
decided: 2026-06-26
supersedes: [ADR-0005]
superseded_by: null
rfc: RFC-0005
tags: [agents, orchestration, subagents, dispatch, models, strictness, policy, time, copilot, vscode, opencode]
---

# ADR-0010: Carter Agent Platform Refresh

> **Status note (2026-10-24):** D2 tiers have moved on: pm and narrator are now implementers (Sonnet), and the shipped models are the Claude 5.5 family (Opus 5.5 / Sonnet 5.5). A `profile:` key re-tiers at resolve time. `redaction.enabled` (kept by D5) was removed in 2026-10 and is ignored if present: narrator redaction is always on, and there is no `carter check` warning.

**Status:** Accepted
**Date:** 2026-06-26
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro (synthesis of architect/engineer/devops/narrator/pm reviews)
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** Records the decision of RFC-0005 (record removed 2026-10)
(revision 3, accepted 2026-06-26). **Supersedes [ADR-0005](0005-risk-based-strictness-policy.md) in
full** — four of the decisions below change ADR-0005's load-bearing model (levels, taxonomy, narrator
special-casing, dispatch primitive). [ADR-0004](0004-rfc-system.md) defined the RFC system that
produced RFC-0005.

---

## Context

Carter is a **scaffolder**: it emits agent and MCP configuration for OpenCode, VS Code custom agents,
and Copilot CLI, then exits. ADR-0005 (risk-based strictness) shipped the first pre-action safety seam,
but four of its load-bearing pieces are now wrong or over-built, and three new capabilities are missing.
Verified against the codebase and primary target/model docs (26 Jun 2026; model facts re-checked
against the bundled `claude-api` skill, cached 2026-06-04):

- **The dispatch primitive is fictional.** `runSubagent` exists on no target
  ([carter-maestro.md:41], [carter-triage/SKILL.md:27]). The real primitive is VS Code's `agent` tool +
  `agents:` allowlist, OpenCode's `permission.task`, and Copilot CLI's `/fleet` — none of which Carter
  emits. ADR-0005 conflated `handoffs:` (user-approved UI buttons) with programmatic dispatch.
- **The strictness model carries a dead level.** `loose` ("advisory only, nothing blocks") was a
  backward-compat carve-out; with the policy shipped a year, it is a footgun (users think they're
  protected and aren't) and 27 references of churn.
- **The 7-category taxonomy is over-built.** R4 (secret-access) is thin; R6 (external-publish) is an
  *overlay* that breaks the "exactly one category" rule and special-cases the narrator.
- **No per-agent model, no time-awareness.** Agents author dated artifacts but have no current-date
  source (this very RFC's session had to be *told* the date), and there is no way to run the
  documentation-authoring agents on a high-reasoning model while running the implementers on a cheaper
  one.
- **`temperature` is dead-or-rejected** on every model Carter pins yet is emitted on every agent and
  asserted by a parity test.

The maintainer scoped a single coherent refresh: native dispatch, per-agent model, two-level
strictness, a simplified taxonomy with a first-class narrator, time-awareness, and a staleness purge.
These share one seam (the emitted agent config and its `carter check` lint), so they live in one ADR.

---

## Decision

Adopt the **Carter Agent Platform Refresh**: nine interdependent sub-decisions (D1–D9) sharing the
emitted-config seam and the deny-by-default / enforcement-honesty principles ADR-0005 established. Full
design detail, `file:line` grounding, the per-agent allowlist table, and the phased roadmap live in
RFC-0005 — this ADR records *what was decided and why*.

### D1 — Native subagent dispatch replaces the `runSubagent` fiction

Emit the real primitive per target, on the **primary** (maestro): VS Code/Copilot get `tools: ['agent']`
+ an **explicit** `agents: [...]` list **and** `handoffs:` (the gate-confirm surface); OpenCode gets a
`permission.task` block with **explicit per-specialist** allow entries. `agents:`/`permission.task` are
a **security boundary**, never `'*'` or a `carter-*` glob — a glob auto-trusts any future
`carter-*`-named agent the user installs; `'*'` lets the maestro delegate to any workspace agent
(failure-open). This is **fail-closed**: a new `carter check` lint **errors (exits non-zero)** if the
primary emits `'*'`, a glob, or omits the key. The chain is **flat** — specialists carry `agents: []`,
so the maestro is the only router. Copilot CLI orchestration is `/fleet`/`@`-mention (runtime); because
`/fleet` subagents do **not** inherit chat history, the maestro's Copilot-CLI prose **must inject the
active-plan + knowledge context into every `/fleet` prompt**, or cross-domain runs silently lose
Carter's state. Delete `runSubagent` at both sites.

### D2 — Per-agent model via a dedicated `models:` block; effort is global-only

Add a `models:` block in `carter.yaml` (orthogonal to `policy:`) mapping role tiers to per-target model
strings, resolved **`overrides` > tier > `default`** (`default` = the un-tiered catch-all). Thinkers
(maestro, architect, pm, learner, narrator) = Opus 4.8; implementers (engineer, devops) = **Sonnet 4.6**
(not Haiku — the reliability premise argues against the smallest model; Haiku is an opt-in via
`models.overrides`). Emit a **single** `model:` string per agent (the array form breaks Copilot CLI):
display name for VS Code/Copilot, `provider/model` ID for OpenCode, via a Carter→target **model-name
table** with a `MODEL LAUNCH` sync marker and a non-empty-per-role test. Carter cannot verify the user's
subscription, so it **emits anyway** and `carter check` prints a **required advisory**. **Effort is not
emitted** — no target has a per-agent effort field; it is the API's global `output_config.effort`, set
per-session on the harness. The docs recommend a single global default of **`high`** (the safe
all-rounder: `xhigh`/`max` error on a Haiku override, `medium` under-serves the thinkers), overridable
per-session.

### D3 — Two strictness levels; `loose` purged entirely

`POLICY_LEVELS = ("guarded", "strict")`. `guarded` is the floor and the default for everything (new and
existing/omitted). **`loose` is removed from all shipped surfaces** with **no migration notice and no
coercion branch** — an absent/legacy level resolves to `guarded` through the normal default path. The
purge touches **live** surfaces only; archived completed-plan records (`design/plans/completed/002-*`)
are left intact as history.

### D4 — Simplify to 4 categories with a printed per-agent allowlist

Collapse R0–R6 to **`read`, `local-write`, `remote-write`, `dangerous`**. Secret-access (old R4) is
**merged into `remote-write`** (it gates identically, so nothing is under-protected); the standalone
category is deleted. R6 (external-publish) is dropped as a category (handled by D5). The **per-agent
allowlist is the genuinely valuable half** and is printed as the P2 spec (deny-by-default — a category
absent for an agent is denied for it):

| Agent | `read` | `local-write` | `remote-write` | `dangerous` |
|---|:---:|:---:|:---:|:---:|
| maestro, architect, learner | ✅ | — | — | — |
| pm, narrator, engineer | ✅ | ✅ | — | — |
| devops | ✅ | ✅ | ✅ | ✅ |

This encodes **devops as the sole pusher** (only holder of `remote-write`/`dangerous`), engineer cannot
remote-write, pm may scaffold plan docs, and narrator authors locally but does not push.

### D5 — First-class narrator; redaction ENFORCED via a gate-tier handoff

The narrator becomes a normal specialist (the external-content specialist, parallel to "the architect
is the design specialist") — no R6 overlay, no special-cased scope. Redaction is **enforced, not
advisory**: at `guarded`/`strict`, **substantive** outward content (release notes, PR descriptions,
Jira/Slack bodies) **must** route through the narrator as a **`gate`-tier handoff encoded in the
allowlist**, then hand to devops (sole `remote-write` holder) to transmit; **short-form one-liners**
stay `ask` + an inline redaction check. This preserves ADR-0005 §D4's forced-pass guarantee while
deleting the overlay complexity — the single-pusher invariant now falls out of the D4 allowlist
structurally. Keep `redaction.enabled` **and** the force-the-pass-at-`guarded`/`strict` fix (the
ADR-0005 §D4 / RFC-0002 Q16 leak fix), decoupled from the dropped R6. `gate` is enforced per-target to
the extent each target enforces gates (the `_TARGET_ENFORCES_GATES` reality, re-evaluated in D8).

### D6 — Time-awareness by instruction, never interpolation

Carter is a scaffolder and cannot inject a live clock (it would also poison the prompt cache). So:
(1) global instructions and the `carter-plan`/`carter-rfc`/`carter-adr` skills carry a **required
date-fetch checklist item** — obtain the current date (native harness var or `date`) **before** writing
any dated frontmatter; (2) the implementing session **verifies per target** whether a native current-date
is exposed and prefers it where present, falling back to the fetch instruction; (3) Carter-side stamping
stays where Carter owns the write (`init`/`save`/ops); (4) **never** bake `Today is <date>` into a
template.

### D7 — `temperature` dropped wholesale

Stop emitting `temperature` on all agents and all targets; remove its parity-test assertion. VS Code
does not recognize the field (silently ignored); OpenCode accepts it syntactically but the pinned
Anthropic models reject it at the API (Opus 4.8/4.7 & Fable 5 return 400; Sonnet 4.6 also removed
sampling params). Effort and temperature are documented as **runtime-owned**.

### D8 — Staleness purge and honest per-target enforcement

Delete `runSubagent` (D1); re-sync drifted static↔template bodies + add a `runSubagent`-absent
body-parity test; document `mode:` as OpenCode-scoped (ignored on VS Code); reconcile the README to what
D1 emits per the RFC §6c claims-commitment (orchestration story becomes **accurate**, narrator reframed
to first-class **without** dropping the redaction promise, flat-chain over-claims dropped, the correct
`~/.copilot/agents/` line protected); stop citing `notes/`; re-evaluate `_TARGET_ENFORCES_GATES`
(Copilot CLI `hooks` preToolUse now enforces; VS-Code-declarative remains non-enforcing); drop the
unsourced OpenCode `tools`-deprecation version.

### D9 — Reliability backstop: the implementer-adherence eval gates the cheap tier

Add an `evals/` scenario running the Sonnet 4.6 implementer against a thinker-produced plan, grading
adherence to `must_haves`. **Pass-bar: ≥ 90% of `must_haves` satisfied AND 0 critical-step failures**
(a critical-step failure = a missed acceptance check or a named-file/intent miss that breaks the plan's
truths). Below the bar = a regression in *either* the model tier *or* the doc quality; the eval blocks
keeping/shipping the cheap tier as default, and the same bar gates any future move to a cheaper default.
**Cadence: NOT a per-PR live-API call** — it runs nightly/on-demand against the live API (billed), and
CI replays a recorded transcript fixture for determinism. The documentation-quality contract is fixed:
choosing the cheaper implementer model does **not** license relaxing the accuracy or detail of generated
docs — the thinkers' output stays at the Opus bar regardless.

---

## Options Considered

### Option 1: One coherent platform refresh — native dispatch + per-agent model + 2 levels + 4 categories + first-class narrator + time-awareness (chosen)
- **Pros:** the six decisions are genuinely coupled (can't simplify the taxonomy without touching
  levels; can't make the narrator first-class without dropping R6; can't drop R6 without the taxonomy
  change); one seam, one ADR, one phased plan; every claim grounded in primary docs.
- **Cons:** large blast radius (config + scaffold + 3 test files + templates + statics); supersedes
  ADR-0005 in full.

### Option 2: Amend ADR-0005 in place
- **Pros:** less ceremony.
- **Cons:** **forbidden** — an accepted ADR is immutable (supersede, don't edit; ADR-0003 §D4 /
  ADR-0004). Four decisions change ADR-0005's load-bearing model, which is a new decision, not an edit.

### Option 3: Split into several small ADRs (one per decision)
- **Pros:** smaller records.
- **Cons:** creates artificial dependencies between records that share one seam and one rationale;
  reviewers confirmed the decisions are coupled. Rejected for the same reason ADR-0005 bundled D1–D7.

### Option 4: Keep `runSubagent` prose / `handoffs:` as the dispatch primitive
- **Pros:** zero change.
- **Cons:** `runSubagent` exists on no target; `handoffs:` is a UI-button surface, not programmatic
  dispatch. Rejected as factually broken.

### Option 5: Implementer tier = Haiku (the cheapest model)
- **Pros:** lowest cost.
- **Cons:** the reliability premise (a cheaper model must execute thinker docs faithfully) argues
  against the smallest model; `xhigh`/`max` error on Haiku. Rejected as default; Haiku is an opt-in via
  `models.overrides`, gated by the D9 eval.

---

## Rationale

The refresh is the only option that is simultaneously **correct, coherent, and honest**. Native dispatch
replaces a fiction with the targets' real primitives; the explicit fail-closed allowlist extends
ADR-0005's deny-by-default to the dispatch layer; dropping `loose` removes an "advisory that does
nothing" footgun; collapsing to 4 categories keeps the ask/gate/deny gradient while deleting the thin
secret category and the narrator-special-casing overlay. Crucially, making the narrator first-class did
**not** dissolve the redaction guarantee — naming the mechanism as an **enforced `gate`-tier handoff**
(rather than "a cross-cutting step") was the converged blocker the architect and narrator raised, and
the maintainer chose enforcement over advisory explicitly. The per-agent model is real where it can be
(the `model:` string); the per-agent *effort* is honestly documented as **not deliverable today**
(global-only), so the docs steer a single global default rather than promising a per-tier split the
targets don't support. Time-awareness is instruction-not-interpolation because Carter is a scaffolder
and interpolation poisons the cache. The D9 eval keeps the cheap-tier decision empirical, not a vibe.

---

## Consequences

### Positive
- Programmatic dispatch is **real** on VS Code and OpenCode (was fictional); the fail-closed lint keeps
  the maestro from delegating outside the vetted Carter crew.
- The strictness model is simpler (2 levels, 4 categories) with **no `loose` footgun** and a printed,
  enforceable per-agent allowlist.
- The narrator is first-class **without** losing the forced-redaction guarantee.
- Dated artifacts stop carrying guessed dates; `temperature` dead-weight is gone.
- Documentation-authoring runs on Opus while implementation can run on cheaper Sonnet, with the
  doc-quality contract protected by the D9 eval.

### Negative
- Large one-time blast radius: `config.py`, `scaffold.py`, all agent templates + statics, three test
  files (re-baselined, not patched), README + `docs/strictness-policy.md` + `docs/getting-started.md` +
  `frontmatter.md`.
- New config surface (`models:` block + model-name table) and a new lint + a new advisory to maintain.
- Per-target divergence persists: the same `gate` yields different real guarantees on different targets
  (surfaced, not hidden — D5/D8).

### Risks
- **Cheap-tier accuracy** — mitigated by Sonnet-not-Haiku + the fixed doc-quality contract + the D9 eval
  (≥90% must_haves, 0 critical-step failures). Residual: medium, watched by the eval.
- **Model-name drift** — a stale model string = a silently dead agent; mitigated by the sync marker +
  test (D2).
- **CI cost** — the D9 eval hits the live API; mitigated by nightly/manual cadence + a recorded CI
  fixture so per-PR CI stays offline.
- **Reliance on emitted-config correctness** — `carter check` lints config↔policy drift but cannot
  verify the platform denies at runtime (inherited from ADR-0005 §D2; explicitly out of scope).

---

## References

- RFC-0005 — Carter Agent Platform Refresh (record removed 2026-10) — the proposal this ADR records (revision 3, accepted 2026-06-26); carries the per-agent allowlist table, `file:line` grounding, and the §7 phased roadmap.
- [ADR-0005 — Risk-Based Strictness Policy](0005-risk-based-strictness-policy.md) — **superseded in full** by this ADR (`superseded_by: ADR-0010`).
- [ADR-0004 — RFC system](0004-rfc-system.md) — the RFC→ADR→plan chain (§D6) and the synthesis gate (§D5) this decision followed.
- Plan 005 — Agent platform refresh (private plan record, not in repo) — the execution plan decomposing P0–P4 + P4-eval.
- [Frontmatter reference](../reference/frontmatter.md) — canonical schema for the `policy`/`models` blocks and agent frontmatter.
