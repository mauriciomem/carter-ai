# Frontmatter reference

> Canonical schema source for Carter's durable artifacts (ADR-0003 §D6).
> This is the **authoritative** definition. The `carter-adr` and `carter-plan`
> skills carry a minimal emittable template for the agent to write from, but this
> page governs — on any discrepancy, this wins, and the Python validator
> (`carter check`) enforces the load-bearing keys/enums against it.

All durable, lifecycle-bearing artifacts carry a YAML frontmatter block. Machines
read the frontmatter; humans read the body. Where a Python validator exists
(ADR-0003 §O3, Phase 2), it enforces these schemas before a plan is `active`.

---

## Plan `README.md`

```yaml
---
id: 001-feature-name          # NNN-kebab; MUST match the directory name
status: active                # proposed | active | blocked | completed | abandoned
created: 2026-06-09           # date (YYYY-MM-DD) — validated
updated: 2026-06-09           # date (YYYY-MM-DD) — validated
adr: null                     # ADR-NNNN if this plan executes an accepted ADR
rfc: null                     # RFC-NNNN this plan traces back to (optional)
push_policy: manual           # manual | auto  (manual = never push without approval)
tags: []
repos: []                     # repos this plan touches (multi-repo work)
must_haves:                   # MANDATORY: >= 1 entry total (ADR-0003 O6)
  truths: []                  #   observable behaviors/states that must be true
  artifacts: []               #   files/resources that must exist
  key_links: []               #   canonical references (PRs, dashboards)
---
```

`must_haves` is the objective, verifiable definition of done. The quality gate
checks against it; a plan with an empty `must_haves` is a checklist, not a plan,
and the validator rejects it while `status: active`.

**Validated rules** (enforced by `carter check`):

- `created` / `updated` must be **dates** (`YYYY-MM-DD`, optionally with a time).
- `must_haves` is a **closed key set** — only `truths`, `artifacts`, `key_links`;
  an unrecognized sub-key is an error (catches typos like `truth:`).
- **Bucket ↔ status coherence:** a plan's frontmatter `status` must agree with its
  folder — terminal statuses (`completed`, `abandoned`) live in `completed/`;
  non-terminal ones (`proposed`, `active`, `blocked`) live in `active/`. The folder
  is a coarse index *and* a validated invariant; the frontmatter `status` remains
  the source of truth, but the two may not contradict each other.

## Plan `step-NN.md`

Present only when a plan has **> 3 steps** (see thresholds below). 1–3 steps stay
inline in the README steps table.

```yaml
---
step: 1
status: pending               # pending | in-progress | done | blocked
depends_on: []                # step numbers this step waits on
files_modified: []            # filled after completion
---
```

## ADR frontmatter

In **addition** to the human "Status / Date / Deciders" block (kept for readers
landing on a long ADR), every ADR carries:

```yaml
---
id: ADR-0003
status: accepted              # proposed | accepted | rejected | superseded | deprecated
created: 2026-06-07
decided: 2026-06-09           # null until accepted
supersedes: []                # ADR ids or "ADR-NNNN§D3"
superseded_by: null
rfc: null                     # RFC-NNNN this ADR records the decision for (optional)
tags: [storage, metadata, plans, adr]
---
```

A change or reversal is a **new** ADR with `supersedes: ADR-NNNN§Dn` — never an
edit to an accepted ADR. Backfilling frontmatter is a metadata addition, not a
decision change, and is permitted.

## RFC frontmatter

An RFC (design proposal, [ADR-0004](../adr/0004-rfc-system.md)) is a **directory**
under `docs/rfcs/NNNN-name/`; its `README.md` carries frontmatter + a human header
block. Status lives in frontmatter; the directory never moves.

```yaml
---
id: RFC-0001
status: draft                 # draft | review | accepted | rejected | withdrawn
revision: 1                   # bump only on a material change to the proposal
created: 2026-06-10
decided: null                 # date when accepted/rejected/withdrawn
author: mauriciomem
adr: null                     # ADR-NNNN produced by this RFC, when accepted
plan: null                    # NNN-slug plan that executes it, when created
supersedes: []                # RFC ids this replaces
tags: []
---
```

Terminal statuses (`accepted`, `rejected`, `withdrawn`) freeze the RFC — supersede
with a new RFC, never edit. Re-reviews append newest-first `## Round N — reviewed
revision M` sections in per-agent `review-{agent}.md` files; a review is current
iff its latest round's reviewed revision equals the RFC's `revision`. Authored via
the [`carter-rfc`](../../skills/carter-rfc/SKILL.md) skill.

## Session `checkpoint.md`

A **thin cursor** the maestro writes suggest-and-confirm at natural pauses. It
points *into* the active plan's frontmatter (the source of truth) and never
duplicates plan content.

```yaml
---
updated: 2026-06-09T18:00:00Z
active_plan: 001-feature-name # plan id, or null
next_step: 4                  # step number, or null
---
```

Followed by a one-line human summary ("where we left off").

## Knowledge entries (optional, light touch)

The 5 hardcoded workspace knowledge files keep their current shape. Individual
entries that need portability MAY carry:

```yaml
scope: workspace              # universal | workspace
tags: [security, terraform]
```

This is genuinely optional — not half-mandatory.

---

## Configurable thresholds

Numeric splitting thresholds are **defaults in `carter.yaml`** (the `plans:`
block), tunable per workspace. The *structural* rules (every plan is a directory,
status lives in frontmatter, one step = one independently-statusable unit) are
invariant and not configurable.

```yaml
plans:
  step_file_threshold: 3     # > N steps -> per-step files
  readme_max_lines: 150      # README split budget
  step_max_lines: 80         # step-file split budget
```

The **ADR ≤ 400-line budget is NOT workspace config** — ADRs live in the main
repo, outside any `.carter/`, so `carter.yaml` cannot govern them. It is a
`carter-adr` skill constant.

## Risk-based strictness policy (`policy` block)

The risk-based strictness policy ([ADR-0005](../adr/0005-risk-based-strictness-policy.md), refreshed by
[ADR-0010](../adr/0010-agent-platform-refresh.md)) adds a `policy` block to
`carter.yaml`. `guarded` is the floor and the default for everything: a new install,
an existing config that omits the block, and an unrecognized level all resolve to
`guarded`.

```yaml
policy:
  level: guarded            # guarded | strict
  overrides: {}             # category -> gate, explicit per-category override
  # Optional user extension — DICT-shaped so it deep-merges over the shipped
  # default (a list would replace it wholesale; carter/config.py _deep_merge):
  allowlist: {}             # agent -> {category: bool}, e.g. {engineer: {remote-write: true}}
```

**Risk taxonomy (shipped, fixed — 4 categories, ADR-0010 D4).** Each maps a
strictness level to a gate (`allow` | `ask` | `gate` | `deny`).

| Category | Meaning | guarded | strict |
|----------|---------|---------|--------|
| read | reads, `git status/log/diff`, MCP GET | allow | allow |
| local-write | file edit, `git add/commit`, run tests | allow | allow |
| remote-write | `git push`, PR/issue write, MCP POST/PATCH/DELETE, secret reads (`vault read`, `.env`) | ask | gate |
| dangerous | `terraform apply/destroy`, `kubectl apply`, `rm -rf`, `git reset --hard`, `--force` | gate | deny |

Secret reads fold into `remote-write` (they gate identically). Outward content is
**not** a category — it is an enforced `gate`-tier redaction handoff (ADR-0010 D5):
substantive outward content must pass the narrator's redaction pass before devops
(the sole `remote-write` holder) transmits it.

**Per-agent allowlist (deny-by-default).** A category absent for an agent is denied
for that agent. The shipped default keeps `devops` the sole holder of `remote-write`
and `dangerous` (the single pusher); the narrator is first-class (`read` +
`local-write`) and reaches a remote only via the redaction handoff to devops:

| Agent | Allowed categories |
|-------|--------------------|
| maestro, architect, learner | read |
| pm, narrator, engineer, security | read, local-write |
| devops | read, local-write, remote-write, dangerous |

**Per-agent emission.** Carter writes the agent's allowlist + gates as a
`<!-- carter:policy {"level":…,"allow":[…],"gates":{…}} -->` comment right after the
frontmatter (the declared model `carter check` lints against), and emits native
frontmatter keys per target:

- **OpenCode:** `permission` (edit / bash command-globs / webfetch) + per-agent
  MCP scope via tool-name patterns.
- **VS Code / Copilot:** an enforced `tools:` allowlist **derived from the policy
  categories** (ADR-0011) — `tools:` is a *replacing* allowlist, so the file tools each
  category implies MUST be listed or the agent (and the chain it delegates to) loses the
  filesystem: `read` → `codebase`/`search`/`usages`/`fetch`; `local-write` → `editFiles`;
  the primary additionally carries `agent`; plus the per-agent MCP scope.

Per-agent MCP scope is emitted in **agent frontmatter**, never the global
`configure_mcp_servers` wiring.

**Native subagent dispatch (P3, ADR-0010 D1).** Carter emits the target's real
delegation primitive on the **primary** (maestro) — never a fictional `runSubagent`.
The dispatch allowlist is a **security boundary**: an **explicit per-specialist
list**, never `'*'` and never a `carter-*` glob (a glob auto-trusts any future
`carter-*` agent; `'*'` lets the primary delegate to any workspace agent). The chain
is **flat** — every specialist carries `agents: []`, so the maestro is the only
router. The emitted names honor `agent_suffix` (e.g. `carter-engineer-local`).

- **VS Code / Copilot:** the `agent` subagent tool (ahead of the maestro's policy file
  tools, ADR-0011) + an explicit `agents: [carter-architect, …]` allowlist + `handoffs:`
  (the user-approved gate-confirm buttons for gate-tier actions).
- **OpenCode:** a `permission.task` block — `'*': deny` plus an explicit `allow` per
  specialist.
- **Copilot CLI:** orchestration is runtime (`/fleet` + `@`-mention), so there is no
  frontmatter change — but the maestro prose **must** inject the active-plan +
  knowledge context into every `/fleet` prompt (subagents do not inherit chat
  history).

```yaml
# maestro, copilot target  (tools: is policy-derived — agent + read file tools, ADR-0011)
tools: [agent, codebase, search, usages, fetch]
agents: [carter-architect, carter-devops, carter-engineer, carter-learner, carter-narrator, carter-pm, carter-security]
handoffs: [carter-architect, carter-devops, carter-engineer, carter-learner, carter-narrator, carter-pm, carter-security]
# maestro, opencode target
permission:
  task: {'*': deny, carter-architect: allow, carter-devops: allow, ...}
```

`carter check` runs a **fail-closed dispatch lint**: it **errors (exit non-zero)** if
the primary's emitted `agents:` / `permission.task` is `'*'`, a glob, or absent — not
a warning.

**Global agents (no `carter.yaml` in scope).** Globally-installed static
`agents/*.md` carry baked hand-edited `guarded` defaults, kept honest by a
`test_parity` extension (Q14 / ADR-0005 D6 — build-time generation is WON'T-DO per
[ADR-0002](../adr/0002-single-source-agent-generation.md)).

## Per-agent model (`models` block)

The `models` block (ADR-0010 D2) is orthogonal to `policy:` — it maps role tiers to a
per-target model string. Carter emits a **single** `model:` string on each agent (an
array breaks Copilot CLI): a display name for VS Code/Copilot, a `provider/model` id
for OpenCode. It is **dict-shaped** so a user override deep-merges rather than wiping
the shipped tiers.

```yaml
models:
  default:      { copilot: "Claude Opus 5.5",   opencode: "anthropic/claude-opus-5-5" }
  thinkers:     { copilot: "Claude Opus 5.5",   opencode: "anthropic/claude-opus-5-5" }
  implementers: { copilot: "Claude Sonnet 5.5", opencode: "anthropic/claude-sonnet-5-5" }
  overrides: {}   # per-agent, e.g. {engineer: {copilot: "Claude Haiku 5.5", opencode: "anthropic/claude-haiku-5-5"}}
```

**Resolution: `overrides` > `profile` > tier > `default`.** Thinkers (maestro,
architect, learner, security) = Opus 5.5; implementers (engineer, devops, pm, narrator)
= Sonnet 5.5; `default` is the un-tiered catch-all so a future agent never resolves to
an empty model. A `profile:` (`quality` | `budget`) re-tiers roles at resolve time (see
[cost-and-models.md](cost-and-models.md)). **Haiku is opt-in via `overrides` only.**
A test asserts every shipped role resolves to a non-empty model string.

**`carter check` model advisory (required).** Carter cannot verify the user's
Copilot/OpenCode subscription includes a pinned model, so it **emits the pin anyway**
and `carter check` always prints an advisory naming each agent's model + the
can't-verify caveat — an unavailable model is silently ignored frontmatter otherwise.

**Effort and temperature are NOT emitted.** No target has a per-agent effort field, so
effort is the global `output_config.effort` knob — set per-session on the harness
(`copilot --effort high`). Carter's docs recommend a single global default of **`high`**
(the safe all-rounder: `medium` under-serves
the thinkers), raised per-session (e.g. `xhigh`) for thinker-heavy RFC/ADR/plan work.
`temperature` is dropped wholesale (D7) — dead or rejected on every pinned model.

## See also

- [ADR-0003](../adr/0003-knowledge-adr-rfc-plan-storage.md) — the decision of record
