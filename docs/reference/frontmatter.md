# Frontmatter reference

> Canonical schema source for Carter's durable artifacts, and for the strictness
> policy tables (risk taxonomy, per-agent allowlist, emitted rule order).
> This is the **authoritative** definition. The `carter-adr` and `carter-plan`
> skills carry a minimal emittable template for the agent to write from, but this
> page governs — on any discrepancy, this wins, and the Python validator
> (`carter check`) enforces the load-bearing keys/enums against it.

All durable, lifecycle-bearing artifacts carry a YAML frontmatter block. Machines
read the frontmatter; humans read the body. The Python validator (`carter check`)
enforces these schemas before a plan is `active`.

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
must_haves:                   # MANDATORY: >= 1 entry total
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
id: ADR-NNNN                  # four-digit, zero-padded
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

An RFC (design proposal, reviewed before anything is built) is a **directory**
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

## Language of Carter's internal docs (`docs_language`)

```yaml
docs_language: en          # language tag, e.g. en | es | pt-BR (default en)
```

Applies only to Carter's internal documentation: ADRs, RFCs, everything under
`.carter/` (plans, knowledge, checkpoints) and memories. Commit messages, branch
names, code comments, repository docs, PR/issue text, review comments, release notes,
Jira and Slack content are always English. Validated at load time against
`^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*$`; a config without the key resolves to `en`.
Global installs (no `carter.yaml`) default to English unless the user asks otherwise.

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

The risk-based strictness policy is a `policy` block in `carter.yaml`. `guarded` is the floor and the default for
everything: a new install, an existing config that omits the block, and an
unrecognized level all resolve to `guarded`.

```yaml
policy:
  level: guarded            # guarded | strict
  overrides: {}             # category -> gate, explicit per-category override
  # Optional user extension — DICT-shaped so it deep-merges over the shipped
  # default (a list would replace it wholesale; carter/config.py _deep_merge):
  allowlist: {}             # agent -> {category: bool}, e.g. {engineer: {remote-write: true}}
```

**Risk taxonomy (shipped, fixed — 4 categories).** Each maps a strictness level to
a Carter gate (`allow` | `ask` | `gate` | `deny`). OpenCode has no `gate` effect,
so `gate` is emitted as `ask`.

| Category | Meaning | guarded | strict |
|----------|---------|---------|--------|
| read | reads, `git status/log/diff` | allow | allow |
| local-write | file edit, `git add/commit`, run tests | allow | allow |
| remote-write | `git push`, `gh` PR/issue/release/api writes, `vault read/write` | ask | gate (→ ask) |
| dangerous | `terraform apply/destroy`, `kubectl apply`, `helm upgrade`, `rm -rf`, `git reset --hard`, `git push --force` | gate (→ ask) | deny |

**Per-agent allowlist (deny-by-default).** A category absent for an agent is not
granted: its risky shell globs are `deny`, and (for read-only agents) `edit`,
`shell` and `webfetch` ask. `devops` is the sole holder of `remote-write` and
`dangerous`:

| Agent | Allowed categories |
|-------|--------------------|
| maestro, architect, learner | read |
| pm, narrator, engineer, security | read, local-write |
| devops | read, local-write, remote-write, dangerous |

Outward content is **not** a category. The narrator → devops redaction handoff is
prompt-level guidance; OpenCode does not enforce it.

### Emitted agent frontmatter

Every agent file Carter writes carries exactly these V2 keys
([OpenCode agents](https://opencode.ai/v2/docs/agents/)):

| Key | Value |
|-----|-------|
| `description` | One-line role summary |
| `mode` | `primary` (maestro) or `subagent` (everyone else) |
| `model` | One `provider/model[#variant]` string (see below) |
| `permissions` | Ordered rule list, `{action, resource, effect}`; last match wins |

`permissions` is built in this order
([OpenCode permissions](https://opencode.ai/v2/docs/permissions/)):

| # | Rule(s) | Effect |
|---|---------|--------|
| 1 | `*` / `*` | ask (baseline) |
| 2 | `read`, `glob`, `grep`, `skill`, `question` / `*` | allow |
| 3 | `read` `*.env`, `*.env.*` / `read` `*.env.example` | ask / allow |
| 4 | `external_directory` + `read` `~/.carter/*`; `edit` `~/.carter/memories/*` (local-write holders only) | allow |
| 5 | `subagent` `*`; then `subagent` `carter-*` (maestro only) | deny; allow |
| 6 | `edit`, `shell`, `webfetch` / `*` | allow with local-write, else ask |
| 7 | `shell` risky globs: `git push *`, `gh pr create *`, `gh pr merge *`, `gh pr comment *`, `gh pr review *`, `gh pr edit *`, `gh issue create *`, `gh issue comment *`, `gh issue edit *`, `gh release *`, `gh api *`, `vault read *`, `vault write *` (remote-write); `terraform apply *`, `terraform destroy *`, `kubectl apply *`, `helm upgrade *`, `rm -rf *`, `git reset --hard *`, `git push --force *` (dangerous) | the category's gate if held, else deny |

Rule 7 is a representative command list, not a sandbox: a shell command not listed
falls to rule 6. `gh api *` is denied to non-devops agents even for read-only calls.
The only secret-read rules are the `.env` asks (rule 3) and `vault read *` (rule 7).

Anything unlisted (MCP tools, `websearch`, `execute`, …) falls to rule 1. Choosing
"Allow always" at any ask saves a project-scoped allow that bypasses it later.

Carter never emits V1 keys (`permission`, `tools`, `bash`, `task`, `name`,
`temperature`): OpenCode ignores them next to `permissions`. There is no policy
comment in the agent body; the emitted `permissions:` is the single source of truth.

**`carter check` lint.** For each agent it fails if `permissions` or `model` is
missing or differs from what `carter.yaml` generates (exact, ordered match), or if a
V1 key is present. It then runs the harness check below.

### Harness check (`opencode debug agents`)

After the lint, `carter check` runs `opencode debug agents` in the workspace and
fails if OpenCode didn't load a Carter agent, or loaded it with a different
description, model or rules.

- **Skipped** with a warning when `opencode` isn't on `PATH`; `--no-harness` skips it
  explicitly.
- **Starts OpenCode's background service** if it isn't running. That is your shared
  per-user service; `carter check` leaves it running and never stops it. (OpenCode's
  `--standalone` private-server flag is not accepted by `debug agents`, so there is
  no service-free way to run this check.)
- **Guards against stale answers.** The service reloads agent files asynchronously,
  so right after an edit it can still report the previous agents. `carter check`
  first waits until the newest agent file is at least 1.5 s old, then treats a
  result as stale unless every agent's description, model and permission block
  match the file.
- **Retries with backoff.** An empty, incomplete or mismatching result is retried
  (waits of 0.5 + 1 + 2 + 4 s, about 7.5 s worst case, plus call time). If it still
  doesn't match, the check fails and names the agents. An agent OpenCode didn't list
  is reported as not loaded (likely a malformed file). For agents that are listed
  but whose description, model or rules differ, it adds a note that OpenCode may be
  serving stale config — re-run `carter check` to confirm.
- **30-second timeout** per call; a timeout fails the check.
- **A broken `opencode`** (it is on `PATH` but errors or prints invalid output)
  fails the check rather than being skipped.

**Global agents.** `carter install` renders the same templates with the shipped
`guarded` defaults, default models and no suffix into `~/.config/opencode/agents/`.
It does not read any `carter.yaml`, so the keys on this page affect only workspace
agents scaffolded by `carter init`.

## Per-agent model (`models` block)

Each tier is **one** OpenCode model string, `provider/model[#variant]`. The block is
dict-shaped so a user override deep-merges rather than wiping the shipped tiers.

```yaml
models:
  default:      anthropic/claude-opus-5-5
  thinkers:     anthropic/claude-opus-5-5
  implementers: anthropic/claude-sonnet-5-5
  overrides: {}   # per-agent, e.g. {engineer: anthropic/claude-haiku-5-5}
```

Any other shape (a per-target mapping, a list, a string without `provider/`) is a
config error.

**Resolution: `overrides` > `profile` > tier > `default`.** Thinkers (maestro,
architect, learner, security) = Opus 5.5; implementers (engineer, devops, pm, narrator)
= Sonnet 5.5; `default` is the un-tiered catch-all so a future agent never resolves to
an empty model. A `profile:` (`quality` | `budget`) re-tiers roles at resolve time (see
[cost-and-models.md](cost-and-models.md)). **Haiku is opt-in via `overrides` only.**

**`carter check` model advisory.** Carter cannot verify that your OpenCode provider
offers a pinned model, so `carter check` always prints each agent's model with that
caveat.

**Effort and temperature are not emitted.** Use a `#variant` in the model string or
OpenCode's settings for reasoning level; `temperature` is never written.

## See also

- [plans-and-state.md](../plans-and-state.md) — the plan/ADR/checkpoint workflow
- [strictness-policy.md](../strictness-policy.md) — tutorial for the `policy` block
