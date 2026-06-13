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
  git_regime: private        # private | workspace (umbrella mode only)
```

The **ADR ≤ 400-line budget is NOT workspace config** — ADRs live in the main
repo, outside any `.carter/`, so `carter.yaml` cannot govern them. It is a
`carter-adr` skill constant.

## Risk-based strictness policy (`policy` block)

The risk-based strictness policy (RFC-0002 /
[ADR-0005](../adr/0005-risk-based-strictness-policy.md)) adds a `policy` block to
`carter.yaml`. It is additive and backward-compatible: an existing config that
omits it resolves to `loose` (no behaviour change); a new install resolves to
`guarded`.

```yaml
policy:
  level: guarded            # loose | guarded | strict
  unknown_tool: ask         # gate for a tool not in the risk map: allow | ask | deny
  overrides: {}             # category -> gate, explicit per-category override
  audit_overrides: true     # log escape-hatch overrides via `carter ops`
  # Optional user extensions — DICT-shaped so they deep-merge over the shipped
  # defaults (a list would replace them wholesale; carter/config.py _deep_merge):
  tool_risk: {}             # tool/command -> risk category, e.g. {my_tool: R2}
  allowlist: {}             # agent -> {category: bool}, e.g. {engineer: {R2: true}}
```

**Risk taxonomy (shipped, fixed).** Seven categories; each maps a strictness level
to a gate (`allow` | `ask` | `gate` | `deny`). An action in multiple categories
takes the most restrictive gate.

| Category | Meaning | loose | guarded | strict |
|----------|---------|-------|---------|--------|
| R0 read | reads, `git status/log/diff`, MCP GET | allow | allow | allow |
| R1 local-write | file edit, `git add/commit`, run tests | allow | allow | allow |
| R2 remote-write | `git push`, PR/issue write, MCP POST/PATCH/DELETE | allow | ask | gate |
| R3 infra-mutate | `terraform apply/destroy`, `kubectl apply` | allow | gate | deny |
| R4 secret-access | read `.env`/secret files, vault reads | allow | ask | gate |
| R5 destructive | `rm -rf`, `git reset --hard`, `--force` | allow | gate | deny |
| R6 external-publish | outward content (overlay; composes with transport) | allow | gate | gate |

**Per-agent allowlist (deny-by-default).** A category absent for an agent is denied
for that agent. The shipped default keeps `devops` the sole R2 pusher and `narrator`
the sole R6 author:

| Agent | Allowed categories |
|-------|--------------------|
| maestro, architect, learner | R0 |
| engineer, pm | R0, R1 |
| devops | R0, R1, R2, R3, R4, R5 |
| narrator | R0, R1, R6 |

**Per-agent emitted frontmatter (P2).** Carter emits the allowlist + gates into
each agent, using the canonical mechanism per target:

- **OpenCode:** `permission` (the `tools` boolean is deprecated ≥ v1.1.1) + per-agent
  MCP scope via tool-name patterns.
- **VS Code / Copilot:** an enforced `tools:` allowlist + per-agent `mcp-servers`.

Per-agent MCP scope is emitted in **agent frontmatter**, never the global
`configure_mcp_servers` wiring.

**Global agents (no `carter.yaml` in scope).** Globally-installed static
`agents/*.md` carry baked hand-edited `guarded` defaults, kept honest by a
`test_parity` extension (Q14 / ADR-0005 D6 — build-time generation is WON'T-DO per
[ADR-0002](../adr/0002-single-source-agent-generation.md)).

## See also

- [ADR-0003](../adr/0003-knowledge-adr-rfc-plan-storage.md) — the decision of record
- [ADR-0003 implementation plan](../adr/0003-implementation.md) — execution checklist
