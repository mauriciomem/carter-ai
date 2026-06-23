---
step: 2
status: done
depends_on: []
files_modified: [pyproject.toml, .github/workflows/ci.yml]
---

## Step 2: ruff config + autofix + CI ruff gate

### Tasks
1. Add `[tool.ruff]` to pyproject.toml: `target-version = "py311"`,
   `line-length = 100`, `src = ["carter", "tests", "evals"]`. Under
   `[tool.ruff.lint]` enable `select = ["E","F","W","I","UP","B","SIM","C4"]`
   (pyflakes/pycodestyle/isort/pyupgrade/bugbear/simplify/comprehensions). Set
   `[tool.ruff.lint.isort] known-first-party = ["carter"]`.
2. Add `ruff>=0.6` to `[project.optional-dependencies].dev`.
3. Run `ruff check --fix` then `ruff format`. Review the diff — autofixes only, NO
   behaviour change. Manually resolve residual lint (unused imports, import order,
   f-strings, `dict()`→`{}`).
4. Verify the full suite stays green (repo test cmd in README Notes).
5. Add a `lint` job to .github/workflows/ci.yml (SHA-pinned actions): checkout →
   setup-uv → `uv pip install -e ".[dev]"` → `ruff check .` + `ruff format --check .`.
   Run it in parallel with the existing `test` job.

### Done criteria
- `ruff check .` and `ruff format --check .` exit 0 locally.
- CI `lint` job present, actions SHA-pinned, green on py3.11 + py3.13.
- 467 unit + 28 offline evals unchanged and green.
- No `# noqa` added except with an inline justification comment.

### Notes
ruff is autofix-heavy and low-risk; do it BEFORE mypy so import-order/format churn
settles first (step 3 `depends_on: [2]`). Pure formatting/lint = TDD skip criteria
(no behaviour change); the existing suite is the regression net.
