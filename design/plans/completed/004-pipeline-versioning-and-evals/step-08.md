---
step: 8
status: done
depends_on: [2, 3, 7]
files_modified: [carter/install/__init__.py, carter/install/console.py, carter/install/paths.py, carter/install/jsonc.py, carter/install/vscode.py, carter/install/mcp.py, carter/install/core.py, carter/installer.py, carter/cli.py]
---

## Step 8: Modularize installer.py → carter/install/ package

### Tasks (behaviour-preserving refactor)
1. Create a `carter/install/` package, splitting the 1171-LOC monolith along its
   existing internal seams (mirror the clean carter/ops/ layout):
   - `console.py` — ANSI color + `log_*` helpers (installer.py:35-93).
   - `paths.py` — `_home`/`_copilot_base`/`_opencode_base`/`_vscode_user_dirs`/
     `_vscode_settings_path`/`_vscode_detected` (installer.py:104-178).
   - `jsonc.py` — `_strip_jsonc`/`_load_jsonc` (installer.py:180-260).
   - `vscode.py` — VS Code detection + settings merge.
   - `mcp.py` — MCP server config/merge (the de-duped server triple from plan-002 D5).
   - `core.py` — `run`/`main` orchestration + install/uninstall.
2. Preserve the public API: `carter.installer.main` / `.run` MUST still import
   (re-export from the package, or keep `installer.py` as a thin shim like the
   root `install.py`). Update `carter/cli.py` (`from carter.installer import run`)
   only if the path changes.
3. Keep each module ≤ ~400 LOC. NO behaviour change — pure move + re-wire; delete
   dead code as you move it (no orphaned helpers "just in case").
4. Run the FULL suite (especially tests/test_install.py, 75) UNCHANGED — it is the
   safety net. ruff + mypy + install-smoke must stay green.

### Done criteria
- `carter/install/` package exists; no module > ~400 LOC.
- All existing installer tests pass UNCHANGED (no edits beyond import paths).
- `carter.installer.main` still resolves (install.sh / install.py / `carter install`
  all work).
- ruff, mypy, unit suite, and install-smoke all green.

### Notes
Highest-blast-radius step → intentionally LAST among code steps, gated by 2,3,7.
This is a refactor (no observable behaviour change) — the 75 install tests + the
step-7 smoke are the regression proof; no new TDD red phase required.
