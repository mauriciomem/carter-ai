---
step: 10
status: done
depends_on: [9]
files_modified: [.github/workflows/evals-live.yml, .github/workflows/ci.yml, docs/testing.md]
---

## Step 10: Pipeline eval strategy — offline gate + live cron + docs

### Tasks
1. **Confirm the PR gate** in ci.yml runs the key-free offline evals
   (`evals/test_skills.py evals/test_routing.py`) as a REQUIRED check (already
   present — keep/formalize). This is the minimal structural-accuracy + functionality
   gate; no secret needed.
2. Add `.github/workflows/evals-live.yml` (SHA-pinned): `on: schedule` (weekly cron)
   + `workflow_dispatch`; `permissions: contents: read`. Steps: checkout → setup-uv →
   install `.[dev]` + httpx → run `pytest evals/test_live.py` with `ANTHROPIC_API_KEY`
   / `OPENAI_API_KEY` from `secrets` and a LOW-COST model via `EVAL_MODEL` +
   `EVAL_JUDGE_MODEL` (e.g. a gpt-4o-mini / Haiku-class model) → upload the metrics
   summary (from step 9) as a build artifact. Add a hard cost cap (scenario count
   and/or `max_tokens`).
3. **Answer "should we use an LLM key?" in docs/testing.md:** local runs reuse
   Copilot OAuth (no key); CI runners CANNOT (no Copilot token — `gh auth token`
   there yields only `GITHUB_TOKEN`, no Copilot API access; no `opencode/auth.json`),
   so the live canary REQUIRES a dedicated repo-secret key. Offline stays key-free.
4. Update docs/testing.md with the two-tier table: PR gate (free/deterministic) vs
   weekly canary (budgeted/live) + how to read the metrics artifact.

### Done criteria
- `evals-live.yml` runs on cron + manual dispatch, key from `secrets`,
  budget-capped, uploads a metrics artifact.
- ci.yml PR gate stays key-free (unit + offline evals + lint + install-smoke).
- docs/testing.md documents the strategy and the API-key decision.

### Notes
Live evals test the PROMPT markdown sent to a RAW model — a good proxy for prompt
quality, NOT the real VS Code Copilot tool-calling loop. State this explicitly so
metrics aren't over-read. NEVER commit a key; secrets only. Closes M6.
