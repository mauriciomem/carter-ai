# Frontmatter reference

Plans, checkpoints, decision records and RFCs start with a YAML **frontmatter**
block: machine-readable fields between two `---` lines, followed by normal Markdown
for people. This page defines those fields.

`carter check` validates plans and the session checkpoint. The `carter-plan`,
`carter-adr` and `carter-rfc` skills write files in these formats. For the workflow
around them, see [Memory and plans](../guides/memory-and-plans.md).

## Plan `README.md`

Location: `.carter/state/plans/{active,completed}/<id>/README.md`

```yaml
---
id: 001-feature-name          # NNN-kebab-case; must match the directory name
status: active                # proposed | active | blocked | completed | abandoned
created: 2026-06-09           # date (YYYY-MM-DD)
updated: 2026-06-09           # date (YYYY-MM-DD)
adr: null                     # decision record this plan carries out (optional)
rfc: null                     # RFC this plan comes from (optional)
ai-usage: ai-assisted         # optional: ai-assisted | ai-generated | human-only
tags: []
repos: []                     # repositories this plan touches
must_haves:                   # at least one entry in total
  truths: []                  # behaviors or states that must be true
  artifacts: []               # files or resources that must exist
  key_links: []               # references such as PRs or dashboards
---
```

`carter check` enforces:

- `id`, `status`, `created`, `updated` and `must_haves` are present.
- `ai-usage`, when present, is one of `ai-assisted`, `ai-generated` or `human-only`.
- `id` matches the directory name.
- `created` and `updated` are dates (a time may follow).
- `must_haves` has only `truths`, `artifacts` and `key_links`, each a list. A typo
  such as `truth:` is an error.
- An `active` plan has at least one `must_haves` entry.
- The status matches the folder: `completed` and `abandoned` plans live in
  `completed/`; `proposed`, `active` and `blocked` plans live in `active/`.
- The README stays within `plans.readme_max_lines` (default 150).

A key `carter check` doesn't know in a plan's front matter is reported once with its file
(``⚠ unknown key `x` in <path> → delete it``). Such a report never changes the exit code of
`carter check`; only errors do.

### The `ai-usage` field

`ai-usage` marks how a record was produced. It is optional and one of:

| Value | Meaning |
|-------|---------|
| `ai-assisted` | A human wrote or directed it with AI help (the default Carter writes) |
| `ai-generated` | An AI produced it with little or no human editing |
| `human-only` | Written without AI |

The value follows the context of the work, not the agent's role. Carter's record
templates (plan, checkpoint, decision record, RFC, research) write
`ai-usage: ai-assisted`. Ordinary repository docs, such as this page, carry no
frontmatter. A value outside the list is an error in a plan or checkpoint.

## Plan `step-NN.md`

Used when a plan has more than `plans.step_file_threshold` steps (default 3). Shorter
plans keep their steps in a table in the README.

```yaml
---
step: 1
status: pending               # pending | in-progress | done | blocked
depends_on: []                # step numbers this step waits for
files_modified: []            # filled in when the step is done
---
```

Each step file stays within `plans.step_max_lines` (default 80).

## Session `checkpoint.md`

Location: `.carter/state/sessions/checkpoint.md`. A small pointer into the active
plan. It never copies plan content.

```yaml
---
updated: 2026-06-09T18:00:00Z
active_plan: 001-feature-name # plan id, or null
next_step: 4                  # step number, or null
ai-usage: ai-assisted         # optional, same values as for plans
---
```

A one-line summary of where you left off follows. `carter check` requires `updated`,
reports an `active_plan` that doesn't exist under `plans/active/`, and rejects an
`ai-usage` value outside the list above.

## Decision record (ADR)

Location: `docs/adr/` in your repository. Written by the `carter-adr` skill. Next to
the frontmatter, each record keeps a readable Status / Date / Deciders block.

```yaml
---
id: ADR-NNNN                  # four digits, zero-padded
status: accepted              # proposed | accepted | rejected | superseded | deprecated
created: 2026-06-07
decided: 2026-06-09           # null until accepted
supersedes: []                # earlier record ids, optionally with a section (§D3)
superseded_by: null
rfc: null                     # the RFC this decision came from (optional)
ai-usage: ai-assisted         # optional, same values as for plans
tags: [storage, plans]
---
```

A change of mind is a **new** record that supersedes the old one; accepted records
are not edited. Records over 400 lines are split.

## RFC

Location: `docs/rfcs/NNNN-name/README.md` in your repository. Written by the
`carter-rfc` skill. An RFC is a design proposal that agents review before anything
is built.

```yaml
---
id: RFC-NNNN
status: draft                 # draft | review | accepted | rejected | withdrawn
revision: 1                   # increase only for a material change
created: 2026-06-10
decided: null                 # date accepted, rejected or withdrawn
author: your-github-user
adr: null                     # the decision record it produced, once accepted
plan: null                    # the plan that carries it out, once created
supersedes: []
ai-usage: ai-assisted         # optional, same values as for plans
tags: []
---
```

Reviews live next to it in `review-<agent>.md`, newest round first. A review is
current when its latest round reviewed the RFC's current `revision`. Accepted,
rejected and withdrawn RFCs are frozen; replace them with a new RFC.
