---
step: 6
status: done
depends_on: [5]
files_modified: [docs/getting-started.md, docs/testing.md, CHANGELOG.md]
---

## Step 6: Baseline tag v2.0.0 + first automated release + docs

### Tasks
1. **Baseline (manual, one-time, USER-APPROVED):** create an annotated tag `v2.0.0`
   at the chosen `main` commit, graduating `2.0.0a1`. This is PSR's starting point
   and the first version hatch-vcs resolves.
2. Verify `uv build` now reports `2.0.0` (hatch-vcs reads the tag) and that
   `carter --version` agrees.
3. Make a trivial Conventional Commit (e.g. a `fix:`), let release.yml run, and
   confirm it tags `v2.0.1`, generates/updates CHANGELOG.md, and opens a GitHub
   Release with auto-generated notes.
4. Document the release flow (new "Releasing" section in docs): commit-type → bump
   table (fix/feat/breaking), how to read the version, and how
   `uv tool install git+https://github.com/...@vX.Y.Z` pins an exact release.

### Done criteria
- Tag `v0.1.0` baseline exists; `uv build` + `carter --version` both report the tag version (`0.1.0`, then `0.1.1` after the first automated release). [v2.0.0 baseline amended to v0.1.0 — pre-1.0.]
- One end-to-end automated release produced a tag + CHANGELOG + GitHub Release.
- Docs explain the SemVer/release flow for contributors.

### Notes
ALL tag/release pushes here are remote writes → batch for explicit user approval
(`push_policy: manual`). The baseline tag is effectively irreversible once others
pull — confirm the target commit before tagging. Closes M3.
