---
id: RFC-0002
status: accepted              # draft | review | accepted | rejected | withdrawn
revision: 3
created: 2026-06-11
decided: 2026-06-13
author: mauriciomem
adr: ADR-0005                 # records this decision (ADR-0004 RFC system)
plan: 002-risk-based-strictness-policy  # execution plan (completed 2026-06-13)
supersedes: []
tags: [strictness, enforcement, security, agents, mcp, policy]
---

# RFC-0002: Risk-Based Strictness Policy

**Status:** Accepted
**Revision:** 3
**Author:** mauriciomem

> **Execution note.** Written to be picked up in a **fresh session**. It embeds
> the verified current state (with `file:line` grounding) so the implementer need
> not re-discover it. **Revision 2** integrated Round 1 multi-reviewer findings
> and the maintainer's resolved decisions; **revision 3** integrates the accepted
> **Round 2** fixes (QA–QF, 2026-06-12). The prior `DECIDE` items in **Open
> questions** (Q1–Q20) are settled one-liners — no open blockers remain for
> implementation.

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

The unifying honest premise, **split correctly**: the Carter *process* cannot
intercept a tool call (it exits after scaffolding) — but the *config Carter emits*
**can** intercept deterministically, because modern targets ship native
interceptors: OpenCode `permission: deny`, Copilot CLI `hooks` (preToolUse), and
VS Code MCP `sandbox` + agent `hooks` (Preview). So "enforcement" = *emitting
platform-native interceptors and allowlists* the target enforces at runtime, plus
a deterministic `carter check` lint that the emitted config matches the declared
policy. Where a target lacks a primitive, the policy degrades to prose and **says
so** (Q15 hard ack).

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

> **Merge footgun (verified).** `carter/config.py` `_deep_merge` recurses dicts
> but **replaces lists wholesale**. The shipped tool→risk map and per-agent
> allowlist MUST therefore be **dict-shaped** (`{tool: risk}`, `{agent: {cat:
> bool}}`) — a list would let one user override silently wipe the whole shipped
> map. `overrides` is already a dict; keep every policy collection a dict.

### 2. Risk taxonomy (fixed, shipped with Carter)

Seven categories. **R0–R5 are mutually-exclusive transport/action categories;
R6 (external-publish) is a content *overlay* dimension** that composes with the
transport gate (narrator D1 — a `gh pr comment` is both an R2 transport **and** an
R6 content overlay: narrator authors/redacts the R6 content, devops performs the
R2 transmit — they **compose**, not collide). Gate vocabulary: `allow` (silent) ·
`ask` (human confirm) · `gate`
(ask **+** required handoff to the owning agent / checkpoint artifact) · `deny`
(blocked; override required).

**Most-restrictive-wins precedence.** An action matching multiple categories takes
the strictest gate: `git push --force` = R2∩R5 → R5; `terraform destroy` =
R3∩R5 → R5. The R6 overlay composes the same way (most-restrictive of transport
gate and R6 gate).

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

- **R6 two-lane (D3):** short-form low-risk outward content (e.g. a one-line PR
  comment) = **`ask` + an inline redaction check** (the agent still runs the
  redaction-category scan on the short-form content before the ask, skipping only
  the full narrator handoff); substantive outward content (release notes, Slack
  posts, Jira bodies, PR descriptions) keeps full **`gate(narrator)`** — avoids
  handoff fatigue while keeping redaction on **every** outward path.
- **Commit messages ship outward (honesty note):** squash-merge publishes the
  commit body, yet commits are R1=`allow` with no R6 pass. Carter cannot gate the
  merge, but the R6 overlay applies to any commit message destined to become
  public — so the redaction path is offered, not silently skipped.
- **Network-egress / exfiltration — rejected as a separate category (rationale):**
  arbitrary outbound spans `webfetch`/`websearch` and bash `curl`/`wget`, can't be
  enumerated as one tool category at the scaffolder layer, and a true exfiltration
  gate implies content inspection Carter cannot perform. Instead:
  `webfetch`/`websearch` inherit the `unknown_tool` gate, bash egress rides the
  R2/R3/R5 bash-glob path, and MCP `sandbox` network allowlists are emitted where
  the target supports them.

### 3. Per-agent tool allowlist (deny-by-default)

Independent of level: a category **not** listed for an agent is **denied** for that
agent, always. This is the "tool allowlist per agent" pillar.

| Agent | Allowed categories | Rationale |
|---|---|---|
| maestro | R0 | routes; never mutates directly |
| architect | R0 | design/review; reads only |
| engineer | R0, R1 | codes/tests locally; R2 only via a devops handoff |
| devops | R0, R1, R2, R3, R4, R5 | the **only** infra-mutator / pusher; **R4 included** — infra work legitimately reads secrets/tokens (`.env`, vault) for `terraform`/deploy |
| pm | R0, R1 | plans; local artifacts only |
| learner | R0 | explains; reads only |
| narrator | R0, R1, R6 | the **only** external **author** — drafts + redacts R6 content; **devops transmits** via R2 (narrator→devops handoff) |

A substantive outward publish is **R2∩R6** and flows as a **narrator→devops
handoff**: narrator authors and applies the redaction pass (R6), then devops
performs the transmit (R2) under its R2 gate. No single agent holds both
categories — this preserves the single-pusher invariant (devops remains the only
R2 agent).

### 4. Emission — enforce natively where supported, label the rest

Effective policy = `min(level gate, per-agent allowlist)` per category, emitted via
the **most authoritative primitive each target offers** (Q2 — verified against 2026
docs):

| capability | OpenCode | VS Code custom agents | Copilot CLI |
|---|---|---|---|
| per-agent tool allowlist | YES `permission` (`tools` boolean **DEPRECATED ≥v1.1.1**) | YES `tools:` list — **ENFORCED** (unlisted tool unavailable) | YES `tools:` in agent profile (default all; restrictable) |
| per-action ask/deny gate | YES `permission:{edit,bash,webfetch,…}` allow\|ask\|deny + bash command globs | NO declarative per-category gate (interactive confirm + MCP `sandbox` fs/network) | partial (interactive allow/deny; `hooks` preToolUse can BLOCK deterministically) |
| per-agent MCP scope | YES tool-name patterns (`mymcp_*: deny`) | YES `tools: [server/*]` / `mcp-servers` | YES `mcp-servers` per profile |
| native handoff primitive | `permission.task` | `handoffs:` frontmatter | subagent delegation |
| deterministic pre-action hook | plugins | `hooks` (**Preview**) | `hooks` preToolUse/postToolUse (strong) |

**Emission ladder (per category, best-available first):**
`native-deny` → `native-ask` → **prose backstop**. For `deny` on R2/R3/R5 prefer a
native interceptor — OpenCode `permission: deny`, Copilot CLI `hooks` preToolUse —
over an allowlist omission, so the action is *blocked*, not merely *unlisted*. VS
Code `hooks` are **Preview**; until stable, VS Code `deny` falls back to allowlist
omission + `sandbox` + prose.

- **OpenCode**: emit **`permission`** (not the deprecated `tools` boolean) per agent
  → genuine runtime enforcement, incl. bash command globs (`"git push": "ask"`).
- **VS Code**: emit the **enforced** `tools:` allowlist + per-agent MCP scope
  (`tools: [server/*]`); use `sandbox` for fs/network; `hooks` once out of Preview.
- **Copilot CLI**: emit restricted `tools:` + `mcp-servers` per profile, and
  **`hooks` preToolUse** as the deterministic deny/ask gate.
- **Handoffs are native, not invented** (supersedes old Q10): use VS Code
  `handoffs:` and OpenCode `permission.task` to scope which agent a category routes
  to; label "advisory" only where no native primitive exists.
- **Bash bypass:** R2/R3/R5 also run via shell against the same token — gate the
  bash path too (OpenCode `permission.bash` globs; Copilot CLI `hooks`). VS Code
  **cannot** gate bash declaratively — note the gap.
- **All targets**: emit a `<policy>` block in the agent body (allowlist + gates) and
  **upgrade the maestro risk table** (`carter-maestro.md.j2:~170`) from
  `skepticism`-gated prose to an always-present policy-driven gate.
- **MCP / "read-only" (Q3 — P1 MUST):** all three targets support per-agent MCP
  scoping in **agent frontmatter**, *not* the global `configure_mcp_servers` @
  `installer.py:782` (`copilot mcp add` is inherently global). **Drop the
  "read-only" wording** at **all four** static agents that carry it —
  `agents/carter-architect.md:39`, `agents/carter-engineer.md:43`,
  `agents/carter-learner.md:40`, and `agents/carter-pm.md:42` — the shared
  full-scope token (`installer.py:271`) makes it a false guarantee. The drop is in
  agent **body text** (not frontmatter), so the `test_parity` frontmatter check
  won't catch it — P1 must edit both the static `agents/*.md` **and** the
  templates. Scoped tokens are deferred to **RFC-0003**.

### 5. Static validation (`carter check` extension)

Deterministic, testable, runs offline:
- Lint that each **installed** agent's emitted frontmatter matches its declared
  allowlist + the active level's gate map.
- Detect **drift** between `carter.yaml policy` and the installed agent/MCP files.
- **HARD ACK (Q15):** when the active target **cannot natively enforce** the declared
  `strict` level, install **and** `carter check` require an explicit acknowledgement
  (not a soft WARN) — the user must accept the degraded guarantee. A non-interactive
  `--accept-degraded` flag (install + `carter check`) satisfies the ack in
  CI/automation without a prompt; absent the flag in a non-interactive context, the
  command fails closed (does not silently proceed). (P3 detail.)
- **WARN on the `redaction.enabled: false` contradiction at `guarded` or `strict`
  (Q16)** — see §6.
- It **cannot** verify that the platform actually denies at runtime — explicitly out
  of scope and documented (Q17).

### 6. Escape hatch & redaction override

A `deny`-gated action proceeds only with an **explicit, single-action override**
(no blanket/session-wide overrides — avoids override fatigue, Q11). **Override ≠
authorization:** the `carter ops` audit path is a **post-hoc ledger** — it *records*,
it **cannot lift a platform `deny`**. So "override" means, per tier: at
**native-deny**, the user edits the emitted config / re-runs with the gate relaxed
(logged); at **native-ask**, confirm the interactive prompt; at **prose backstop**,
proceed on trust (logged only). The ledger is accountability, not a bypass.

**Redaction override (Q16 — verified leak).** The narrator's entire
`<redaction_rules>` block (incl. the anti-bypass clause) is wrapped in
`{% if config.redaction.enabled %}` at `templates/agents/carter-narrator.md.j2:67-111`
— so `redaction.enabled: false` renders a narrator with **zero** redaction rules. At
**`guarded` and `strict`** (every level where R6's gate is `gate(narrator)` — loose
stays advisory), **R6 MUST force a redaction/narrator pass regardless of
`redaction.enabled`**, and `carter check` MUST WARN on the contradiction.

### 7. Phasing (so a fresh session can land it incrementally)

- **P1 — model + docs (no behavior change):** `policy` block (dict-shaped maps) in
  `config.py`; risk taxonomy + tool→risk map (shipped, user-extensible); agent +
  global-policy frontmatter schema in `docs/reference/frontmatter.md`; default
  `guarded` for **new** installs, `loose` for existing/omitted config (Q6); **drop
  the "read-only" prose** (Q3 P1 MUST).
- **P2 — emission:** agent templates **and** the static `agents/*.md` emit
  `permission` (OpenCode) / enforced `tools:` + `hooks` (VS Code/Copilot) + per-agent
  MCP scope in frontmatter; maestro risk table becomes policy-driven; the "you're
  `guarded` now" migration message surfaces **here** (enforcement is real), not P1.
- **P3 — lint + escape hatch + tests:** `carter check` policy lint (incl. Q15 hard
  ack, Q16 WARN); override ledger; unit tests for emission + lint (runtime denial is
  manual/out of scope). **Gate:** `strict` enforcement ships only after P3 lands —
  the execution plan decomposes this into per-phase milestones with a **P2→P3 gate**.

## Alternatives considered

| Option | Pros | Cons |
|--------|------|------|
| **Risk-based hybrid (chosen)** | speed for low-risk; hard gates only where it matters; emits **native interceptors** (hooks/permission-deny) where supported | per-target divergence; more config surface |
| Globally rigid (everything gated) | simplest mental model | kills the loose-chain speed; users disable it (worse than loose) |
| Prompt-only "be stricter" | zero code | unenforceable; the exact problem we have now |
| Carter as a **runtime proxy** intercepting calls itself | true enforcement on any target | huge complexity; Carter would become a runtime — rejected (we emit the target's *native* interceptors instead) |
| Per-agent **scoped MCP tokens** (Q3(b)) | fixes the shared full-scope token at its root | out of scope here — **split into draft RFC-0003** (`../0003-per-agent-scoped-mcp-tokens/`) |
| Reuse `quality_gate` pre-action | no new concept | gate is post-implementation review, not per-action authorization (different seam) |

## Trade-offs / Impact

- **New config surface** (`policy` block) — additive, backward-compatible.
- **Touches > 3 files** (config, all agent templates, static agents, installer MCP
  wiring, `carter check`, frontmatter docs) → justifies an RFC + ADR + plan.
- **Per-target inequality (verified):** OpenCode + VS Code `tools:` are **enforced**;
  per-category ask/deny is strongest on OpenCode (`permission`) and Copilot CLI
  (`hooks`), weakest on VS Code (no declarative gate, `hooks` still Preview) —
  `carter check` surfaces this via the Q15 hard ack, never hides it.
- **Residual token risk (Q3):** the shared full-scope MCP token is **not** fixed by
  this RFC; we drop the false "read-only" claim and defer the real fix to **RFC-0003**
  (`../0003-per-agent-scoped-mcp-tokens/`). Accepted residual: medium.
- **`carter update` re-emits agents** — customization must live in `carter.yaml`,
  never in hand-edited agent files (Q12). **Exception:** *global* agents have no
  `carter.yaml` in scope (Q14) — their `guarded` defaults are **hand-edited into the
  static `agents/*.md`** and kept honest by a `test_parity.py` extension (build-time
  generation is **WON'T-DO** per ADR-0002:37; statics are raw-copied at
  `installer.py:498`).
- **Reconciliations:** generalizes plan `push_policy` (Q20 — effective gate =
  `max(workspace level, plan push_policy)`; `push_policy: manual` only ever *tightens*
  R2); orthogonal to `personality.skepticism` (tone) and `quality_gate` (post-review);
  **`strict` overrides `redaction.enabled: false`** for R6 (Q16).
- **Risk of friction:** an over-strict default makes users disable the whole thing
  → default `guarded`, single-action overrides, clear acks.

## Open questions

**All Round 1 `DECIDE` items are resolved in revision 2** (maintainer, 2026-06-12).
Retained as a one-line audit trail; no open blockers remain.

- **Q1 — Enforcement locus → REFRAMED.** Process can't intercept; *emitted config*
  can (native interceptors). No proxy. See Summary.
- **Q2 — Per-target capability → RESOLVED by verification.** See the §4 matrix
  (2026 docs): all three targets do per-agent tool allowlist + MCP scope; gate
  strength differs.
- **Q3 — MCP token blast radius → chose (a).** Ship `guarded`; **drop "read-only"
  wording** (P1 MUST); scoped-token fix deferred to **RFC-0003**.
- **Q4 — vs `personality.skepticism`:** orthogonal; on conflict **policy gates win**,
  skepticism only shapes prose.
- **Q5 — vs `quality_gate`/`tdd.strict`:** separate seams; reuse severity vocab;
  policy = pre-action authorization, quality gate = post-review.
- **Q6 — Default level:** `guarded` for new installs, `loose` for existing/omitted;
  migration message at **P2** (not P1).
- **Q7 — Level scope:** global `level` + optional `overrides` (category→gate);
  per-agent allowlist always applies.
- **Q8 — Taxonomy edge cases:** amend-published = R5; `tf plan` default R0 but
  `-refresh`/state-write = R2; `.env` read = R4 (table stands).
- **Q9 — Tool→risk map:** shipped + user-extensible (**dict-shaped**); `unknown_tool`
  = `ask` at guarded, `deny` at strict.
- **Q10 — Handoff → SUPERSEDED.** Native primitives exist (VS Code `handoffs:`,
  OpenCode `permission.task`); advisory only where none.
- **Q11 — Override UX:** explicit single-action override + `carter ops` ledger; no
  session-wide overrides (override ≠ authorization, §6).
- **Q12 — `carter update` clobbering:** all customization in `carter.yaml`; agents
  always re-emitted (global-agent exception, Q14).
- **Q13 — Lint scope:** emitted frontmatter ↔ allowlist; category↔gate per level;
  carter.yaml↔installed drift. Runtime denial not verifiable.
- **Q14 — Global agents (no `carter.yaml`) → REFRAMED, chose (a).** "Bake at build
  time" is **falsified** (ADR-0002:37 WON'T-DO; statics raw-copied
  `installer.py:498`). Decision: **baked hand-edited `guarded` defaults in static
  `agents/*.md` + a `test_parity.py` extension** (dual-source hand-edit, *not*
  generation). A global policy file read at install was considered and **deferred
  to the execution plan** as a possible future alternative.
- **Q15 — Strict on non-enforcing target → HARD ACK** (not soft WARN); install +
  `carter check` require explicit acknowledgement.
- **Q16 — vs `redaction` → strict OVERRIDES `redaction.enabled: false`** (verified
  leak, §6) + `carter check` WARN on the contradiction.
- **Q17 — Testing:** unit-test emission + lint + prose; runtime denial manual/out of
  scope.
- **Q18 — One RFC vs split → ONE** phased RFC; the *execution plan* decomposes into
  per-phase milestones with a **P2→P3 gate**.
- **Q19 — ADR numbering:** **do not pre-reserve** — the resulting ADR takes the next
  free number at write time.
- **Q20 — `push_policy`:** effective gate = `max(workspace level, plan push_policy)`;
  `manual` only *tightens* R2; kept as a per-plan override, documented in
  `frontmatter.md`.
- **D1 (narrator) — R2↔R6 → OVERLAY** (not split): R6 is a content overlay composed
  with the transport gate (most-restrictive-wins), so redaction stays on every
  outward path; the "exactly one category" rule is relaxed accordingly (§2).
- **D3 (narrator) — short-form R6 lane:** one-line/low-risk outward = `ask`;
  substantive outward = full `gate(narrator)` (§2).

## Decision

**Accepted 2026-06-13.** After a three-round review — rev 1 drew 5× request-changes;
rev 2 integrated the Round 1 findings and resolved Q1–Q20; rev 3 integrated the
Round 2 fixes (QA–QF) — all five reviewers (architect, engineer, devops, narrator,
pm) approve, each current at revision 3. No open blockers remain.

The decision is recorded as **[ADR-0005](../../adr/0005-risk-based-strictness-policy.md)**
(per ADR-0004, an accepted RFC yields an ADR before a plan executes it). The next
step is **execution plan 002**, covering phases P1–P3 with per-phase milestones and
the **P2→P3 gate** (`strict` enforcement ships only after P3 lands).

This RFC is now **frozen**; any change is a new RFC that supersedes it, never an edit.
