---
step: 5
status: done
depends_on: [4]
files_modified: [pyproject.toml, .github/workflows/release.yml]
---

## Step 5: PSR config + release.yml (tag + CHANGELOG + Release)

### Tasks
1. **SPIKE FIRST** — verify the CURRENT (2026) python-semantic-release config for a
   tag-driven / no-version-file project against its docs. Confirm how PSR sources
   "current version" from tags when no `version_variables`/`version_toml` is set,
   and the exact v9/v10 GitHub Action input names. Do NOT wire blind.
2. Add `[tool.semantic_release]` to pyproject.toml: `tag_format = "v{version}"`,
   `commit_parser = "conventional"`, `build_command = "uv build"`, target branch
   `main`, changelog enabled, NO version-file writes (tag-driven per ADR-0009 D1).
3. Add .github/workflows/release.yml (SHA-pinned actions): trigger
   `push: branches: [main]`, `permissions: contents: write`, a `concurrency` guard.
   Steps: checkout with `fetch-depth: 0` (full history + tags) → run the PSR action,
   which computes the bump, tags `vX.Y.Z`, writes CHANGELOG, and creates the GitHub
   Release. Ensure non-releasing commits (docs/chore) no-op cleanly.
4. Keep the workflow on a throwaway branch and use PSR `--noop`/dry-run until a dry
   run prints the correct next version. Only then merge to main.

### Done criteria
- `release.yml` present, SHA-pinned, least-privilege (`contents: write` only).
- A PSR dry-run computes the expected next version from commit history.
- pyproject `[tool.semantic_release]` matches the verified 2026 config.

### Notes
remote_ops: tag + release are REMOTE WRITES under `push_policy: manual` — do NOT
push tags/releases without explicit user approval. Dry-run locally first. The
release job needs `contents: write`; do not over-grant (`id-token: write` only if
PyPI is added later — out of scope here).
