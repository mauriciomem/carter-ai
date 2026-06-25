---
step: 3
status: done
depends_on: [2]
files_modified: [pyproject.toml, .github/workflows/ci.yml]
---

## Step 3: mypy config + type fixes + CI mypy gate

### Tasks
1. Add `[tool.mypy]` to pyproject.toml: `python_version = "3.11"`,
   `packages = ["carter"]`, `warn_unused_ignores = true`,
   `warn_redundant_casts = true`, `no_implicit_optional = true`,
   `disallow_untyped_defs = true`. Start NON-strict globally; add per-module
   `[[tool.mypy.overrides]]` with `strict = true` for already-clean small modules
   first (e.g. `carter.resources`, `carter.ops.attribution`).
2. Add `mypy>=1.11` and `types-PyYAML` to dev extras.
3. Run `mypy carter/`. Fix errors by ADDING annotations / `TypedDict`s — NOT by
   loosening. Likely hotspots: untyped dict returns (e.g. `installed: dict[str, dict]`
   in cli.py `check`), Click callbacks, the JSONC loader in installer.py.
4. Introduce `TypedDict`s for the config and the per-agent frontmatter shapes where
   it removes the most `Any`.
5. Extend the CI `lint` job (from step 2) with `mypy carter/`.

### Done criteria
- `mypy carter/` exits 0 at the configured level; any module still non-strict is
  recorded in ADR-0009 / this step as a tracked ratchet (not a blocker).
- CI `lint` job runs mypy and is green.
- Test suite unchanged and green; no runtime behaviour changed.

### Notes
Code already uses `from __future__ import annotations` + PEP 604 unions, so friction
is low. Full `--strict` everywhere is a follow-up ratchet, NOT required to close M1.
Type-only changes = TDD skip criteria; existing suite guards behaviour.
