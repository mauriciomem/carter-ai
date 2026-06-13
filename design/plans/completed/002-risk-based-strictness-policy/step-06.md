---
step: 6
status: done
depends_on: []
files_modified: [carter/installer.py, tests/test_install.py]
---

## Step 6 — Fold D5: de-dup the hardcoded server triple (P2)

Carried non-blocking task **D5**. The `["github","terraform","atlassian"]` triple
is hardcoded twice — `carter/installer.py:786` (install) and `:948` (uninstall).

### Tasks
- Extract the server triple to a single module-level constant (or reuse the
  existing manifest source) and reference it from both sites.
- No behavior change — pure de-duplication; the emitted MCP wiring stays identical.

### Done when (TDD red → green)
- A test asserts install and uninstall reference the **same** server list (no
  divergence) and the emitted set is unchanged.
- `python -m pytest tests/ -q -p no:cacheprovider` green.

### Note
Independent refactor (`depends_on: []`) — sits in P2 by milestone but does not
block, and is not blocked by, the emission steps.
