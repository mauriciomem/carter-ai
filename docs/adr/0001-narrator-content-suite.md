---
id: ADR-0001
status: accepted
created: 2026-06-06
decided: 2026-06-06
supersedes: []
superseded_by: null
tags: [narrator, skills, documentation]
---

# ADR-0001: Narrator as a first-class agent with a documentation & storytelling skill suite

> **Status note (2026-10-24):** `redaction.enabled` and the `config_warnings` guard no longer exist; the narrator's redaction rules are always rendered and `redaction.categories` selects them.

**Status:** Accepted
**Date:** 2026-06-06
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)

---

## Implementation Status (verified 2026-06-06)

**Shipped** in commit `5d4a194` (+ `0c7f3d8` for the "write for the reader"
principle). Audit confirms all four sub-decisions are live:

| Sub-decision | Status | Evidence |
|--------------|--------|----------|
| D1 — narrator first-class (6→7 agents) | **DONE** | `agents/carter-narrator.md` exists, redaction ON + 7 categories; `mode: subagent` (per ADR-0002) |
| D2 — `carter-docs` skill | **DONE** | Diátaxis + Keep a Changelog + git-aware doc-audit + delegation table present |
| D3 — `carter-story` skill | **DONE** | audience matrix, delegates redaction to narrator + decks to pptx/docx |
| D4 — Brief register | **DONE** | canonical in `carter-docs`; referenced (not duplicated) by `carter-atlassian` + `carter-ops` |

Ground truth: 22 skills, 7 agents, anti-drift contracts honored in the actual
skill files. Tests `TestNarratorAgent` + `TestContentSkills` guard it.

**Known limitation (edge case).** The static narrator bakes redaction ON, but the
*template* gates it on `{% if config.redaction.enabled %}`. A workspace that sets
`redaction.enabled = false` while keeping `narrator` in `config.agents` scaffolds
a narrator with **no redaction rules**, yet maestro still routes external content
to it. The parity test reads the template as raw text, so it does **not** catch
this. Not fixed (by-design config-gating per D1); recorded for a future guard
(e.g. warn when narrator is enabled but redaction is off, or render-time assertion).

---

## Context

Carter produces "narrative" output — content written for humans rather than
machines: PR descriptions, Jira comments, Slack drafts, READMEs, changelogs,
ADRs, API docs, contribution guides, and presentations. A review of the current
implementation revealed three structural problems.

### Current state (verified against source)

1. **The narrator is a second-class agent.** The system installer copies static
   agent files by globbing `agents/carter-*.md`
   ([carter/installer.py](../../carter/installer.py) `install_agents`, line ~459).
   The `agents/` directory contains **six** files — architect, devops, engineer,
   learner, maestro, pm. The **narrator has no static source**; it exists only as
   a Jinja template ([templates/agents/carter-narrator.md.j2](../../templates/agents/carter-narrator.md.j2)).
   Consequently:
   - `carter install` (system-level) installs **6 agents — never the narrator**.
   - `carter init` (workspace scaffold) renders **7 agents incl. narrator**, but
     only when `config.redaction.enabled` is true.
   - Every other agent has **both** a static `agents/carter-*.md` and a
     `templates/agents/*.j2`. The narrator is the lone exception — an orphan.

2. **Routing already references the narrator, but it is conditionally present.**
   The maestro template already routes external-facing work to it
   ([templates/agents/carter-maestro.md.j2](../../templates/agents/carter-maestro.md.j2),
   lines 37–38, guarded by `{% if "narrator" in config.agents %}`). So in a
   scaffold the narrator is wired in; at system level the routing target does not
   exist. (Note: an earlier analysis incorrectly claimed routing was missing —
   the gap is *availability at system level*, not routing.)

3. **Narrative style/voice is fragmented and partly missing.** There is no skill
   for authoring developer documentation. `carter-adr` exists and is good for
   ADRs. Review voice/registers were recently added to `carter-code-review`, and
   PR/Jira body guidance lives in `carter-ops`. There is no consolidated home for
   "how Carter writes docs" or "how Carter writes public narrative," and no
   doc-audit capability to detect stale/missing documentation.

### Problem statement

- The narrator should be a **first-class, always-installed** agent like the other
  six, not a redaction-gated scaffold-only template.
- Carter needs **dedicated skills** for two genuinely distinct narrative needs —
  developer/technical documentation, and warm public-facing storytelling — without
  duplicating capabilities that already exist (`carter-adr`, `carter-atlassian`,
  `carter-code-review`, `pptx`/`docx`/`pdf`, `carter-diagram`).
- A third need (terse, precise responses for tickets/PRs/issues) must be served
  **without** creating a fourth competing definition of PR/ticket voice.

---

## Decision

We will make four coordinated changes. They are interdependent and recorded as a
single ADR because they share one boundary surface (external-facing content).

### D1 — Narrator becomes a first-class, always-installed agent

Add a static `agents/carter-narrator.md` so the installer's existing glob picks it
up. System installs go from **6 → 7 agents**. Because a system install has no
`carter.yaml`, the static file **bakes in redaction = ON with all seven
categories** (secrets, internal_urls, security_incidents, pii, financials,
employee_data, infra_ids). The workspace template
([carter-narrator.md.j2](../../templates/agents/carter-narrator.md.j2)) remains
config-driven and may still disable categories per workspace. The two sources
must be kept in sync, exactly as the other six agents already are.

### D2 — New skill `carter-docs` (developer/technical documentation)

Authors and maintains repository documentation: READMEs, changelogs, API docs,
contribution guides, and a **doc-audit mode**. Structured on the **Diátaxis**
framework (tutorials / how-to / reference / explanation). Changelogs follow
**Keep a Changelog** + Conventional Commits (already referenced by
`carter-pipeline`). Doc-audit is **git-aware**, reusing the Scope Gate pattern
already in `carter-code-review` (scope to the diff/tracked files, not the whole
tree).

### D3 — New skill `carter-story` (the Storyteller)

Warm, precise, audience-aware **public-facing narrative**. Distinct output shape
from `carter-docs` (narrative arc & prose vs. structured reference; external vs.
internal). This is the skill the narrator invokes for public narrative; redaction
is always applied by the narrator agent gate, never inside the skill.

### D4 — The third need is a *register*, not a skill

"Laser-focused, concise, context-aware responses for tickets/PRs/issues" is
expressed as a **Brief register** (mirroring the review registers), reused by
`carter-docs`, `carter-atlassian`, and `carter-ops`. No standalone skill is
created, to avoid a fourth definition of PR/ticket voice.

---

## Options Considered

### Axis A — Narrator availability

**Option A1 — Keep narrator scaffold-only (status quo).**
- Pros: no count churn; redaction stays opt-in.
- Cons: narrator absent on system installs; routing target can dangle; the agent
  is uniquely orphaned (template-only); inconsistent with the other six.

**Option A2 — Narrator first-class, always installed (CHOSEN).**
- Pros: completes the existing dual-source pattern; routing target always exists;
  redaction-on-by-default is the safe system-level posture.
- Cons: 6→7 count churn touching tests + docs; adds a dual-source sync burden.

**Option A3 — Make the installer render the narrator template at install time.**
- Pros: single source (template only).
- Cons: introduces Jinja rendering into the system installer (currently a plain
  file-copy glob); needs a synthetic default config; larger blast radius than a
  static file. Rejected as over-engineering.

### Axis B — Skill granularity for narrative

**Option B1 — One skill per surface (PR / Jira / docs / deck).**
- Pros: superficially tidy.
- Cons: 4 files to sync; conflates *surface* (formatting) with *audience* (tone);
  re-creates the overlap we are actively consolidating. Rejected.

**Option B2 — Two skills (docs, story) + a register for terse responses (CHOSEN).**
- Pros: matches the two genuinely distinct output shapes; reuses the proven
  register pattern; delegates to existing skills rather than duplicating.
- Cons: +2 skills (20→22) with attendant count churn.

**Option B3 — One mega "narrate" skill with a surface×audience matrix.**
- Pros: single file.
- Cons: docs vs. public storytelling are different enough (structure vs. prose,
  internal vs. external) that one file becomes a kitchen sink. Rejected in favor
  of two focused skills.

### Axis C — Third need (terse ticket/PR responses)

**Option C1 — Dedicated skill.** Rejected: a 4th place defining PR/ticket voice,
fragmenting `carter-code-review` + `carter-atlassian` + `carter-ops`.

**Option C2 — Brief register reused across skills (CHOSEN).** Consistent with the
review-register pattern; one definition, many call sites.

### Axis D — Documentation framework for `carter-docs`

**Option D1 — Ad-hoc structure.** Rejected: no shared mental model; drift-prone.

**Option D2 — Diátaxis (CHOSEN).** Authoritative, widely adopted (Cloudflare,
Gatsby, Vonage), light-weight, and directly prevents mixing reference with
tutorial. Source: <https://diataxis.fr/>.

### Axis E — ADR granularity (record structure)

**Option E1 — One ADR covering D1–D4 (CHOSEN).**
- Pros: the four decisions share one boundary surface (external-facing content)
  and one rationale; they read as a single architectural decision. The Anti-Drift
  Contracts table — the keystone artifact — lives in exactly one place. They ship
  together as one plan/review/commit, with no web of cross-references.
- Cons: coarser supersession (reversing one sub-decision leaves the ADR partially
  stale, annotated internally rather than cleanly replaced); mixes grains (D1
  agent topology is heavier than D4 a style register); a focused search lands on a
  larger document.

**Option E2 — Split into 3–4 ADRs (0001 narrator, 0002 docs, 0003 story, 0004 register).**
- Pros: granular supersession and searchability; small, individually linkable
  records; purist one-decision-per-ADR discipline.
- Cons: the Anti-Drift table must be **duplicated across ADRs (the very drift this
  ADR exists to prevent) or orphaned into a 5th umbrella ADR** that recreates the
  single document anyway; the four are genuinely interdependent (docs/story are
  invoked by the now-first-class narrator; the brief register is shared by both);
  more overhead now for an independent-supersession benefit that may never be
  exercised.

**Decisive factor:** splitting forces the Anti-Drift Contracts to be duplicated or
orphaned — self-contradictory for an anti-drift ADR. The explicit D1–D4 labels
preserve most of the granular-supersession benefit: a future ADR can supersede a
sub-decision by reference (e.g., "ADR-0007 supersedes ADR-0001 §D3").

---

## Rationale

- **Consistency over special-casing.** Making the narrator first-class removes an
  orphan and completes a pattern the codebase already enforces for six agents.
- **Capability where the agent is not.** Skills install globally on every
  install; the narrator agent does not (pre-D1). Putting *style* in skills makes
  it reusable by `carter-ops`/`carter-pm` even absent the narrator, while
  *redaction* stays at the agent gate where it cannot be bypassed by invoking a
  skill directly.
- **Reuse the patterns we just validated.** Registers (Brief/Standard/Deep) and
  the Scope Gate are recent, tested additions; D2–D4 extend them rather than
  inventing parallel mechanisms.
- **Delegation prevents drift.** `carter-docs` delegates ADRs to `carter-adr`,
  diagrams to `carter-diagram`, and decks/binary docs to `pptx`/`docx`/`pdf`.
  This is the central anti-drift contract (see below).

---

## Anti-Drift Contracts (normative — implementation MUST honor)

These boundaries exist specifically to prevent duplication. They are testable.

| Skill/Agent | MUST do | MUST NOT do (delegate instead) |
|-------------|---------|-------------------------------|
| `carter-docs` | README, changelog, API docs, contribution guides, doc-audit | Author ADRs → **`carter-adr`**; draw diagrams → **`carter-diagram`**; explain in chat → **`carter-explain`**; summarize *external* docs → **`carter-research`**; produce decks/binary docs → **`pptx`/`docx`/`pdf`** |
| `carter-story` | Public-facing narrative prose, audience tone | Apply redaction itself (the **narrator agent** owns redaction); build slides → **`pptx`** |
| `carter-narrator` (agent) | Redaction gate + audience routing; invoke `carter-docs`/`carter-story`/`carter-atlassian` | Re-derive technical substance (engineer/architect/pm own that) |
| Brief register | Single definition of terse ticket/PR/issue voice | Be copied into multiple skills — it is referenced, not duplicated |

Redaction is **never** placed inside a style skill; invoking a skill directly must
not bypass the gate.

---

## Consequences

### Positive
- Narrator is consistent with all other agents and always available.
- Redaction-on-by-default at system level (safer posture).
- Two focused, reusable narrative skills grounded in authoritative practice.
- Terse-response need met without voice fragmentation.

### Negative / Costs
- **Dual-source sync burden** for the narrator (static + template), like the
  other six agents.
- **Count churn** (third time this session these numbers move): system agents
  **6 → 7**, skills **20 → 22**.
- Re-touches docs refreshed earlier: [docs/testing.md](../testing.md),
  [docs/getting-started.md](../getting-started.md), [README.md](../../README.md),
  [docs/carter-ops.md](../carter-ops.md), [docs/memory-and-knowledge.md](../memory-and-knowledge.md).

### Risks & mitigations
- **Risk:** static vs. template narrator drift. **Mitigation:** a test asserting
  the static file contains the redaction block with all 7 categories.
- **Risk:** `carter-docs` reabsorbs ADR/diagram scope over time. **Mitigation:**
  the Anti-Drift table above + a skills eval asserting delegation language is
  present.
- **Risk:** count assertions missed. **Mitigation:** enumerate the exact tests in
  the implementation plan (below).

---

## Test & Documentation Impact (enumerated to prevent misses)

**Tests to update:**
- `tests/test_install.py` → `TestInstallAgents` (asserts 6 → **7**),
  `TestOpsOneLiner` (iterates 6 agents → **7**), skill-count assertions in
  `TestInstallSkills` (20 → **22**).
- `tests/test_scaffold.py` → `TestNarrator` (confirm still rendered; no regression).
- New: a narrator static-source redaction test; new `carter-docs`/`carter-story`
  skill-presence + delegation evals in `evals/`.

**Docs to update:** testing.md (counts + new skills), getting-started.md (agent
count narrative), README.md (agent/skill counts, narrator no longer "scaffold
utility"), carter-ops.md (narrator first-class), memory-and-knowledge.md if it
references counts.

---

## Implementation Plan (sequenced; execute only after approval)

1. **D1 — narrator static source.** Create `agents/carter-narrator.md` (redaction
   ON, 7 categories, baked from the template's rendered form). Verify the
   installer glob picks it up.
2. **D2 — `carter-docs` skill.** `skills/carter-docs/SKILL.md` — Diátaxis structure,
   changelog (Keep a Changelog + Conventional Commits), git-aware doc-audit,
   delegation per Anti-Drift table. Add to OpenCode skill mirror if applicable.
3. **D3 — `carter-story` skill.** `skills/carter-story/SKILL.md` — audience matrix,
   warmth + precision, delegates decks to `pptx`/`docx`.
4. **D4 — Brief register.** Add to `carter-docs` (canonical) and reference it from
   `carter-atlassian` and `carter-ops`.
5. **Wire-up.** Add `## Available Skills` to the narrator template + new static
   file (carter-docs, carter-story, carter-atlassian); keep maestro routing.
6. **Counts + docs + tests.** Apply all enumerated test/doc updates.
7. **Verify.** Run `tests/` + `evals/`; confirm 6→7 / 20→22; eyeball a docs sample
   and a story sample; run a doc-audit dry pass.

---

## Decisions Resolved (review 2026-06-06)

1. **Skill names:** `carter-docs` and `carter-story`. **Confirmed.**
2. **Single ADR vs. split:** one ADR with labeled sub-decisions D1–D4 (see Axis E
   for full pros/cons). **Confirmed — single ADR.**
3. **Brief register home:** canonical definition in `carter-docs`, referenced by
   `carter-atlassian` and `carter-ops`. **Confirmed.**
4. **Changelog convention:** Keep a Changelog + Conventional Commits. **Confirmed.**
5. **Scope:** no new redaction categories; maestro routing unchanged beyond
   ensuring the narrator is always present. **Confirmed.**

---

## References

- Diátaxis documentation framework — <https://diataxis.fr/>
- Keep a Changelog — <https://keepachangelog.com/>
- Conventional Comments — <https://conventionalcomments.org/>
- Google Engineering Practices, "How to write code review comments" —
  <https://google.github.io/eng-practices/review/reviewer/comments.html>
- Michael Nygard, "Documenting Architecture Decisions" —
  <https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>
- Prior session work: review registers + Scope Gate in
  [skills/carter-code-review/SKILL.md](../../skills/carter-code-review/SKILL.md)
