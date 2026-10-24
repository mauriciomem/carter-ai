---
name: carter-rfc
description: Propose and review a design before building it — a lightweight RFC with multi-expert reviews
argument-hint: "[design proposal title or topic]"
---

<objective>
Create and shepherd a **Request for Comments (RFC)** — a design proposal that
explores *"should we do X?"* before a plan or code exists. An accepted RFC yields
an ADR (the durable decision) and then a plan (execution). This skill implements
ADR-0004; the canonical frontmatter schema lives in
[docs/reference/frontmatter.md](../../docs/reference/frontmatter.md).

**Language:** write in the workspace `docs_language` (`.carter/carter.yaml`); if it is absent, English unless the user chose another language.
</objective>

<when-to-rfc>
Write an RFC when a change affects **> 3 files**, introduces a **new agent or
skill**, or alters Carter's **architecture**. Otherwise skip straight to a plan.
RFC explores; ADR records; plan executes — keep the phases distinct.
</when-to-rfc>

<directory-layout>
Each RFC is a **directory** under `docs/rfcs/` (main repo). The directory holds the
proposal plus one review file per reviewing agent — so multiple experts can
contrast the idea. The directory **never moves**; status lives in frontmatter
(no status folders).

```
docs/rfcs/
├── 0001-rfc-system/
│   ├── README.md            ← the proposal (frontmatter + sections)
│   ├── review-architect.md  ← one file per reviewing agent
│   └── review-engineer.md
└── README.md                ← index table (by frontmatter status)
```

Naming: `NNNN-kebab-name/` (zero-padded four digits, mirroring ADRs); the `id`
frontmatter is `RFC-NNNN` and matches the directory number.
</directory-layout>

<proposal-template>

## RFC `README.md`

```markdown
---
id: RFC-0001
status: draft                 # draft | review | accepted | rejected | withdrawn
revision: 1                   # bump only on a MATERIAL change to the proposal
created: YYYY-MM-DD
decided: null                 # date when accepted/rejected/withdrawn
author: <who>
adr: null                     # ADR-NNNN produced by this RFC, when accepted
plan: null                    # NNN-slug plan that executes it, when created
supersedes: []                # RFC ids this replaces
tags: []
---

# RFC-0001: Title

**Status:** Draft | Review | Accepted | Rejected | Withdrawn
**Revision:** 1
**Author:** <who>

## Summary
One paragraph: what this proposes.

## Problem
What is wrong or missing, and why it matters.

## Proposal
What to build or change.

## Alternatives considered
| Option | Pros | Cons |
|--------|------|------|

## Trade-offs / Impact
What this costs; what it touches.

## Open questions
Unresolved points for reviewers.

## Decision
[Filled when accepted/rejected — rationale + link to the resulting ADR.]
```

</proposal-template>

<review-template>

## `review-{agent}.md` (one per reviewing agent)

Re-reviews are **appended newest-first** as `## Round N` sections; never rewrite a
prior round. Every round states **which revision it reviewed** — that marker is
how staleness is computed.

```markdown
# Review: RFC-0001 — <agent>

## Round 2 — YYYY-MM-DD — reviewed revision 2 — verdict: approve
<what changed since round 1; remaining concerns>

## Round 1 — YYYY-MM-DD — reviewed revision 1 — verdict: request-changes
<blocking issues, suggestions, notes>
```

Verdicts: `approve | request-changes | reject`.
</review-template>

<lifecycle>
```
draft → review → accepted   (→ yields an ADR, then a plan)
              └→ rejected
draft|review → withdrawn     (author drops it)
```

- Status changes are **frontmatter edits**, not directory moves.
- **Revisions & rounds.** Bump `revision: N` only on a *material* change to the
  proposal. Reviewers append a new `## Round N — reviewed revision M` section.
- **Staleness is derived:** a review is *current* iff its latest round's
  `reviewed revision` equals the RFC's `revision`. A missing/unparseable marker is
  treated as **stale** (needs re-review) — never current.
- **Git is the authoritative history**; `revision` + rounds are a human cursor over it.
</lifecycle>

<reviewer-model>
Any relevant Carter subagent reviews from its expertise — multi-perspective
contrast is the point — but **domain-triggered, not all-agents-always**:

- **carter-architect** reviews **every** RFC (design coherence, alternatives) — the owner.
- **carter-engineer** — code/test feasibility + security pass (auth, secrets, trust boundaries).
- **carter-devops** — CI/CD, deployment, infra. **carter-pm** — scope, sequencing.
- **carter-narrator** — external-facing / redaction impact.
- carter-maestro (orchestrates) and carter-learner (explains) do **not** review.

Reviews are **advisory, never voting.** The **maestro synthesizes** the latest
round of each reviewer into one recommendation — flagging any stale-vs-`revision`
or missing reviews — *before* the decision is presented. The **user decides.**
</reviewer-model>

<guidelines>
- **Fetch the current date before writing the RFC.** The frontmatter `created:`/
  `decided:` fields must use the real current date — obtain it from a native
  harness date variable where the target exposes one, otherwise run `date`. Do this
  **before writing any dated frontmatter**; never guess from your training cutoff.
- One RFC = one coherent proposal. Keep it focused; split a sprawling proposal.
- **Size budget: an RFC `README.md` > 400 lines MUST be split or tightened** (skill
  constant, mirroring the ADR budget — RFCs live in the main repo, outside `.carter/`).
- **Terminal statuses are frozen.** Once `accepted`, `rejected`, or `withdrawn`, the
  proposal is immutable — supersede with a new RFC (`supersedes: RFC-NNNN`), never edit.
- An **accepted RFC yields an ADR** (the durable decision) before a plan executes it;
  set `adr:` then `plan:` as those are created. `carter-adr` owns the ADR; `carter-plan`
  owns the plan — no overlap.
- Update `docs/rfcs/README.md` (the index) on every status change.
- Enforce the review-revision discipline by **template** (the `reviewed revision M`
  slot is required), **fail-safe default** (missing → stale), and the **maestro
  synthesis gate** — no Python validation (RFCs are skill-governed, like ADRs).
- Reference: Rust RFC process (<https://rust-lang.github.io/rfcs/>) and Python PEP 1
  (<https://peps.python.org/pep-0001/>) — git-as-history, newest-first change log.
</guidelines>
