---
id: RFC-0005
status: accepted              # draft | review | accepted | rejected | withdrawn
revision: 3
created: 2026-06-26
decided: 2026-06-26
author: mauriciomem
adr: ADR-0010                 # ADR-NNNN produced by this RFC, when accepted
plan: 005-agent-platform-refresh   # NNN-slug plan that executes it, when created
supersedes: [RFC-0002]        # supersedes RFC-0002 (strictness) on acceptance — see §0
tags: [agents, orchestration, subagents, dispatch, models, strictness, policy, time, copilot, vscode, opencode]
---

# RFC-0005: Carter agent platform refresh — orchestration, models, two-level strictness, time-awareness

**Status:** Accepted (2026-06-26)
**Revision:** 3
**Author:** mauriciomem

> **Revision 3 (2026-06-26) — decision gate resolved; every open Q and review blocker folded in.** The maintainer answered all decision-gate items; r3 records them as decisions (not recommendations) and prints the artifacts reviewers said were missing. Changes from r2: (§1) `agents:` **and** `handoffs:` both emitted; **explicit** specialist list enforced by a **fail-closed `carter check` lint**; flat chain (`agents: []`); a **`/fleet` context-injection rule** for Copilot CLI. (§2) dedicated **`models:` block** with named precedence `overrides > tier > default`; **`temperature` dropped wholesale**; **`carter check` model advisory required**; Carter→target **model-name table** + sync marker + test; **single documented global effort = `high`** (per-session overridable; Carter emits no effort key). (§3) **`loose` fully purged** — no migration notice, no coercion branch. (§4) **4-category per-agent allowlist table printed** (the P2 spec); secret-access **merged** into `remote-write`. (§5) redaction mechanism **named: enforced** — substantive outward content is a **`gate`-tier narrator handoff** in the allowlist; `redaction.enabled` + the force-at-`guarded`/`strict` fix kept. (§6a) **per-target native-date check** + **required date-fetch checklist** in the skills. (§7) **time-awareness moved up**; **allowlist table is a hard P2 entry-gate**; **P4-eval pass-bar = ≥90% must_haves + 0 critical-step failures**, run nightly/manual with a recorded CI fixture. Every model claim re-verified against the bundled `claude-api` skill (cached 2026-06-04) this session; the model section holds.

> **Revision 2 (2026-06-26) — expanded from "native subagent orchestration" into the full agent-platform refresh** the maintainer scoped: (1) collapse strictness to two levels, (2) per-agent default model with override, (3) re-justify or simplify the risk taxonomy, (4) make every agent a first-class citizen (incl. narrator), (5) make Carter time-aware, plus a cross-cutting inconsistency/staleness audit. Every platform claim is **re-verified against primary docs, 26 June 2026**, and every model claim against the bundled `claude-api` skill (cached 2026-06-04). r1 (native dispatch only) is folded into §1.

> **Read this first if you are a fresh session.** This RFC is written to be executed cold.
> §0 says what it supersedes and what survives. §1–§5 are the five decisions, each with:
> *verified platform/model reality → decision → exact emission → open questions*. §6 is the
> staleness/inconsistency audit. §7 is the phased roadmap → plan. Do not trust `notes/`;
> trust this file's cited `file:line` + the primary-doc URLs in §References.

## 0. Relationship to RFC-0002 / RFC-0005-r1 (what dies, what survives)

RFC-0002 (Risk-Based Strictness Policy) is **accepted and frozen** (ADR-0004 §D4: supersede,
don't edit). This RFC, on acceptance, **supersedes RFC-0002 in full** and produces a new ADR,
because four of the five decisions below change RFC-0002's load-bearing model (levels, taxonomy,
narrator's special status) — not just extend it.

| RFC-0002 element | Status under RFC-0005 | Where |
|---|---|---|
| 3 levels `loose/guarded/strict` | **CHANGED** → 2 levels `guarded/strict` | §3 |
| 7-category risk taxonomy R0–R6 | **SIMPLIFIED** → 4 categories (RESOLVED, §4) | §4 |
| Narrator as the sole R6 author (special-cased) | **CHANGED** → all agents first-class | §5 |
| `policy:` block + `tools:`/`permission` emission + `carter check` lint | **KEPT**, re-tuned for 2 levels + new taxonomy | §3, §4 |
| Dispatch via `runSubagent` prose / `handoffs:` as "the" primitive | **REPLACED** by native `agent`/`agents:`/`permission.task` | §1 |
| per-agent model | **NEW** (RFC-0002 never addressed it) | §2 |
| time-awareness | **NEW** | §6 (§Time) |

**Why supersede rather than amend:** RFC-0002's §2 taxonomy, §3 allowlist, and the
`loose` level are woven through `carter/config.py`, `carter/scaffold.py`, and three test
files (27 `loose` references). A two-level model with a simplified taxonomy is not an
"edit" — it is a new decision that replaces the old one. ADR-0005 (which records RFC-0002)
gets a `superseded_by` pointer to the new ADR.

---

## 1. Native subagent orchestration (replaces the `runSubagent` fiction)

### Verified reality (primary docs, 26 Jun 2026)

| Platform | Programmatic dispatch primitive | Source |
|---|---|---|
| VS Code Copilot | `agent` tool in `tools:` **+** `agents: [...]` allowlist on the primary; specialists invocable unless `disable-model-invocation: true`; nesting depth ≤ 5 | [Subagents in VS Code](https://code.visualstudio.com/docs/copilot/agents/subagents) |
| Copilot CLI | `@`-mention (manual); `/fleet` for parallel orchestration (runtime, not frontmatter) | [/fleet docs](https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet) |
| OpenCode | Task tool + `permission.task` (glob-scoped, only on `mode: subagent`/`all` invokers); `@`-mention manual | [OpenCode agents](https://opencode.ai/docs/agents/) |

Three corrections to RFC-0002 §4 and the `notes/HANDOFF-005` framing, **both wrong on these**:
- **`handoffs:` is NOT programmatic dispatch.** It renders **user-approved UI buttons** after a
  response — guided sequential workflows, not model-initiated routing. Programmatic delegation is
  the **`agent` tool + `agents:`** allowlist (a *different* primitive). RFC-0002 conflated them.
- **The VS Code subagent tool is `agent`, not `runSubagent`.** `runSubagent` exists on no target.
- **`mode:` is OpenCode-only.** VS Code custom-agent frontmatter is `name/description/model/tools/handoffs/agents/disable-model-invocation/argument-hint` — **no `mode:`**. Carter emits `mode: primary/subagent` into VS Code files where it is silently ignored. VS Code's primary/subagent distinction comes from `agents:` + `disable-model-invocation`.

### What Carter emits today (the gap)

- [agents/carter-maestro.md:1-9](../../../agents/carter-maestro.md) — frontmatter = `description`, `mode: primary`, `temperature`, `policy`. **No `agent` tool, no `agents:`.**
- [carter/config.py](../../../carter/config.py) `policy_native_keys` emits only `tools` (MCP scope) + `permission` (opencode/edit,bash,webfetch). **No `agent`/`agents:`/`permission.task`.**
- `runSubagent` fiction at exactly two sites: [agents/carter-maestro.md:41](../../../agents/carter-maestro.md), [skills/carter-triage/SKILL.md:27](../../../skills/carter-triage/SKILL.md).

### Decision

Emit the real primitive per target, on the **primary** (maestro). All four sub-decisions below are
**resolved by the maintainer** (decision gate, r3) and are requirements, not recommendations.

```yaml
# VS Code / copilot target — maestro frontmatter
tools: ['agent']                 # enables programmatic subagent delegation
agents: [carter-architect, carter-engineer, carter-devops, carter-learner, carter-pm, carter-narrator]   # EXPLICIT list — never '*' or a glob (D1.2)
handoffs: [...]                  # ALSO emitted — user-approved confirm buttons for gate-tier actions (D1.1)
```
```yaml
# OpenCode target — maestro permission block (extends the existing one)
permission:
  task:                          # NEW
    '*': deny
    carter-architect: allow      # EXPLICIT per-specialist entries — NOT a 'carter-*' glob (D1.2)
    carter-engineer: allow
    carter-devops: allow
    carter-learner: allow
    carter-pm: allow
    carter-narrator: allow
```
Copilot CLI: document `/fleet` + `@`-mention; **no frontmatter change** (orchestration is runtime) —
but see **D1.D2** for the required context-injection rule.
Specialists stay invocable (no `disable-model-invocation`); their own `agents:` is **`[]`** so the
chain is exactly one level deep (D1.3).

Delete `runSubagent` at both sites; re-sync the static maestro body with the template (they drifted).

### Decisions (decision gate, r3 — all resolved)

- **D1.1 (was Q1.1) — RESOLVED.** Emit **both** `agents:` (programmatic routing) **and** `handoffs:`
  (user-approved confirm buttons) — `agents:` for routing, `handoffs:` as the confirm surface for a
  `gate`-tier action. Both keys ship on the maestro.
- **D1.2 (was Q1.2 / engineer E1) — RESOLVED, hard rule.** `agents:` (VS Code) and `permission.task`
  (OpenCode) are an **explicit per-specialist list**, never `'*'` and never a `carter-*` glob — a glob
  auto-trusts any future `carter-*`-named agent the user installs; `'*'` lets the maestro delegate to
  *any* workspace agent (failure-open, breaks deny-by-default). This is a **fail-closed** rule: a new
  `carter check` lint **errors (exits non-zero)** if the emitted `agents:`/`permission.task` on the
  primary is `'*'`, a glob, or absent. Not a warning — a build-breaking error (the §1 analog of
  RFC-0002's deny-by-default; closes E1).
- **D1.3 (was Q1.3) — RESOLVED.** Specialists carry **`agents: []`** — a **flat, one-level**
  delegation chain. The maestro is the only router; no specialist re-delegates. (VS Code permits depth
  ≤ 5; Carter does not use it.)
- **D1.D2 (was devops D2) — RESOLVED.** Because Copilot CLI `/fleet` subagents **do not inherit chat
  history**, the maestro's Copilot-CLI prose **must explicitly inject the active-plan + knowledge
  context into every `/fleet` prompt**. The maestro template loads that state at session bootstrap
  ([carter-maestro.md.j2:67-100](../../../templates/agents/carter-maestro.md.j2)); the `/fleet` prompt
  is the *only* channel that survives the `/fleet` boundary, so cross-domain `/fleet` runs would
  otherwise silently lose Carter's state. Example shape:
  ```
  /fleet carter-engineer "Implement plan 005 phase P3 (token refresh).
    Active plan: docs/plans/005-...md — must_haves: <inlined>.
    Relevant knowledge: <the context file the maestro loaded>.
    Acceptance: carter check passes; test_parity green."
  ```
  This is a required behavior in the maestro prose for the Copilot-CLI path, not a doc note.

---

## 2. Per-agent default model, with override (NEW)

> **The maintainer's intent:** Opus-tier (high reasoning) for the agents that *think and write
> documentation* (plans, RFCs, ADRs); a cheaper/faster model for the agents that *implement*.
> The cheaper model's output must be reliable — so the docs those thinkers produce must be
> precise enough that a more rudimentary model executes them accurately.

### ⚠️ Three verified constraints that reshape this feature

The maintainer named "**haiku 4.6 medium**" and "**opus 4.8 xhigh**". Against ground truth:

1. **"Haiku 4.6" does not exist, and Haiku is not the chosen tier.** Current Haiku is
   `claude-haiku-4-5`. **Decision (maintainer, confirmed): the implementer tier is `claude-sonnet-4-6`,
   not Haiku** — the reliability premise (below) argues against the smallest model. Sonnet 4.6 is the
   "cheap but accurate" tier ($3/$15 per MTok vs Opus $5/$25); Haiku remains an opt-in via
   `models.overrides` for users who accept the accuracy risk.
2. **Reasoning effort (`xhigh`/`medium`) is NOT settable per-agent on ANY target.** It's an
   Anthropic-API parameter (`output_config.effort`), and the agent frontmatter on all three targets
   has **no effort field**. Open feature requests confirm the gap: VS Code
   [microsoft/vscode#313546](https://github.com/microsoft/vscode/issues/313546), Copilot CLI
   [github/copilot-cli#2904](https://github.com/github/copilot-cli/issues/2904). Effort is
   **global-only** (CLI `--effort`, user config). **So neither "opus 4.8 xhigh" nor "sonnet medium"
   is expressible as per-agent frontmatter today.** Carter can pin the *model* per agent; it
   **cannot** pin the *effort* per agent. Carter records the recommended efforts — thinkers `xhigh`,
   implementers `medium` (both valid on their respective models; Sonnet 4.6 supports `medium`) — as a
   **global recommendation** applied via the CLI flag, until the targets ship per-agent effort (the
   open issues above). Note `xhigh`/`max` **error on Haiku** (Opus-tier only) — a further reason the
   chosen implementer is Sonnet, where `medium` is valid.
3. **`model:` value is platform-shaped, and array form is not portable.**
   - VS Code accepts a **display name** (`"Claude Opus 4.5"`) and even an **array** with fallbacks
     (`model: ['Claude Opus 4.5', 'GPT-5.2']`).
   - **Copilot CLI rejects the array form** ([github/copilot-cli#2133](https://github.com/github/copilot-cli/issues/2133)) — parse error / first-entry-only.
   - OpenCode uses `provider/model` IDs (e.g. `anthropic/claude-opus-4-8`).
   - The model must exist in the user's Copilot/OpenCode subscription — Carter can't guarantee a given model is available.

### Decision

Add a config-driven, per-agent **model** map in a **dedicated `models:` block** (no effort — effort is
out of Carter's reach). The block is orthogonal to `policy:` (D2.1).

```yaml
# carter.yaml
models:
  default:      { copilot: "Claude Opus 4.8",   opencode: "anthropic/claude-opus-4-8" }   # catch-all for any agent not in a named tier
  thinkers:     { copilot: "Claude Opus 4.8",   opencode: "anthropic/claude-opus-4-8" }   # maestro, architect, pm, learner, narrator
  implementers: { copilot: "Claude Sonnet 4.6", opencode: "anthropic/claude-sonnet-4-6" } # engineer, devops (Sonnet, not Haiku)
  overrides: {}    # per-agent: {engineer: {copilot: "Claude Haiku 4.5", opencode: "anthropic/claude-haiku-4-5"}}  (Haiku is opt-in here)
```

**Resolution order (D2.1 / architect A3) — `overrides` > tier > `default`:** to pick an agent's model,
(1) use `models.overrides[<agent>]` if present; else (2) use the agent's tier (`thinkers` /
`implementers`); else (3) fall back to `default`. `default` is the **un-tiered catch-all** — it is what
a future agent that belongs to no named tier resolves to, so an agent never resolves to an empty/missing
model string.

- **Role→tier map** (shipped, dict-shaped so `_deep_merge` doesn't wipe it — same footgun RFC-0002 §1 documented): thinkers = {maestro, architect, pm, learner, narrator}; implementers = {engineer, devops}. User-overridable via `models.overrides` (where a user may opt into Haiku if they accept the accuracy risk).
- **Emit a per-target `model:` string** in each agent's frontmatter (single string, **not** array —
  the array form breaks Copilot CLI). VS Code/Copilot get the display name; OpenCode the provider ID.
- **Effort is NOT emitted and Carter ships no effort key** (D2.D1). No target has a per-agent effort
  field, so there is nothing to emit. Effort is a **per-session, global** knob the user sets on their
  harness (`copilot --effort high`, a VS Code/OpenCode setting), mapping to the Anthropic API's
  `output_config.effort`. Carter's docs recommend **`high`** as the default all-rounder and tell the
  user to **raise it per-session** (e.g. `xhigh`) for thinker-heavy work (RFC/ADR/plan authoring) and
  may lower it for routine implementation. See D2.D1 for why `high` (not `xhigh`/`medium`) is the
  documented default. (`temperature` is dropped entirely — D2.6.)

### The reliability premise (maintainer's hard requirement)

"A more rudimentary LLM must perform with extreme accuracy of what it's told." This is a
**documentation-quality contract**, not just a model choice. **Maintainer directive (confirmed):
choosing the cheaper implementer model does NOT license relaxing the accuracy or detail of generated
documentation** — the thinkers' output must be as precise and complete as if Opus were executing it.
The cheaper tier is justified *only* because the thinker-produced docs are good enough to execute
faithfully, never by lowering the bar on those docs.
- The thinker agents' output templates (plan/RFC/ADR) must produce **executable, unambiguous,
  step-level** instructions — `must_haves`, explicit file paths, acceptance checks — exactly what
  [docs/reference/frontmatter.md](../../reference/frontmatter.md) `must_haves` already enforces. This
  bar **stays fixed** regardless of which model executes.
- The implementer agents' templates should be **checklist-driven** and lean on the thinkers'
  artifacts rather than re-deriving intent — they consume precise docs, they do not get terser docs.
- **Validation (decided):** add an `evals/` scenario that runs the **Sonnet 4.6** implementer tier
  against a thinker-produced plan and grades adherence. This empirically backs the Sonnet choice and
  guards the contract — a drop in adherence is a regression in *either* the model tier or the doc
  quality, and the eval catches both (Q2.5). It also gates any future move to a cheaper tier (e.g.
  Haiku opt-in): no cheaper tier ships as default until it clears the same adherence bar.

### Decisions (decision gate, r3 — all resolved)

- **D2.1 (was Q2.1 / architect A3) — RESOLVED.** Per-target model string lives in a **dedicated
  `models:` block** (orthogonal to `policy:`), not folded into `policy_native_keys`. Precedence is
  named: **`overrides` > tier > `default`** (above).
- **D2.2 (was Q2.2 / devops note) — RESOLVED.** Maintain a small **Carter→target model-name table**
  (display name for Copilot, e.g. `claude-opus-4-8` ⇄ "Claude Opus 4.8"; `provider/model` ID for
  OpenCode, e.g. `anthropic/claude-opus-4-8`). Treat it like the MCP server-name mapping: **one home**,
  a **`MODEL LAUNCH`-style sync marker** so the next model bump updates it, and a **test** asserting the
  mapping is **non-empty for every shipped role**. A wrong/stale string = a silently dead agent (D2.3);
  the marker + test guard against that.
- **D2.3 (was Q2.3 / engineer E2) — RESOLVED, required advisory.** Carter **emits the pinned `model:`
  anyway** (it cannot verify the user's Copilot/OpenCode subscription), **and** `carter check` prints a
  **required advisory**: *"agent X pins model Y; Carter cannot verify your subscription includes it"*.
  The advisory is a real, always-on `carter check` output — not optional — so "emit + advisory" is
  honest (closes E2; without it, an unavailable model = silently ignored frontmatter = a broken agent).
- **D2.4 (was Q2.4) — RESOLVED (carried).** Implementer tier = **Sonnet 4.6** (not Haiku). Haiku is an
  opt-in via `models.overrides`. The accuracy/detail of generated docs stays at the Opus bar regardless.
- **D2.5 (was Q2.5) — RESOLVED (carried).** Add the `evals/` adherence scenario (Sonnet implementer vs
  thinker plan). It backs the Sonnet choice and gates any future cheaper-tier default (pass-bar in §7).
- **D2.6 (was Q2.6 / engineer E3) — RESOLVED, drop wholesale.** **`temperature` emission is dropped
  entirely** on all agents and all targets, and its parity-test assertion ([test_parity.py:141](../../../tests/test_parity.py))
  is removed. Effort/temperature are documented as **runtime-owned**. The precise reason (correcting
  S4's framing): **VS Code custom-agent frontmatter does not recognize `temperature` at all** (silently
  ignored), while **OpenCode *does* accept `temperature` as a valid frontmatter field — but the
  Anthropic models Carter pins reject it at the API**: Opus 4.8/4.7 & Fable 5 **400** on `temperature`,
  and Sonnet 4.6 (the implementer tier) also removed the sampling params. So `temperature` is dead or
  harmful on **every** target × model combination Carter ships — there is no configuration in which
  emitting it helps. Dropping it loses no working behavior.
- **D2.D1 (was devops D1) — RESOLVED, operational truth stated.** Per-agent effort is **not deliverable
  today** — a Carter session has **one** global `--effort`, and the per-agent feature is unshipped (open
  issues [microsoft/vscode#313546](https://github.com/microsoft/vscode/issues/313546),
  [github/copilot-cli#2904](https://github.com/github/copilot-cli/issues/2904)). Only the per-tier
  **model** is real today; the per-tier *effort* split (thinkers `xhigh` / implementers `medium`) is
  **aspirational** pending those issues. The docs recommend a **single global default of `high`** — the
  safe all-rounder: it works even when a user opts into a Haiku override (`xhigh`/`max` **error on
  Haiku**), does not over-spend on implementers (as `xhigh` would), and does not under-serve the
  Opus-tier thinkers writing plans/RFCs/ADRs (as `medium` would). Effort is **per-session overridable**
  via the harness flag — the docs tell the user to raise to `xhigh` for thinker-heavy sessions. Carter
  emits no effort key (D2 / §2 Decision).

---

## 3. Two strictness levels: drop `loose` (CHANGED from RFC-0002's three)

### Current state

`POLICY_LEVELS = ("loose", "guarded", "strict")` ([config.py:199](../../../carter/config.py)).
`loose` = "advisory only, nothing blocks" and is the **default for existing/omitted configs** (Q6 in
RFC-0002), while new installs get `guarded`. `loose` appears 27× across config.py, scaffold.py, and
`tests/test_config.py` / `test_policy_lint.py` / `test_scaffold.py`.

### Decision: `POLICY_LEVELS = ("guarded", "strict")` — and **`loose` is fully purged**

- **`guarded`** becomes the floor and the default for *everything* (new and existing/omitted).
- **`strict`** unchanged in intent (R3/R5 → deny; hard-ack on non-enforcing targets).
- **Total purge (D3.1) — no migration notice, no coercion branch.** `loose` is removed from **all
  shipped surfaces**: `POLICY_LEVELS`, `RISK_TAXONOMY` (the `loose` column), `DEFAULT_CONFIG`,
  `_emit_level`, `scaffold.py` (the `config_warnings`/`policy_notice` `loose` branches), every template
  and static, the README, `docs/strictness-policy.md`, `docs/getting-started.md`, and the three test
  files. There is **no `loose`-specific migration notice and no `loose`→`guarded` coercion branch** —
  `loose` simply ceases to exist in Carter's vocabulary. The default for an omitted/unknown `policy`
  block is `guarded` via the normal default path; a stale `level: loose` left in a user's own
  `carter.yaml` from a prior install resolves to the `guarded` default through that same path (no
  dedicated handling, no message). **Scope note:** the purge touches **live** surfaces only — the
  archived completed-plan records under `design/plans/completed/002-*` are **left intact as history**
  (they record RFC-0002 as it was; rewriting a completed archive would falsify the record).

### Why this is coherent

`loose` only ever existed for backward-compatibility with pre-policy installs (RFC-0002 Q6). With the
policy shipped and a year of installs on it, the "no behaviour change" carve-out has served its
purpose. Two levels = simpler mental model, one fewer column in every taxonomy table, and removes the
"advisory that does nothing" footgun where users think they're protected and aren't.

### Code/test surface to change (exhaustive)
- [config.py:199](../../../carter/config.py) `POLICY_LEVELS`; the `RISK_TAXONOMY` `loose` column (drop it); `DEFAULT_CONFIG["policy"]["level"]` → `guarded`; `generate_default_config` (the `guarded` bump becomes a no-op).
- [scaffold.py:99-100,118-119](../../../carter/scaffold.py) `config_warnings`/`policy_notice` `loose` branches.
- `_validate_policy` error message (lists valid levels).
- `tests/test_config.py` (6), `tests/test_policy_lint.py` (7), `tests/test_scaffold.py` (14) — re-baseline; add a `loose`→`guarded` migration test.
- Docs: [docs/strictness-policy.md](../../strictness-policy.md), [docs/getting-started.md](../../getting-started.md), [README.md:142-146](../../../README.md), [frontmatter.md](../../reference/frontmatter.md).

### Decisions (decision gate, r3)
- **D3.1 (was Q3.1) — RESOLVED.** No migration UX, because there is nothing to migrate *to* a named
  state: `loose` is purged outright (above). No auto-map notice, no hard-error — an absent/legacy level
  resolves to the `guarded` default silently. (Maintainer: "there must be no trace of `loose`.")
- **Q3.2 — RESOLVED (sequencing).** Dropping `loose` interacts with the simplified taxonomy (§4) — the
  gate map is re-derived for **2 levels × 4 categories together** in P2 (after P1 lands the level
  change). §7 honors this (P1 before P2).

---

## 4. Do we even need the risk taxonomy? (SIMPLIFY)

### What the taxonomy is *for* (the honest answer)

The 7-category R0–R6 taxonomy ([config.py:202-210](../../../carter/config.py)) exists to answer one
question per action: **"silent / ask / handoff / deny?"** It buys three things:
1. A **per-agent allowlist** (deny-by-default): a category absent for an agent is denied for it — this
   is what encodes "devops is the only pusher", "engineer can't remote-write."
2. A **level→gate map** so one `policy.level` knob re-gates everything.
3. **Native emission**: OpenCode `permission` bash-globs + `tools:`/`permission` allowlists derive
   from it ([config.py:347-388](../../../carter/config.py)).

So the taxonomy *is* worth something — it's the join key between "which agent" and "how strict." The
question is whether **seven** categories earn their complexity. Evidence they don't:
- R6 (external-publish) is an **overlay**, not a transport category — it already breaks the "exactly
  one category" rule (RFC-0002 D1) and special-cases the narrator (which §5 removes).
- R4 (secret-access) maps to one tool entry (`read .env`, `vault read`) — thin.
- The gate vocabulary has four tiers (`allow/ask/gate/deny`) but OpenCode collapses `gate`→`ask`
  ([config.py:309-314 `_OPENCODE_GATE`](../../../carter/config.py)) — so on OpenCode `gate` resolves to
  `ask`. (`gate` is **not** cosmetic, though: §5 makes the redaction handoff a real `gate`-tier
  allowlist entry, enforced per-target to the extent each target enforces gates — see §5 and the S7
  re-eval of `_TARGET_ENFORCES_GATES`.)

### Decision (RESOLVED — decision gate, r3): collapse to **4 categories**

| New | Folds in (old) | guarded | strict |
|---|---|---|---|
| **read** | R0 | allow | allow |
| **local-write** | R1 | allow | allow |
| **remote-write** | R2 + R4 merged in — secret-access rides remote/infra paths (D4.2) | ask | gate |
| **dangerous** | R3 infra-mutate + R5 destructive | gate | deny |

- **R6 external-publish is dropped as a category** and handled by §5 (redaction is enforced via a
  `gate`-tier narrator handoff in the allowlist, not via an R6 overlay — see §5).
- **Secret-access (old R4) is merged into `remote-write`** (D4.2) and the standalone category is
  deleted. A secret read (`read .env`, `vault read`) is classified `remote-write` — it gates
  identically (`ask` at `guarded`, `gate` at `strict`), so merging it away loses no protection.
- Gate vocabulary stays `allow/ask/gate/deny` (cheap, already wired).
- The **per-agent allowlist** survives — it's the genuinely valuable half. The table below is the
  **P2 spec** (D4.A1), not a description; a category **absent** for an agent is **denied** for it
  (deny-by-default).

### The 4-category per-agent allowlist (P2 spec — D4.A1)

This is the join key between "which agent" and "how strict," and it is a **hard entry-gate for P2**
(§7 R2). A category not listed for an agent is denied for that agent.

| Agent | `read` | `local-write` | `remote-write` | `dangerous` |
|---|:---:|:---:|:---:|:---:|
| **maestro** | ✅ | — | — | — |
| **architect** | ✅ | — | — | — |
| **learner** | ✅ | — | — | — |
| **pm** | ✅ | ✅ | — | — |
| **narrator** | ✅ | ✅ | — | — |
| **engineer** | ✅ | ✅ | — | — |
| **devops** | ✅ | ✅ | ✅ | ✅ |

**Invariants this encodes:**
- **`devops` is the sole holder of `remote-write` and `dangerous`** — the single-pusher invariant,
  enforced by the allowlist (not by an R6 overlay). Nothing else can push to a remote or run a
  destructive/infra-mutating action.
- **`engineer` cannot `remote-write`** — implements locally, hands off to devops to transmit.
- **`pm` gets `local-write`** — it scaffolds/updates plan documents (D4.A1, maintainer).
- **`narrator` gets `read, local-write` but NOT `remote-write`** — it *authors* outward content
  locally and reaches `remote-write` only via the **`gate`-tier handoff to devops** (§5). Narrator is
  first-class (§5) but is not a second pusher.

### Alternative considered (for the review)
- **Keep 7** — least churn, but carries R4/R6 weight the simplification removes.
- **Collapse to 2** (`safe` = read+local-write allow always; `risky` = everything else, gated) —
  simplest, but loses the ask-vs-deny gradient that makes `guarded` ≠ `strict` meaningful.
- **Recommend 4** as the balance: keeps ask/gate/deny gradient, drops the overlay and the thin
  secret category, halves the table.

### Decisions (decision gate, r3 — all resolved)
- **D4.1 (was Q4.1) — RESOLVED (carried).** Collapse to **4 categories** (`read`, `local-write`,
  `remote-write`, `dangerous`). The per-agent allowlist (table above) is retained; R6 overlay dropped (→ §5).
- **D4.2 (was Q4.2) — RESOLVED, merge.** Secret-access (old R4) is **merged into `remote-write`** and
  the standalone category is deleted. It gates identically (`ask`/`gate`), so the merge under-protects
  nothing — a secret read at `guarded` still `ask`s. (Maintainer: condense, merge, remove the leftover.)
- **D4.3 (was Q4.3) — RESOLVED.** With R6 gone, redaction's gate is the **`gate`-tier narrator handoff
  in the allowlist** (§5, enforced) — not an overlay.
- **D4.A1 (was architect A1) — RESOLVED.** The 4-category per-agent allowlist table (above) is printed
  as the **P2 spec**, with `pm` = `{read, local-write}` and `narrator` = `{read, local-write}` (no
  `remote-write`; single-pusher = devops only).

---

## 5. All agents are first-class citizens (incl. narrator) (CHANGED)

### Current special-casing of the narrator

- It's the **sole R6 author** ([config.py:243,234-235](../../../carter/config.py)); R6's whole
  existence is "route outward content to narrator."
- Maestro hard-wires a **narrator→devops handoff** for outward content ([carter-maestro.md.j2:188-193](../../../templates/agents/carter-maestro.md.j2)).
- Redaction rules are gated on `redaction.enabled` and the narrator renders empty without them
  (RFC-0002 §6 leak; [scaffold.py:88-106](../../../carter/scaffold.py)).
- `AGENT_MCP_SCOPE["narrator"] = []` and `AGENT_MCP_SCOPE["maestro"] = []` — narrator is treated as a
  no-MCP author, an exception in the scope table ([config.py:297-305](../../../carter/config.py)).

### Decision: narrator becomes a normal specialist; redaction is **ENFORCED** via a gate-tier handoff

The narrator is made first-class **without** dissolving the redaction guarantee. The mechanism is
**named explicitly** (decision gate, r3 — this is the converged blocker A2 + N1 raised, and reviewers
required a named mechanism rather than "a cross-cutting step"):

- **Drop R6 as a narrator-only category** (already done in §4). The narrator is "the external-content
  specialist" the same way the architect is "the design specialist" — Maestro routes to it by domain
  (the routing table already lists it), not by a special overlay rule. Narrator participates in dispatch
  like every other specialist (§1 `agents:` list includes it).
- **Redaction is ENFORCED, not advisory (D5.A2/N1).** At `guarded`/`strict`, **substantive** outward
  content (release notes, PR descriptions, Jira/Slack bodies, announcements) **must** route through the
  narrator as a **`gate`-tier handoff encoded in the allowlist** — not a routing convention, not prose.
  The narrator applies its redaction pass and hands the redacted content to **devops** (the sole
  `remote-write` holder) to transmit. **Short-form one-liners** (a one-line commit note, "LGTM") stay
  **`ask` + an inline redaction check** (the old D3 lane), not a full gate. This preserves RFC-0002's
  **forced-pass** guarantee — the exact enforcement RFC-0002 spent three rounds establishing — rather
  than silently downgrading it to advisory prose.
- The single-pusher invariant falls out of the §4 allowlist: only devops holds `remote-write`, and
  narrator holds `local-write` only, so "narrator drafts + redacts → devops transmits" is structural,
  not an R6 overlay. The `gate`-tier handoff is the **enforcement point** where the redaction pass is
  forced before content can reach `remote-write`.

> **`gate` is enforced where the target enforces gates.** On OpenCode `gate`→`ask` ([config.py:309-314
> `_OPENCODE_GATE`](../../../carter/config.py)) and on VS-Code-declarative the gate is a hard
> acknowledgement, per RFC-0002's enforcement-honesty rules (the same `_TARGET_ENFORCES_GATES` reality,
> re-evaluated in S7). The point of D5.A2/N1 is that the redaction pass is a **named gate in the
> allowlist**, not advisory prose — Carter emits it as a gate and each target enforces it to the extent
> it enforces any gate. This is the honest position: enforced as a gate, with the same per-target
> enforcement caveat every gate already carries.

### Why this is better

The R6 overlay was the single most complex part of RFC-0002 (D1/D3 "two-lane", "compose not collide").
Making the narrator a normal specialist and expressing redaction as a **`gate`-tier handoff in the
allowlist** deletes the overlay complexity while **keeping the actual guarantee** (substantive outward
content is forced through redaction; devops is the only pusher) — instead of trading the guarantee away.

### Decisions (decision gate, r3 — all resolved)
- **D5.A2/N1 (was Q4.3 / Q5.1 / architect A2 / narrator N1) — RESOLVED: ENFORCED.** The mechanism is
  named: substantive outward content **must** route through the narrator as a **`gate`-tier handoff in
  the allowlist** at `guarded`/`strict`; short-form one-liners = `ask` + inline check. Not a routing
  convention; not advisory prose. (Maintainer chose enforced over advisory — N1's required position.)
- **D5.2 (was Q5.2) — RESOLVED, keep.** Keep the `redaction.enabled` config **and** the force-the-pass
  fix at `guarded`/`strict` (the RFC-0002 Q16 leak fix: at `guarded`/`strict` the redaction pass is
  forced regardless of the `redaction.enabled` flag, and `carter check` warns on the
  `redaction.enabled: false` contradiction — [scaffold.py:237-240](../../../carter/scaffold.py)). This
  fix is independently valuable and now decoupled from the dropped R6 — it just no longer hangs off R6.

---

## 6. Cross-cutting: time-awareness, plus the inconsistency / staleness audit

### 6a. Time-awareness (NEW)

**Verified gap:** Carter agents have **zero runtime time-awareness.** Every `datetime` use is
installer/ops plumbing — backup dir stamps ([installer.py:314-315](../../../carter/installer.py)),
`carter save` ([cli.py:290](../../../carter/cli.py)), ops audit timestamps
([ops/carter_ops.py](../../../carter/ops/carter_ops.py)), plan-date validation
([plans.py](../../../carter/plans.py)). **Nothing injects "today's date" into any agent.** Yet agents
author dated artifacts — ADRs/RFCs/plans carry `created:`/`decided:`/`updated:` dates
([frontmatter.md](../../reference/frontmatter.md)) — and have a training cutoff, so they cannot know
the current date unaided. (This very session: the maintainer had to *tell* the assistant "today is
26 June 2026.")

**The hard constraint:** Carter is a **scaffolder, not a runtime** — it can't inject a live clock
into the agent's context at conversation time (the same constraint RFC-0002 §Summary documents for
enforcement). So time-awareness must come from the **target's** mechanism or from a **deterministic
instruction**, not from Carter inserting a timestamp (which would also break prompt caching — see the
`claude-api` prompt-caching guidance: `datetime.now()` in a system prompt is a silent cache
invalidator).

**Decision (decision gate, r3 — resolved):**
1. **Instruction, not interpolation.** Carter's global instructions
   ([instructions/copilot-instructions.md](../../../instructions/copilot-instructions.md)) and the
   plan/RFC/ADR skills tell agents to **obtain the current date from a tool/the environment** (e.g.
   run `date`, or read it from the harness) **before writing any dated frontmatter** — rather than
   guessing from training. This is target-agnostic and cache-safe.
2. **Carter-side stamping where Carter owns the write.** `carter init`/`save`/ops already have real
   clocks — anywhere Carter *itself* writes a dated field, stamp it deterministically (mostly already
   true; audit for gaps).
3. **Do NOT** bake `Today is <date>` into agent frontmatter/templates — it's stale the moment it's
   rendered and it poisons the cache.
4. **Per-target native-date check (D6a.1).** The implementing session **verifies, per target** (VS
   Code / Copilot CLI / OpenCode), whether the harness exposes a native "current date" to agents (a
   system var). Where a target injects date context natively, **prefer that** over the `date`-tool
   instruction; fall back to the fetch instruction where it doesn't. (Note: this very session's harness
   *did* inject a `currentDate` — yet it was still verified against `date` before use, per §6a's own
   rule. Native-where-present, fetch-otherwise.)
5. **Required date-fetch checklist item (D6a.2).** The `carter-plan` / `carter-rfc` / `carter-adr`
   skills carry a **required checklist item**: fetch the current date (native var or `date`) **before
   writing any dated frontmatter**. A dated artifact cannot be authored with a training-cutoff guess —
   this is exactly the bug §6a exists to fix.

### Decisions (decision gate, r3 — all resolved)
- **D6a.1 (was Q6a.1) — RESOLVED.** Verify per target whether a native current-date is exposed; prefer
  native where it exists, else the `date`-fetch instruction. (Item 4 above.)
- **D6a.2 (was Q6a.2) — RESOLVED.** Date-fetch is a **required checklist item** in the
  `carter-plan`/`carter-rfc`/`carter-adr` skills. (Item 5 above.)

### 6b. Inconsistency & staleness audit (findings to fix in the plan)

| # | Finding | Evidence | Fix |
|---|---|---|---|
| S1 | **`runSubagent` fiction** — tool name exists on no platform | [carter-maestro.md:41](../../../agents/carter-maestro.md), [carter-triage/SKILL.md:27](../../../skills/carter-triage/SKILL.md) | §1 — delete, emit `agent`/`agents:` |
| S2 | **`mode:` emitted into VS Code files is ignored** (OpenCode-only field) | all 7 statics + templates carry `mode:` | §1 — keep for OpenCode, document it's OpenCode-scoped; VS Code uses `agents:`/`disable-model-invocation` |
| S3 | **static `.md` ↔ template drift** — static maestro says `runSubagent`, template says "chain sequentially" | [carter-maestro.md:41](../../../agents/carter-maestro.md) vs [carter-maestro.md.j2:51](../../../templates/agents/carter-maestro.md.j2) | re-sync; add a body-parity test for `runSubagent` (the existing body tests at [test_parity.py:172-220](../../../tests/test_parity.py) cover `read-only`/`full access` only) |
| S4 | **`temperature:` is rejected by every model Carter pins** — Opus 4.8/4.7 & Fable 5 **400** on `temperature`; Sonnet 4.6 (implementer tier) also removed sampling params; it's emitted on every agent and *tested* as required ([test_parity.py:141](../../../tests/test_parity.py)). **Precise layering (corrects S4's r2 framing):** VS Code custom-agent frontmatter does **not recognize** `temperature` (silently ignored); OpenCode **does** accept it as a valid frontmatter field, but the pinned Anthropic models reject it at the API one layer down. | all agents emit `temperature` | **RESOLVED (D2.6): drop `temperature` emission wholesale** on all agents/targets and **remove the parity assertion** ([test_parity.py:141]); document effort/temperature as **runtime-owned**. No target × model combination Carter ships benefits from emitting it. |
| S5 | **README over-claims** — "routes… and chains specialists" / auto-dispatch diagram ship nowhere | [README.md:11,57,70-82,86](../../../README.md) | reconcile to what §1 actually emits — **with the explicit claims-commitment in §6c below (narrator N2)**: which README claims survive, become accurate, or are dropped. |
| S6 | **README troubleshooting row is actually correct** (HANDOFF-005 wrongly flagged it) — `~/.copilot/agents/` IS a VS Code user-profile location | [README.md:221](../../../README.md) | leave as-is; note in plan so a future session doesn't "fix" a correct line |
| S7 | **`_TARGET_ENFORCES_GATES = {opencode: True, copilot: False}`** predates Copilot CLI `hooks` (preToolUse can deterministically block) | [scaffold.py:142](../../../carter/scaffold.py) | re-evaluate: copilot-CLI is no longer purely non-enforcing; VS-Code-declarative remains non-enforcing |
| S8 | **`loose` level** — backward-compat carve-out, now removed | 27 refs across config/scaffold/tests (live surfaces) | §3 — **purge entirely** (D3.1); no notice, no coercion. Archived `design/plans/completed/002-*` left intact as history. |
| S9 | **R6 overlay complexity / narrator special-casing** | [config.py:234-243](../../../carter/config.py) | §4/§5 — R6 dropped; redaction re-expressed as a **`gate`-tier handoff in the allowlist** (enforced, D5.A2/N1). |
| S10 | **`notes/` is stale and partly wrong** (HANDOFF-005 Finding 1 false; the user said don't trust notes) | `notes/HANDOFF-005-*.md` | the plan should not cite `notes/`; cite this RFC + primary docs |
| S11 | **OpenCode `tools` boolean deprecation has no sourced version** (RFC-0002 said "≥v1.1.1") | RFC-0002 §4 | drop the version; emit `permission` (already correct) |

### 6c. README claims-commitment (narrator N2 — RESOLVED)

S5 said only "reconcile to what §1 emits." N2 required a commitment to **which** claims survive, so the
narrator isn't guessing when it drafts the copy. r3 commits:

- **Survives, now ACCURATE (not aspirational):** the orchestration story. Once §1 ships, programmatic
  dispatch on VS Code (`agent`+`agents:`) and OpenCode (`permission.task`) is **real** — the
  auto-routing framing at [README.md:11,57,70-82](../../../README.md) becomes accurate and **stays**;
  it is re-landed as "accurate," not deleted. Copilot CLI orchestration is `/fleet`/`@`-mention
  (runtime), described as such.
- **Reframed:** the agent table ([README.md:86-97](../../../README.md)) currently frames the narrator
  via a "external content, redaction" **special role**. Reframe it to **first-class-specialist**
  language consistent with §5 ("the external-content specialist the way the architect is the design
  specialist") **without dropping the redaction-on-outward-paths promise** — the `gate`-tier handoff
  (D5.A2/N1) is the promise, stated plainly. (N1's one-liner is a good candidate for the copy verbatim:
  "any agent can read; the learner specializes in explaining" → "any agent can draft; the narrator
  specializes in redacted outward content.")
- **Dropped/corrected:** any claim that overshoots what §1 emits (e.g. a chaining diagram implying
  multi-level delegation — the chain is **flat**, D1.3).
- **Left as-is (do NOT "fix"):** the `~/.copilot/agents/` troubleshooting row (S6) is **correct** — it
  is a real VS Code user-profile location. A future session must not "correct" a correct line.
- **Owner:** the narrator drafts the agent-table + strictness-section copy when this lands; the RFC's
  commitment above is what it drafts against.

---

## 7. Phased roadmap → execution plan

Each phase is independently shippable and test-gated. Order chosen so the highest-impact, lowest-risk
corrections land first and the model-reliability eval (the riskiest) gates the cheap-model rollout.

> **Sequencing change (r3, pm R1):** time-awareness moves **up** to ride with P0 — it fixes a live
> correctness bug (dated artifacts are wrong *today*), is independent, and low-risk. It is no longer
> the last phase.

- **P0 — staleness fixes + time-awareness (no behaviour change):** delete `runSubagent` (S1), re-sync
  static↔template (S3) + add `runSubagent` body-parity test, reconcile README per the §6c claims-
  commitment (S5/N2), document `mode:` as OpenCode-scoped (S2), **drop `temperature` emission wholesale
  + remove its parity assertion** (S4/D2.6), stop citing `notes/` (S10). **Plus time-awareness (§6a,
  R1):** date-fetch instruction in global instructions + the required date-fetch checklist in
  `carter-plan`/`carter-rfc`/`carter-adr` (D6a.2), the per-target native-date check (D6a.1), audit
  Carter-side stamping, verify no template bakes a literal date. Pure correctness.
- **P1 — two-level strictness (§3):** `POLICY_LEVELS` → `(guarded, strict)`, default `guarded`,
  **`loose` purged entirely — no migration notice, no coercion branch** (D3.1); re-baseline the 3 test
  files (no `loose` migration test — there is no migration). Archived `design/plans/completed/002-*`
  left untouched. Self-contained.
- **P2 — simplify taxonomy + first-class narrator (§4, §5):** collapse to 4 categories, merge
  secret-access into `remote-write` (D4.2), drop R6 overlay, re-express redaction as the **`gate`-tier
  narrator handoff in the allowlist** (enforced, D5.A2/N1), keep `redaction.enabled` + the
  force-at-`guarded`/`strict` fix (D5.2), re-derive `RISK_TAXONOMY`/`AGENT_ALLOWLIST`/bash-globs/lint
  from the **printed allowlist table (§4)**. Biggest model change — do after P1 so the level change is
  absorbed. **Hard entry-gate (pm R2): P2 may not start until the 4-category allowlist table is in the
  RFC** — it now is (§4, D4.A1), so the gate is satisfied.
- **P3 — native dispatch (§1):** emit `agent`+`agents:` **and** `handoffs:` (copilot, D1.1) and
  `permission.task` (opencode) — **explicit per-specialist lists, never `'*'`/glob** (D1.2); flat chain
  `agents: []` (D1.3); the **`/fleet` context-injection rule** in the maestro Copilot-CLI prose
  (D1.D2); extend `policy_native_keys` + parity for the new keys; **add the fail-closed `carter check`
  lint** that errors when the primary emits `'*'`/glob or omits the key (D1.2).
- **P4 — per-agent model (§2):** dedicated **`models:` block** with `overrides > tier > default`
  precedence (D2.1), role→tier map, per-target `model:` emission (single string, not array), the
  Carter→target **model-name table + `MODEL LAUNCH` sync marker + non-empty-per-role test** (D2.2);
  **required `carter check` advisory** when a model can't be verified (D2.3). Effort/`temperature` not
  emitted; effort documented as global `high`, per-session overridable (D2.D1). **Gated on P4-eval.**
- **P4-eval — reliability backstop (§2 D2.5):** an `evals/` scenario running the **Sonnet 4.6**
  implementer tier against a thinker-produced plan, grading adherence to `must_haves`. **Pass-bar (R3):
  ≥ 90% of `must_haves` satisfied AND 0 critical-step failures** — where a *critical-step failure* is a
  missed acceptance check or a named-file/intent miss that breaks the plan's truths. Below the bar = a
  regression in *either* the model tier *or* the doc quality, and the eval blocks keeping/shipping the
  cheap tier. **Cadence (R3 / devops): this is NOT a per-PR live-API call** — it runs **nightly or
  on-demand against the live API** (billed), and **CI replays a recorded transcript fixture** for
  determinism, so per-PR CI stays offline and free (matching RFC-0002's deterministic suite). The same
  bar gates any future move to a cheaper default (e.g. Haiku).

**Plan `must_haves` (seed for the execution plan):**
- *truths:* maestro emits `agent`+`agents:`+`handoffs:` (copilot) and `permission.task` (opencode),
  all as **explicit per-specialist lists** (never `'*'`/glob); `carter check` **errors** on a `'*'`/
  glob/absent primary allowlist (fail-closed lint); specialists carry `agents: []` (flat chain);
  maestro Copilot-CLI prose injects plan+knowledge context into `/fleet` prompts; no `runSubagent`
  anywhere; `POLICY_LEVELS == (guarded, strict)` with **zero `loose` references** in shipped code/docs/
  tests; taxonomy is the **4-category allowlist (§4 table)** with secret-access merged into
  `remote-write`; substantive outward content routes through the narrator as a **`gate`-tier handoff**
  (enforced) and `redaction.enabled` + force-at-`guarded`/`strict` is retained; no agent emits
  `temperature`; each agent emits a per-target `model:` resolved by `overrides > tier > default`;
  `carter check` prints the unverifiable-model advisory; a dated artifact is written with a fetched
  (not guessed) date; all tests green; the P4-eval clears **≥90% must_haves + 0 critical-step
  failures**.
- *artifacts:* new ADR superseding ADR-0005; updated `config.py`/`scaffold.py`/templates/statics;
  README reconciled per §6c + `docs/strictness-policy.md` + `docs/getting-started.md` +
  `frontmatter.md`; the `models:` block + Carter→target model-name table (with sync marker + test);
  the fail-closed dispatch lint + the required `carter check` model advisory; `evals/` adherence
  scenario + its recorded CI fixture.
- *key_links:* this RFC; the primary-doc URLs in §References; the P4-eval results.

---

## Decision

**ACCEPTED — 2026-06-26.** The maintainer answered every open Q and review blocker at the decision
gate; r3 records them as decisions (D-prefixed throughout). The five r1 reviews were **request-changes**
(architect, engineer, devops, narrator) and **approve** (pm); r3 folded in every blocker (A1 allowlist
table, A2/N1 named redaction mechanism, A3 `models:` precedence, E1 fail-closed lint, E2 model advisory,
E3 `temperature` drop, D1 effort truth, D2 `/fleet` context rule, N2 README claims-commitment, R1
sequencing, R2 P2 entry-gate, R3 eval pass-bar), and the maestro synthesis gate (ADR-0004 §D5) confirmed
all ten blockers resolved with no new contradiction. Per the ADR-0004 §D6 chain this RFC yields:

- **[ADR-0010](../../adr/0010-agent-platform-refresh.md)** — the durable decision record, which
  **supersedes ADR-0005 in full** (ADR-0005 gets `superseded_by: ADR-0010`).
- **Plan [005-agent-platform-refresh](../../../.carter/state/plans/active/005-agent-platform-refresh/)**
  — the execution plan decomposing §7's P0–P4 + P4-eval.

`supersedes: [RFC-0002]` is set in the frontmatter above. **Carried decisions (Group 8, not
re-litigated):** implementer tier = Sonnet 4.6 (Haiku opt-in only; doc accuracy/detail stays at the
Opus bar); add the `evals/` adherence scenario; taxonomy = 4 categories; RFC-0005 supersedes RFC-0002
**in full**.

## References (verified 26 Jun 2026 unless noted)

**Platform — orchestration & frontmatter**
- Custom agents in VS Code (frontmatter fields; `tools:` enforced; `handoffs:` = UI buttons; `.md` accepted; `~/.copilot/agents` + `.github/agents` discovery) — <https://code.visualstudio.com/docs/agent-customization/custom-agents>
- Subagents in VS Code (`agent` tool; `agents:` allowlist; `disable-model-invocation`; depth 5) — <https://code.visualstudio.com/docs/copilot/agents/subagents>
- Copilot CLI `/fleet` — <https://docs.github.com/en/copilot/concepts/agents/copilot-cli/fleet>
- OpenCode agents (`mode`; `permission` incl. `task`; `tools` deprecated, no sourced version) — <https://opencode.ai/docs/agents/>
- OpenCode agent frontmatter **accepts `temperature`** (and `top_p`) as a valid field (re-verified 26 Jun 2026) — relevant to D2.6: OpenCode accepts `temperature` syntactically, but the pinned Anthropic models reject it at the API one layer down, so Carter drops it on all targets — <https://opencode.ai/docs/agents/>

**Platform — model & effort per agent**
- `model:` array vs Copilot CLI parse error — <https://github.com/github/copilot-cli/issues/2133>
- Per-agent reasoning effort NOT supported (Copilot CLI request) — <https://github.com/github/copilot-cli/issues/2904>
- Per-agent reasoning effort NOT supported (VS Code request) — <https://github.com/microsoft/vscode/issues/313546>
- `.agent.md` custom-endpoint model limits — <https://github.com/microsoft/vscode/issues/319709>

**Models (Anthropic `claude-api` skill, cached 2026-06-04)**
- Current Haiku = `claude-haiku-4-5` (no 4.6 Haiku); Opus = `claude-opus-4-8`; effort `low/medium/high/xhigh/max`; `xhigh`/`max` Opus-tier only (error on Haiku); Opus 4.8/4.7 & Fable 5 reject `temperature`; `effort` is `output_config.effort` (API-level, not agent frontmatter).
