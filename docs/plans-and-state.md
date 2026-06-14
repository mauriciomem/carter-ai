# Plans, decisions & session state

Carter keeps durable working state on disk so a session can be picked up later —
and so a deleted plan or session is recoverable. This page is the workflow guide;
the exact frontmatter schemas live in [reference/frontmatter.md](reference/frontmatter.md).

## Where things live

| Artifact | Location | Git regime |
|----------|----------|-----------|
| Plans | `.carter/state/plans/{active,completed}/<NNN-slug>/` | nested `.carter/.git` (private) |
| Session checkpoint | `.carter/state/sessions/checkpoint.md` | nested `.carter/.git` (private) |
| Workspace knowledge | `.carter/knowledge/` | nested `.carter/.git` (private) |
| Architecture decisions | `docs/adr/NNNN-*.md` | main repo (reviewable in PRs) |

ADRs are deliberately in the **main repo** — they are shared, reviewable
decisions. Plans/sessions are per-workspace execution state, kept in the nested
`.carter/.git` so they don't clutter the project history (ADR-0003 D5).

## Plans

A plan is a **directory**, not a chat message — written by the `carter-plan`
skill. The directory name equals the `id` (NNN-kebab).

- **1–3 steps:** everything inline in `README.md` (frontmatter + objective +
  `must_haves` + a steps table).
- **More than 3 steps:** each step becomes its own `step-NN.md`; the README links
  to them.
- **Size budgets:** README ≤ 150 lines, each step ≤ 80 lines. Tunable per
  workspace in `carter.yaml` under `plans:`.

Every plan must declare at least one **`must_haves`** entry — the objective,
verifiable definition of done (`truths` / `artifacts` / `key_links`). The quality
gate validates against it; a plan with none is a checklist, not a plan.

**Lifecycle:** `active/<id>/` → `completed/<id>/` when all `must_haves` are met.
The frontmatter `status` is the source of truth, but it must stay **coherent with
the folder**: terminal statuses (`completed`, `abandoned`) belong in `completed/`,
non-terminal ones (`proposed`, `active`, `blocked`) in `active/` — `carter check`
flags a mismatch. Never delete a plan — abandon it (`status: abandoned`) so the
history survives.

## Session checkpoint

`checkpoint.md` is a **thin cursor**: `updated`, `active_plan`, `next_step`, and a
one-line summary. It *points into* the active plan's frontmatter — it never
duplicates plan content. At the start of a session, Maestro reads it to answer
"where were we?"; at natural pauses it offers (suggest-and-confirm) to update it.

## Commands

```bash
carter check .     # validate plan + checkpoint frontmatter against the schema
carter save .      # commit a recovery snapshot of .carter/ (plans, sessions, knowledge)
```

`carter check` rejects an `active` plan with empty `must_haves` and reports any
schema violation. `carter save` is what makes deletion recoverable — run it at
stopping points; a deleted plan is then restorable from `.carter/.git`.

> **Validation is opt-in.** Nothing runs `carter check` automatically — not
> `carter init`, no git hook. The deterministic guarantees (frontmatter contract,
> `must_haves`, checkpoint↔plan integrity) only bite when you run `carter check`.
> Run it after writing or editing a plan, and wire it into CI if you track plans
> in a repo.

## Decisions (ADRs)

Architecture Decision Records are written by the `carter-adr` skill into
`docs/adr/`. Rules (ADR-0003 D4):

- **One ADR = one coherent decision** (interdependent sub-decisions `D1..Dn` may
  bundle if they share one rationale).
- **A change is a new ADR**, never an edit — supersede with `supersedes: ADR-NNNN§Dn`.
- **Budget: ≤ 400 lines.** Over budget → split a sub-area into its own ADR.

Each ADR carries YAML frontmatter (machine-readable) *and* the human Status block.

## See also

- [reference/frontmatter.md](reference/frontmatter.md) — the canonical schemas
- [ADR-0003](adr/0003-knowledge-adr-rfc-plan-storage.md) — the decision of record
- [memory-and-knowledge.md](memory-and-knowledge.md) — knowledge & memory layers
