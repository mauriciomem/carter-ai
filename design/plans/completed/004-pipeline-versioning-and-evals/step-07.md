---
step: 7
status: done
depends_on: []
files_modified: [.github/workflows/ci.yml]
---

## Step 7: install-smoke CI job (Linux + macOS)

### Tasks
1. Add an `install-smoke` job to ci.yml (SHA-pinned actions), matrix
   `os: [ubuntu-latest, macos-latest]`, `permissions: contents: read`.
2. Steps: checkout → setup-uv → `uv tool install .` (REAL install of the built CLI,
   not editable) → assert `carter --version` exits 0 and prints a PEP 440 version →
   `carter init "$RUNNER_TEMP/smoke-ws" --target all` → `carter check
   "$RUNNER_TEMP/smoke-ws"` (must pass) → `carter install --base-dir
   "$RUNNER_TEMP/fake-home" --target all` (exercise the genuine installer against a
   throwaway home) → assert expected agent/skill/instruction files exist under it.
3. Use `$RUNNER_TEMP` for all paths; the runner is ephemeral so no explicit cleanup.

### Done criteria
- `install-smoke` green on ubuntu-latest AND macos-latest.
- Exercises the genuine `uv tool install` + `carter init/check/install` path — not
  just the unit-level `base_dir` redirection already covered by tests/test_install.py.

### Notes
Catches cross-platform path regressions previously only logic-tested
(knowledge/decisions.md — Fedora 44 in-situ note). Must land BEFORE step 8 so the
installer refactor is protected by a real end-to-end check. Independent of M1-M3
(can be built in parallel), but its presence is a precondition for step 8.
