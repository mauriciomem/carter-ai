# ADR-0003 — Implementation plan

> Companion to [ADR-0003: Knowledge, ADRs, RFCs & plans](0003-knowledge-adr-rfc-plan-storage.md).
> The ADR records the **decision**; this file holds the **execution checklist**.
> Extracted to keep the ADR under its own 400-line budget (D4 rule 3).

**Status:** Accepted — execute in phase order. Each phase is independently
shippable; commit per phase with the quality gate.

---

## Phase 1 — Metadata standard & ADR frontmatter (docs/skills/config; low risk)

1. **Frontmatter schema reference.** Define the D6 schemas in one canonical place
   — `docs/reference/frontmatter.md` — that the `carter-adr` / `carter-plan`
   skills link to (one source, per the anti-drift discipline).
2. **`plans:` config block.** Add to `DEFAULT_CONFIG` in
   [config.py](../../carter/config.py): `step_file_threshold: 3`,
   `readme_max_lines: 150`, `step_max_lines: 80`, `git_regime: private`.
3. **`carter-adr` skill.** YAML frontmatter + keep the human status block; add the
   400-line guardrail (skill constant) + supersede-by-`§Dn` guidance.
4. **Backfill** frontmatter into ADR-0001/0002/0003 (small, consistency).

## Phase 2 — Plans become real + validator (the core fix)

5. **Rewrite `carter-plan` skill** to write `.carter/state/plans/active/<id>/`
   (tiered: README, or README+steps per D2), with mandatory `must_haves` (O6).
6. **Python validator (O3).** A `carter`-side check that parses plan frontmatter
   against D6 and rejects an `active` plan with missing keys or empty
   `must_haves`; reads thresholds from the `plans:` config block. Deterministic.
7. **Update `carter-pm` template.** It already claims the location — align wording
   to the tiered structure + frontmatter + the validator gate.

## Phase 3 — Session recovery, checkpoint & ongoing history

8. **Implement `checkpoint.md` (D7.2/O4).** Maestro writes it suggest-and-confirm
   as a **thin cursor** (`updated`, `active_plan`, `next_step`, one-line summary)
   that points into plan frontmatter — never duplicating plan content.
9. **Ongoing auto-commit (D5 recovery fix).** Commit the nested `.carter/.git` at
   plan/checkpoint/session write boundaries so deletions are recoverable. Honor
   `workspace.mode` + `plans.git_regime` for where plans land.
10. **Tighten `session_bootstrap`** to parse plan/checkpoint frontmatter
    deterministically.

## Phase 4 — Knowledge metadata (optional, lightest)

11. Add optional `scope`/`tags` convention to knowledge entries; document it. No
    structural change to the 5 files.

## Phase 5 — Tests & docs

12. **Tests:** plan-file rendering + frontmatter presence (mirror yui-soul's
    `scaffold.test.js`), the validator (accept/reject cases), ADR frontmatter, and
    an auto-commit/recovery test (delete → restore from `.carter/.git`).
13. **Docs:** getting-started (`.carter/state/` tree), memory-and-knowledge, and a
    short "plans & decisions" reference page.

---

## Out of scope (deferred to their own assessments)

- **Detailed RFC design** → prospective **ADR-0004** (D3).
- **Off-machine backup / durability** (private-remote push vs. global mirror vs.
  catalog) → prospective **ADR-0005**.
