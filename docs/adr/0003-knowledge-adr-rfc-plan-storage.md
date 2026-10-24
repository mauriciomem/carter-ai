---
id: ADR-0003
status: accepted
created: 2026-06-07
decided: 2026-06-09
supersedes: []
superseded_by: null
tags: [storage, metadata, plans, adr]
---

# ADR-0003: Knowledge, ADRs, RFCs & plans — storage, frontmatter & splitting

> **Status note (2026-10-24):** `plans.git_regime` was never read by code and was removed from the config; the companion `0003-implementation.md` checklist was deleted.

**Status:** Accepted
**Date:** 2026-06-07 (proposed), 2026-06-09 (accepted)
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Scope:** Storage, metadata, git-trackability, and splitting of knowledge files,
ADRs, RFCs, and plans. **Not** general Carter improvements.

---

## Context

A read-only audit of how Carter stores its durable artifacts surfaced an
inconsistent metadata model, three "phantom contracts" (agent prompts that
reference structured artifacts nothing produces), and a complete-but-unbuilt
design for exactly this problem.

### Current storage (verified against source)

| Artifact | Location | Format | Git regime | Created by |
|----------|----------|--------|-----------|------------|
| Workspace knowledge | `<ws>/.carter/knowledge/` (5 files) | plain MD, **no metadata** | private nested `.carter/.git`; `.carter/` gitignored from main repo in single mode | [carter/state.py](../../carter/state.py) `KNOWLEDGE_FILES` |
| System knowledge | `~/.copilot/knowledge/` (6 files) | plain MD, **no metadata** | manifest-tracked, no git | [carter/installer.py](../../carter/installer.py) `install_knowledge` |
| Memory | `~/.carter/memories/{user,session,repo}/` | freeform MD | none | `install_memories` |
| ADRs | `docs/adr/NNNN-*.md` | **bold header fields**, not YAML | main repo | `carter-adr` skill (manual) |
| Plans | `<ws>/.carter/state/plans/{active,completed}/` | **dirs created empty** | private `.carter/.git` | `init_workspace` (dirs only) |
| Sessions | `<ws>/.carter/state/sessions/` | **dir created empty** | private `.carter/.git` | `init_workspace` (dir only) |
| RFCs | — | **do not exist** | — | — |

### Three git regimes (deliberate, but unexamined)

Three regimes already exist: **main repo** (knowledge/, docs/adr/, skills);
**private nested repo** (`<ws>/.carter/` gets its own `git init` via
[state.py](../../carter/state.py) `_git_init`, gitignored from the host in
single mode); **manifest-only** (`~/.copilot/`, `~/.carter/`). So artifacts *can*
be git-tracked — three ways. The unexamined question (settled in D5) is *which*
regime each should use: reviewable-in-PR vs. local-uncoupled.

### The metadata is inconsistent

- **Skills** — proper YAML frontmatter ✓
- **ADRs** — bold text fields (`**Status:**`), human-readable but **not
  machine-parseable** ✗
- **Knowledge** — no metadata ✗
- **Plans** — no metadata, because **plans are never generated** ✗

### Three phantom contracts (the core defect)

Agent prompts already assume a structured artifact model that **nothing
produces**:

1. **Plans + `must_haves`.** Maestro reads `.carter/state/plans/active/` at
   session start and injects a plan's `must_haves` into reviewers
   ([carter-maestro.md.j2](../../templates/agents/carter-maestro.md.j2) §session_bootstrap, §quality_gate).
   The pm agent claims *"Plans go to `.carter/state/plans/active/`"*
   ([carter-pm.md.j2](../../templates/agents/carter-pm.md.j2)). But
   [skills/carter-plan/SKILL.md](../../skills/carter-plan/SKILL.md) emits **flat
   Markdown to chat** — it writes no files and no `must_haves`.
2. **`checkpoint.md`.** Maestro reads `.carter/state/sessions/checkpoint.md` for
   last-session state. **Nothing ever writes it.**
3. **The empty dirs.** `plans/active`, `plans/completed`, `sessions` are created
   but never populated by any code path.

### A complete design already exists, unbuilt

docs/analysis/implementation-plan.md (record no longer in repo) §8
specifies almost exactly this: multi-file plans with frontmatter
(`id/status/must_haves/push_policy/rfc`), per-step `depends_on`, a single-folder
RFC system, and a note that *"carter-plan SKILL needs updating."*

### Problem statement

1. Resolve the phantom contracts — make the model real, or delete the references.
2. Adopt one **deterministic metadata** standard (machine-parseable, recoverable).
3. Decide the **splitting criterion** for plans, RFCs, and ADRs.
4. Decide **whether to add RFCs** at all (ADR-as-proposal worked this session).

---

## Decision

Seven sub-decisions. They are interdependent (one metadata model, one storage
tree) and recorded as one ADR with labeled D1–D7 so any can be superseded by
reference later (the convention from ADR-0001/0002).

### D1 — Adopt YAML frontmatter as the universal metadata standard

Every durable, lifecycle-bearing artifact carries a YAML frontmatter block. This
is the keystone — it makes status, dependencies, and verification criteria
machine-readable, which is the precondition for session recovery and the
quality-gate `must_haves` contract that **already exists in the prompts**.

- **Plans / steps:** mandatory frontmatter (schema below).
- **ADRs:** add YAML frontmatter **and keep** the human "Status" block we
  introduced this session (machines read the frontmatter; humans landing on a
  long ADR read the block).
- **Knowledge:** light touch — optional `scope: universal | workspace` + `tags`
  on entries that need portability (per implementation-plan Q4); the 5 hardcoded
  files keep their current shape.

### D2 — Plans: written to disk, split by explicit rigid rules, fix the phantom contract

Rewrite [skills/carter-plan/SKILL.md](../../skills/carter-plan/SKILL.md) so plans
are **written to disk** under `.carter/state/plans/active/<NNN-slug>/`, not
emitted only to chat.

**Splitting rules — explicit, rigid, deterministic (per maintainer):**

1. **Every plan is a directory** `plans/active/<NNN-slug>/` with a `README.md`
   (frontmatter + objective + `must_haves` + steps table). No single-file plans;
   the directory is the unit.
2. **Step files are mandatory when steps > 3.** 1–3 steps live inline in the
   README steps table. With **> 3 steps**, each step is its own `step-NN.md`
   (frontmatter `status`/`depends_on` + tasks + done-criteria); the README table
   links to them.
3. **Hard size budget.** A `README.md` > 150 lines or any `step-NN.md` > 80
   lines MUST be split (extract detail into step files / sub-sections). No file
   in a plan exceeds these budgets.
4. **One step = one independently-statusable unit.** If something needs its own
   `status` or `depends_on`, it is a step (its own file once rule 2 trips) —
   never a bullet buried in prose.

**Thresholds are configurable defaults (O2).** The four numbers above are
*defaults* surfaced in `carter.yaml` so a workspace can tune them; the
*structural* rules (every plan is a directory, status in frontmatter, step =
independent unit) are invariant and NOT configurable. Proposed block:

```yaml
plans:
  step_file_threshold: 3     # > N steps → per-step files
  readme_max_lines: 150
  step_max_lines: 80
  git_regime: private        # private | workspace (umbrella only); see D5
```

The Python validator (O3) reads these, so enforcement stays deterministic *per
workspace*. The **ADR 400-line budget is NOT workspace config** (ADRs live in the
main repo, outside any `.carter/`) — it is a `carter-adr` skill constant (D4).

Lifecycle: `active/<id>/` → `completed/<id>/` when all `must_haves` are satisfied
(pm verifies). Status lives in frontmatter; the folder move is a coarse index,
not the source of truth.

### D3 — RFC and ADR are DISTINCT artifacts; keep both (detailed RFC design deferred)

**Reversed from the first draft.** An RFC is *not* a "Proposed ADR" — they serve
different phases and must not be collapsed:

| | RFC | ADR |
|---|-----|-----|
| Question | "**Should** we do X?" — exploratory | "We **decided** X, and why" — record |
| Phase | *before* a decision exists | *at / after* the decision |
| Mutability | evolves through discussion; may be withdrawn | immutable once Accepted (supersede, never edit) |
| Outcome | may yield one or more ADRs, or nothing | the durable decision of record |
| Risk if collapsed | a "Proposed ADR" pre-commits the framing and discourages genuine exploration | — |

**Decision:** keep RFCs and ADRs as **separate, linked** artifacts. An RFC
explores; an accepted RFC yields an ADR; an ADR records. They cross-reference
(`adr ↔ rfc` ids) but never substitute.

**Deferred (maintainer's request):** the *detailed* RFC design — storage,
lifecycle/statuses, reviewers, how it links to plans and ADRs — is **its own assessment** (prospective ADR-0004). This
ADR records only the *principle* (RFC ≠ ADR, both kept) and leaves the design to
that assessment.

### D4 — ADRs: one decision per file, frontmatter + status block, rigid split rules

- **Frontmatter** (D1) augments — does not remove — the human status block.
- **Splitting rules (explicit, rigid):**
  1. **One ADR = one coherent decision.** It MAY bundle labeled sub-decisions
     `D1..Dn` ONLY if they are interdependent (share one rationale/boundary, as
     in ADR-0001/0002). Independent decisions go in separate ADRs.
  2. **A change or reversal is a NEW ADR, never an edit.** An Accepted ADR is
     immutable; a later decision creates a new ADR with `supersedes:
     ADR-NNNN§Dn`. (This session's "append follow-ups to ADR-0002" pattern is
     explicitly disallowed going forward. Backfilling *frontmatter* is a metadata
     addition, not a decision change, and is permitted.)
  3. **Hard size budget:** an ADR > 400 lines MUST be split (extract a sub-area
     into its own ADR). We hit this with ADR-0002. This 400-line budget is a
     `carter-adr` **skill constant**, not workspace config — ADRs live in the
     main repo, outside any `.carter/`, so `carter.yaml` cannot govern them (O2).
- **Status block + superseded markers** (this session's convention) remain the
  human-facing mitigation alongside frontmatter.

### D5 — Storage & git regime per artifact (mode-derived) + ongoing history

| Artifact | Location | Git regime | Rationale |
|----------|----------|-----------|-----------|
| ADRs | `docs/adr/` (main repo) | **main repo** | Reviewable in PRs, shared, recoverable from the project remote. Unchanged. (RFCs will follow the same main-repo regime; location TBD in ADR-0004.) |
| Plans | `.carter/state/plans/` | **mode-derived** (below) | Execution state is per-workspace, recovery-oriented, churns fast. Now actually populated. |
| Workspace knowledge | `.carter/knowledge/` | private `.carter/.git` | Per-workspace learnings; unchanged. |
| Sessions / `checkpoint.md` | `.carter/state/sessions/` | private `.carter/.git` | Recovery cursor; per-workspace. |
| System knowledge / memory | `~/.copilot/`, `~/.carter/` | manifest / none | Global; unchanged. |

**Mode-derived regime for plans (resolves O7).** The lever is `workspace.mode`
(`carter init --single` vs. default umbrella), which already gates the gitignore +
nested-repo behavior in [cli.py](../../carter/cli.py):

- **single mode** — Carter overlays a repo the user already owns; `.carter/` is
  gitignored from that host repo, so plans stay **private** to the nested
  `.carter/.git`. (Current behavior, unchanged.)
- **umbrella mode** — the workspace *is* Carter-owned; plans **may** be tracked in
  the umbrella repo (reviewable), gated by `plans.git_regime: private | workspace`
  (default `private`). “global-vs-workspace install” is **not** the axis — global
  `carter install` has no plan storage at all; only `carter init` creates plans.

**Ongoing history is mandatory (resolves the recovery gap).** Today
[state.py](../../carter/state.py) commits the nested `.carter/.git` **once** at
init (`chore: init carter state`) and never again — so “I deleted a session
folder” is *not* recoverable, contradicting this regime's “history without
coupling” promise. The nested repo MUST carry **ongoing history**: auto-commit on
write at plan/checkpoint/session boundaries (suggest-and-confirm where
user-facing). That single behavior is what makes deletion-recovery real and
closes the recovery half of the phantom contracts (D7).

**Off-machine backup is explicitly deferred** (prospective **ADR-0005**).
Surviving loss of the *whole* workspace folder — private-remote push via
`push_policy` vs. a global `~/.carter/` mirror vs. a cross-project catalog — is a
*durability* concern with a redaction/secrets-boundary dimension, distinct from
storage layout. It gets its own assessment (see the Deferred note in the phased
plan).

### D6 — Frontmatter schema (merged, Carter-tuned)

The **canonical schemas live in [docs/reference/frontmatter.md](../../docs/reference/frontmatter.md)** —
one source; duplicating them here would invite the drift this ADR fights. The
keystone is the plan `README.md`:

```yaml
---
id: 001-feature-name          # NNN-kebab; matches directory name
status: active                # proposed | active | blocked | completed | abandoned
created: 2026-06-07
updated: 2026-06-07
adr: null                     # ADR-NNNN if this plan executes an accepted ADR
push_policy: manual           # manual | auto  (never push without approval = manual)
tags: []
repos: []                     # repos this plan touches (multi-repo work)
must_haves:                   # objective, verifiable completion criteria
  truths: []                  #   - observable behaviors/states that must be true
  artifacts: []               #   - files/resources that must exist
  key_links: []               #   - canonical references (PRs, dashboards)
---
```

Step files (`step-NN.md`), ADR frontmatter, and the `checkpoint.md` cursor follow
the same standard (see the reference). Rationale for `must_haves: {truths,
artifacts, key_links}` over §8's flat list: the sub-structure maps to
how the quality gate reasons (verify a *state*, confirm an *artifact*, follow a
*link*), and it has existing test coverage to copy.

### D7 — Resolve all three phantom contracts

1. **Plans:** D2 makes `carter-plan` write the structured files maestro/pm
   already reference. The contract becomes real.
2. **`checkpoint.md` — build it (O4).** It is a phantom reference today (nothing
   has ever written it). Decision: **(a)** the maestro writes/updates
   `.carter/state/sessions/checkpoint.md` **suggest-and-confirm** at natural pause
   points, as a **thin cursor** — frontmatter (`updated`, `active_plan`,
   `next_step`) + a one-line summary that **points into** the active plan's
   frontmatter (the source of truth). It must never duplicate plan content, so the
   three session-state layers (`/memories/session/`, `checkpoint.md`, plan
   frontmatter) don't re-create the drift this ADR fixes.
3. **pm claim vs. reality:** aligned automatically once D2 lands.

---

## Options Considered

| Axis | Chosen | Rejected alternatives |
|------|--------|-----------------------|
| **A — Metadata format** | A2 YAML frontmatter (greppable, used by skills) | A1 plain MD (not machine-parseable); A3 sidecar JSON/TOML (two files to sync) |
| **B — Plan splitting** | B3 tiered by size (≤3 steps inline, dir+steps beyond) | B1 single file (steps can't carry status); B2 always dir+steps (ceremony for small tasks) |
| **C — RFC vs ADR** | C2 distinct, linked artifacts | C1 collapse to "Proposed ADR" (pre-commits framing); C3 design full RFC now (deferred to ADR-0004) |
| **D — ADR header** | D-2 frontmatter + human status block | D-1 bold fields only (not machine-readable) |
| **E — must_haves shape** | E2 `{truths, artifacts, key_links}` (maps to quality gate; tested) | E1 flat list (loses structure) |
| **F — Plans git regime (O7)** | F3 mode-derived (single→private; umbrella may track) | F1 always private (never reviewable); F2 always main-repo (breaks single-mode isolation) |
| **G — Recovery (O7 follow-up)** | G2 ongoing auto-commit in `.carter/.git` | G1 one init commit (deletions unrecoverable); G3 global mirror (crosses redaction boundary; → ADR-0005) |

---

## Consistency contracts (normative — implementation MUST honor)

| Rule | Why |
|------|-----|
| Plans are **written to disk**, never only chat | Resolves phantom contract #1; enables recovery |
| Every plan has a non-empty `must_haves` (≥ 1 entry) | The quality gate verifies against it; a plan with none is a checklist (O6) |
| Status lives in **frontmatter**; folders are a coarse index | Single source of truth; no status-via-move ambiguity |
| `carter-plan` owns plan files; `carter-adr` owns ADRs; no overlap | Anti-drift, mirrors ADR-0001's delegation discipline |
| RFC and ADR stay distinct, linked artifacts (never collapsed) | D3; detailed RFC design deferred to ADR-0004 |
| Frontmatter is validated **in Python** before a plan is `active` | Determinism is only useful if enforced; not model-dependent (O3) |
| Numeric thresholds are config (`plans:`); structural rules are invariant | Tunable per workspace without fragmenting the format (O2) |
| The nested `.carter/.git` carries **ongoing history** (auto-commit) | Makes deletion-recovery real; closes the D5 “history” promise |

---

## Consequences

### Positive
- The phantom contracts become real: session recovery, must_haves-driven review,
  and "where were we?" all start working.
- One greppable metadata model across plans/ADRs (+ optional knowledge), enforced
  deterministically in Python (O3).
- Deletion-recovery becomes real: ongoing auto-commit in `.carter/.git` means a
  deleted plan/session/folder is restorable without any off-machine copy.
- RFC and ADR stay cleanly separated (D3); no framing pre-commitment.


### Costs / risks
- **`carter-plan` rewrite** is the biggest piece — it changes a skill from
  "emit prose" to "write a file tree," and needs the Python validator + tests.
- **The validator is new `carter` code** (O3) — deterministic, but it must read
  the `plans:` config thresholds and stay in lockstep with the D6 schema.
- **Ongoing auto-commit** adds commit churn to `.carter/.git` and a new write
  behavior; keep it scoped to plan/checkpoint/session boundaries and quiet.
- **Knowledge frontmatter is optional/loose** — risk of half-adoption; mitigate
  by keeping it genuinely optional, not half-mandatory.
- **`checkpoint.md` writer** adds a small new maestro behavior; keep it
  suggest-and-confirm (like knowledge capture) to avoid surprise writes.
- **Backup remains unsolved until ADR-0005** — auto-commit protects against
  deletion *within* a surviving folder, not loss of the whole workspace.
- Touches docs again (getting-started workspace tree, memory-and-knowledge,
  carter-ops if push_policy interacts with ops).

---

## Implementation

The phased execution checklist (5 phases, 13 steps) lives in its companion,
0003-implementation.md (record removed 2026-10), extracted to keep this ADR under
its own 400-line budget (D4 rule 3). Execute only after acceptance (now granted).

> **Deferred to their own assessments:** detailed **RFC** design → prospective
> **ADR-0004** (D3); **off-machine backup / durability** → prospective
> **ADR-0005**. Both out of scope here.

---

## Decisions resolved

- **RFC ≠ ADR (D3, Axis C).** Reversed the first draft's collapse of RFC into
  "Proposed ADR." RFC (explore) and ADR (record) are distinct, linked artifacts;
  both kept. Detailed RFC design deferred to ADR-0004.
- **Rigid splitting (D2, D4).** Explicit, deterministic rules (plans: directory
  always, step files when > 3 steps, 150/80-line budgets; ADRs: one decision per
  file, change = new ADR not an edit, 400-line budget).
- **Quality gate valued** — it verifies against `must_haves`, which underpins
  O6 = mandatory `must_haves`.

**Open decisions — all resolved (2026-06-09).** This ADR is **Accepted**;
implementation may proceed.

1. **O1 — RFC stance** → keep RFC/ADR distinct (D3); detailed RFC design → ADR-0004.
2. **O2 — Thresholds** → configurable `plans:` defaults; ADR ≤ 400 a `carter-adr`
   skill constant (D2, D4).
3. **O3 — Enforcement** → Python validator, deterministic, not model-dependent
   (Phase 2).
4. **O4 — `checkpoint.md`** → build (first time) as a thin, suggest-and-confirm
   cursor pointing into plan frontmatter (D7.2).
5. **O5 — Schema** → merged D6 (`must_haves: {truths, artifacts, key_links}`).
6. **O6 — `must_haves` mandatory** → yes, every plan (≥ 1 entry), validator-enforced.
7. **O7 — Plans git regime** → mode-derived; default private; umbrella may track
   via `plans.git_regime` (D5). "global vs. workspace install" is not the axis.
- **Recovery (from the O7 discussion)** → ongoing auto-commit in `.carter/.git` is
  mandatory so deletions are recoverable (D5, D7, Axis G).
- **Off-machine backup** → deferred to ADR-0005 (durability + redaction boundary).

---

## References

- ADR-0001 ([0001-narrator-content-suite.md](0001-narrator-content-suite.md)) — labeled-sub-decision + anti-drift pattern; ADR-0002 ([0002-single-source-agent-generation.md](0002-single-source-agent-generation.md)) — status-block + superseded-marker convention
- Carter design (unbuilt) — docs/analysis/implementation-plan.md (record no longer in repo) §8 + Q5
- Source: [carter/state.py](../../carter/state.py), [skills/carter-plan/SKILL.md](../../skills/carter-plan/SKILL.md), [skills/carter-adr/SKILL.md](../../skills/carter-adr/SKILL.md), [templates/agents/carter-maestro.md.j2](../../templates/agents/carter-maestro.md.j2), [templates/agents/carter-pm.md.j2](../../templates/agents/carter-pm.md.j2)
