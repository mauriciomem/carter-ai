---
step: 1
status: done
depends_on: []
files_modified: [docs/adr/0009-release-versioning-and-pipeline.md]
---

## Step 1: ADR-0009 — release & versioning strategy

Author the decision record this plan executes, using the `carter-adr` skill
(frontmatter + human Status block, ≤400 lines). A change is a NEW ADR, never an
edit to an accepted one.

### Decisions to record
- **D1 Tag-driven version** — `hatch-vcs` derives the build/runtime version from
  the latest `vX.Y.Z` git tag. Kills the dual-source drift (`[project].version` +
  `carter/__init__.py:__version__`, the latter currently dead code); git-install
  distribution resolves `@vX.Y.Z` cleanly. File-driven PSR (writing a version
  literal back to source) REJECTED — reintroduces a drift-prone string + a
  `chore(release)` commit per bump.
- **D2 SemVer automation** — python-semantic-release maps Conventional Commit
  types to bumps: `fix:`→PATCH, `feat:`→MINOR, `feat!:`/`BREAKING CHANGE:`→MAJOR;
  `docs/chore/refactor/test/ci/build/style` → no release. PSR owns tag + CHANGELOG
  + GitHub Release.
- **D3 Baseline** — manually tag `v2.0.0` at current `main` (graduating `2.0.0a1`);
  PSR computes every subsequent version from commits since the last tag.
- **D4 Quality gates** — ruff (lint+format) + mypy become required CI gates.
- **D5 Eval economics** — offline evals are the key-free PR gate; live/accuracy
  evals run on a weekly cron with a repo-secret low-cost model + token/cost metrics
  (Copilot OAuth is unavailable on CI runners).

### Done criteria
- `docs/adr/0009-release-versioning-and-pipeline.md` exists, `status: accepted`,
  `decided: 2026-06-15`, ≤400 lines, frontmatter per docs/reference/frontmatter.md.
- The plan README `adr: ADR-0009` back-reference is satisfied.
- `carter check .` reports no NEW ADR/plan frontmatter errors.

### Notes
This is the only documentation-first step (TDD skip criteria apply — docs-only).
It front-loads the locked decisions so the implementer never re-litigates them.
