---
id: ADR-0004
status: accepted
created: 2026-06-10
decided: 2026-06-10
supersedes: []
superseded_by: null
tags: [rfc, process, storage, design]
---

# ADR-0004: RFC system — a lightweight design-proposal process

**Status:** Accepted
**Date:** 2026-06-10
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** ADR-0003 §D3 deferred the *detailed* RFC design to this ADR (kept the
principle: RFC ≠ ADR, both retained and linked).

---

## Context

ADR-0003 §D3 settled the *principle* — an RFC (explore "should we?") and an ADR
(record "we decided") are distinct, linked artifacts — and explicitly deferred
the **detailed design** (storage, lifecycle, reviewers, linkage) to this ADR.

### The precedent ADR-0003 just set

ADR-0003 split durable artifacts cleanly by nature:

- **ADRs** — single file in `docs/adr/`, status in frontmatter **+ human block**,
  **no status folders**, governed by the `carter-adr` *skill* (not Python).
- **Plans** — directory + `active/`/`completed/` **folders** in `.carter/` private
  state, **Python-validated** (`carter check`), because they are churning
  execution state with steps and recovery semantics.

This gives a sharp decision rule for RFCs: **which is an RFC more like — an ADR or
a plan?** An RFC is a *design document* (problem / proposal / alternatives), not
execution state with steps. It is reviewed and either yields an ADR or is dropped.
It is therefore **an ADR-shaped artifact**, and consistency says model it on the
ADR, not the plan folder machinery.

### Problem statement

1. Pick the RFC **storage + shape** (ADR-like single file vs. plan-style folders).
2. Define **frontmatter, lifecycle, statuses**.
3. Define the **reviewer model** against Carter's *actual* agent set.
4. Define **RFC ↔ ADR ↔ plan linkage**.
5. Decide the **authoring home** (new skill vs. extend `carter-adr`) and whether
   RFCs are **validated** (Python) or **skill-governed** (like ADRs).

---

## Decision

A lightweight RFC process that borrows the ADR's **lifecycle and main-repo
regime** but stores each RFC as a **directory** so multiple experts can contribute
first-class, attributable reviews — the multi-perspective contrast that *is*
"Request for Comments." Eight interdependent sub-decisions (one storage/lifecycle
model), labelled D1–D8 so any can be superseded by reference.

### D1 — ADR lifecycle + directory-per-RFC for first-class reviews

An RFC borrows the ADR's regime (main repo, frontmatter status, freeze-on-decide,
supersede-don't-edit) but is **not** a bare single file: it is a directory holding
the proposal **and** one review file per reviewing agent. The directory exists so
that *any* Carter subagent can contrast the idea from its expertise — the value of
an RFC. There are no draft/review/approved/rejected folders and the RFC directory never moves; only
frontmatter status changes. (Plans get folders + a Python validator because they
are churning machine-recovered runtime state; an RFC is human-reviewed prose.)

### D2 — Storage: `docs/rfcs/NNNN-kebab-name/`, main repo, no status folders

```
docs/rfcs/
├── 0001-rfc-system/
│   ├── README.md            ← the proposal (frontmatter + sections)
│   ├── review-architect.md  ← one file per reviewing agent
│   └── review-engineer.md
└── README.md                ← index table (by frontmatter status)
```

- **Main repo** — reviewable in PRs, shared, recoverable from the project remote;
  the same regime as ADRs. **Rejected:** `.carter/` private state (RFCs are shared
  design artifacts, not per-workspace runtime).
- **No status folders.** Status lives in frontmatter; the directory never moves.
- The index `README.md` lists RFCs by status.

### D3 — Frontmatter schema (+ human status block)

Mirror the ADR pattern: machine-readable frontmatter **and** a human header block.

```yaml
---
id: RFC-0001
status: draft                 # draft | review | accepted | rejected | withdrawn
revision: 1                   # bump only on a material change to the proposal
created: 2026-06-10
decided: null                 # date when accepted/rejected
author: mauriciomem
adr: null                     # ADR-NNNN produced by this RFC, when accepted
plan: null                    # NNN-slug plan that executes it, when created
supersedes: []                # RFC ids this replaces
tags: []
---
```

Canonical schema entry **to be added** to [docs/reference/frontmatter.md](../reference/frontmatter.md) (implementation sketch, step 1).

### D4 — Lifecycle & statuses

```
draft → review → accepted  (→ yields an ADR, then a plan)
              └→ rejected
draft|review → withdrawn   (author drops it)
```

- `draft` — being written. `review` — open for reviewer input. `accepted` — the
  proposal is adopted; it should now produce an **ADR** (the durable decision) and
  then a **plan** (execution). `rejected` — declined, with a `## Decision`
  rationale appended. `withdrawn` — author abandons before a decision.
- Status changes are **frontmatter edits**, not directory moves. The human status
  block and a `## Decision` section record the outcome for readers.
- An RFC is **mutable while draft/review** and **frozen once accepted/rejected**
  (like an ADR — supersede, don't edit).

**Revisions & rounds (lightweight).** Bump `revision: N` only on a *material*
change to the proposal — mirroring PEP's `Post-History`/Change-History convention
(a significant rewrite gets a new recorded entry). Re-reviews are **appended
newest-first** as `## Round N` sections inside each reviewer file (the same
reverse-chronological pattern PEP formalized in 2026). **Git is the authoritative
revision history** — both Rust RFCs and PEPs rely on git, not a tracked field; the
`revision` integer and round headers are a human-readable cursor over it.

### D5 — Reviewer model: any expert, advisory, maestro-synthesized

Any Carter subagent may review an RFC from its expertise — the multi-perspective
contrast is the point. To keep signal high, reviews are **domain-triggered**, not
all-agents-always:

- **carter-architect** reviews **every** RFC (design coherence, alternatives) —
  the RFC owner.
- **carter-engineer** — code/test feasibility, plus its security pass (auth,
  secrets, external services, trust boundaries).
- **carter-devops** — CI/CD, deployment, infra impact. **carter-pm** — scope,
  sequencing. **carter-narrator** — external-facing/redaction impact.
- maestro (orchestrates) and learner (explains) do **not** review.
- Each reviewer writes `review-{agent}.md`, appending `## Round N — <date> —
  reviewed revision M — verdict: approve | request-changes | reject`.
- **Advisory, never voting.** Reviews *inform*; the **maestro synthesizes**
  divergent reviews into one recommendation at the decision gate (D8); the **user
  decides**. Divergence is surfaced, not auto-resolved.

### D6 — Linkage: RFC ↔ ADR ↔ plan

A traceable chain *idea → RFC → ADR → plan → code*:

- RFC frontmatter: `adr:` (the ADR it produced) and `plan:` (the plan executing it).
- ADR frontmatter: add an optional `rfc:` field pointing back (extends the
  ADR-0003 §D6 ADR schema — a metadata addition, not a decision change).
- Plan frontmatter already carries `adr:`; add optional `rfc:` likewise.

### D7 — Authoring home + validation regime

- **New `carter-rfc` skill** (mirrors `carter-adr`): emits the frontmatter + the
  section template, owned conceptually by **carter-architect**. **Rejected:**
  folding RFCs into `carter-adr` — different phase (propose vs. record), and one
  skill per artifact keeps the anti-drift delegation discipline (ADR-0001).
- **Skill-governed, not Python-validated.** RFCs live in the main repo (like
  ADRs), so `carter check` — which validates `.carter/` workspace state — does
  **not** touch them. Determinism for RFCs is the skill checklist, exactly as for
  ADRs. (Plans get Python validation because they are machine-recovered runtime
  state; RFCs are human-reviewed prose.) The `carter-rfc` review template makes
  "reviewed revision M" a **required, visible slot** so omitting it is obviously
  wrong (D8).

### D8 — Enforcing the review-revision discipline (no code, four mechanisms)

The one soft spot is that a reviewer might forget to state which `revision` it
reviewed, silently breaking staleness detection. Enforced **without** a validator
(which would reintroduce the ceremony we avoided), via four layers grounded in the
Rust/PEP processes and the fail-safe-defaults principle:

1. **Template forcing (pit of success).** The `carter-rfc` review section template
   carries `reviewed revision: <M>` as a required slot; an omission leaves a
   visibly-wrong placeholder. (Rust and PEP both reject off-template submissions.)
2. **Fail-safe default.** A review with a missing or unparseable revision marker
   is treated as **stale** (needs re-review), never current — forgetting degrades
   to the safe, conservative state, not a silent pass.
3. **Synthesis gate.** The maestro **must** consolidate reviews before presenting
   the decision (mirroring Rust's pre-FCP sign-off), computing currency
   (`reviewed revision` vs the RFC's `revision`) and flagging stale/missing ones.
   The decision cannot be reached without passing through this gate.
4. **Git is the backstop.** `revision` + round headers are convenience; the
   authoritative history is git, so even total discipline failure loses
   convenience, not the record — `git log` recovers what changed and when.

### When to write an RFC (threshold)

Affects **> 3 files**, introduces a **new agent or skill**, or changes Carter's
**architecture** → RFC first. Otherwise → straight to a plan. (Inherited from
implementation-plan Q5; mirrors the plan-vs-just-do pragmatism.)

---

## Options Considered

| Axis | Chosen | Rejected |
|------|--------|----------|
| **A — Shape** | A2 ADR lifecycle + **directory-per-RFC** (no status folders) | A1 status folders + dir moves (ceremony); A3 bare single file (can't hold first-class per-agent reviews) |
| **B — Location/regime** | B1 `docs/rfcs/` main repo (reviewable like ADRs) | B2 `.carter/` private state (RFCs are shared, not per-workspace); B3 `.rfcs/` local-only |
| **C — Status tracking** | C1 frontmatter only, dir never moves | C2 four status folders with dir moves (over-engineered) |
| **D — Reviews** | D1 **per-agent `review-{agent}.md` + appended rounds** (attributable multi-perspective) | D2 inline-only `## Reviews` (loses attribution + first-class re-review); D3 status-folder ceremony |
| **E — Authoring** | E1 new `carter-rfc` skill | E2 extend `carter-adr` (conflates propose vs. record) |
| **F — Validation** | F1 skill-governed (like ADR) | F2 Python `carter check` (RFCs aren't `.carter/` state) |
| **G — Review discipline** | G1 template + fail-safe default + synthesis gate + git (D8) | G2 Python revision-marker check (re-adds the ceremony we avoided) |

---

## Consistency contracts (normative)

| Rule | Why |
|------|-----|
| RFCs live in `docs/rfcs/`, main repo, one **directory** each | Reviewable like ADRs; the dir holds first-class per-agent reviews |
| Status in frontmatter; the RFC directory never moves | Single source of truth; no move-ceremony |
| An accepted/rejected RFC is frozen — supersede, don't edit | Same immutability rule as ADRs (ADR-0003 §D4) |
| `carter-rfc` owns RFCs; `carter-adr` owns ADRs — no overlap | Anti-drift delegation (ADR-0001) |
| An accepted RFC yields an ADR before a plan executes it | Preserves the explore→record→execute chain |
| RFC ↔ ADR ↔ plan cross-link via frontmatter ids | Traceability |
| Reviews are advisory; the maestro synthesizes; the user decides | Multi-perspective without deadlock |
| Every review states the revision it reviewed; missing → stale | Fail-safe staleness (D8) |

---

## Consequences

### Positive
- **Multi-expert contrast without ceremony:** any relevant subagent contributes an
  attributable, independently-revisable review — the core RFC value — with no
  status-folder machinery and no Python validator.
- One regime for design docs: RFC and ADR share the main repo, frontmatter status,
  freeze rule, and the `carter-{rfc,adr}` skill pattern; only the phase differs.
- Reviewable in PRs; git is the authoritative revision + review history.
- Round/staleness discipline is grounded in the Rust/PEP processes, not invented.

### Costs / risks
- **Directory-per-RFC** is slightly heavier than a flat file (justified by
  first-class reviews).
- **New `carter-rfc` skill** + a `docs/rfcs/` index to maintain.
- **Relies on reviewer discipline** for revision markers — mitigated, not
  eliminated, by the D8 fail-safe + synthesis gate (no hard validation by design).
- **Frontmatter additions** (`rfc:` on ADRs and plans) — small, backward-compatible.

---

## Implementation sketch (only after acceptance)

1. Create `docs/rfcs/` with a `README.md` index; add the RFC frontmatter entry
   (incl. `revision`) to `docs/reference/frontmatter.md`.
2. Add the `carter-rfc` skill (mirror `carter-adr`): proposal `README.md` template
   + a `review-{agent}.md` template whose `## Round N — reviewed revision M —
   verdict` header makes the revision a required slot; freeze/supersede + budget.
3. Add optional `rfc:` to the ADR and plan frontmatter schemas (metadata-only).
4. Wire maestro/architect: "design proposal → carter-rfc → domain reviewers append
   `review-{agent}.md` → maestro synthesis gate (flag stale vs `revision`) → user
   decides → accepted → carter-adr → carter-plan."
5. Dogfood: write RFC-0001 ("the RFC system") describing this very process.

---

## Decisions resolved (review 2026-06-10)

1. **O1 — Shape:** ADR lifecycle + **directory-per-RFC**, no status folders (D1/D2).
   Reversed the first draft's bare single file — a directory is needed to hold
   first-class per-agent reviews.
2. **O2 — Authoring:** new **`carter-rfc`** skill (D7).
3. **O3 — Validation:** **skill-governed** like ADRs, not `carter check` (D7/D8).
4. **O4 — Reviews:** **per-agent `review-{agent}.md` files** (not inline-only) —
   any expert contributes an attributable, independently-revisable perspective;
   advisory, maestro-synthesized (D5). *Reversed from the first draft per
   maintainer: the multi-crew review is the value; only the status-folder ceremony
   is dropped.*
5. **O5 — Status enum:** `draft | review | accepted | rejected | withdrawn` (D4) —
   matches the PEP set (Withdrawn = author drops it).
6. **O6 — Naming:** keep `RFC-NNNN` ids + `NNNN-kebab-name/` directories (mirrors
   the ADR pattern; RFCs are ADR-regime artifacts).
7. **Rounds (new):** lightweight iterative re-review — `revision: N` bumped on
   material change, rounds appended newest-first, staleness derived, git
   authoritative (D4); discipline enforced by D8 (template + fail-safe + synthesis
   gate + git), grounded in the Rust/PEP processes.

---

## References

- ADR-0003 §D3 ([0003-knowledge-adr-rfc-plan-storage.md](0003-knowledge-adr-rfc-plan-storage.md)) — deferred this design; RFC ≠ ADR principle
- implementation-plan §8.7 + Q5 (docs/analysis/implementation-plan.md (record no longer in repo)) — the lightweight `docs/rfcs/` sketch + single-user rationale
- Rust RFC process (git-as-history, pre-FCP sign-off) — <https://rust-lang.github.io/rfcs/>
- Python PEP 1 (Post-History + 2026 newest-first Change History, status enum) — <https://peps.python.org/pep-0001/>
- [docs/reference/frontmatter.md](../reference/frontmatter.md) — canonical schema home
