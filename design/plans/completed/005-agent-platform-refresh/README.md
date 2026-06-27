---
id: 005-agent-platform-refresh
status: completed
created: 2026-06-26
updated: 2026-06-27
adr: ADR-0010
rfc: RFC-0005
push_policy: manual
tags: [agents, orchestration, dispatch, models, strictness, taxonomy, narrator, time, copilot, vscode, opencode]
repos: [carter-ai]
must_haves:
  truths:
    - "maestro emits the real dispatch primitive per target: VS Code/Copilot `tools: ['agent']` + an EXPLICIT `agents: [...]` list + `handoffs:`; OpenCode `permission.task` with EXPLICIT per-specialist allow entries — never `'*'` or a `carter-*` glob; specialists carry `agents: []` (flat chain); `runSubagent` exists nowhere"
    - "`carter check` FAILS (exits non-zero) if the primary's emitted `agents:`/`permission.task` is `'*'`, a glob, or absent (fail-closed dispatch lint); and the maestro Copilot-CLI prose injects active-plan + knowledge context into every `/fleet` prompt"
    - "`POLICY_LEVELS == ('guarded', 'strict')`, default `guarded` everywhere; ZERO references to `loose` remain in shipped code/docs/tests (live surfaces; archived design/plans/completed/002-* left intact); no `loose` migration notice or coercion branch exists"
    - "the risk taxonomy is the 4 categories read/local-write/remote-write/dangerous (secret-access merged into remote-write); the per-agent allowlist matches the ADR-0010 D4 table (devops sole holder of remote-write+dangerous; pm/narrator/engineer = read+local-write; maestro/architect/learner = read)"
    - "substantive outward content routes through the narrator as a `gate`-tier handoff encoded in the allowlist (one-liners = ask+inline check); narrator carries no R6-only special case; `redaction.enabled` + the force-the-pass-at-guarded/strict fix are retained, decoupled from R6"
    - "no agent emits `temperature` (and its parity assertion is removed); each agent emits a single per-target `model:` string resolved `overrides > tier > default` from a `models:` block; `carter check` prints the required unverifiable-model advisory; Carter emits no effort key"
    - "the carter-plan/carter-rfc/carter-adr skills carry a required date-fetch checklist item and a dated artifact is written with a fetched (not guessed) date; no template bakes a literal `Today is <date>`"
    - "the `evals/` implementer-adherence scenario exists and the cheap (Sonnet 4.6) tier ships as default ONLY after it clears >=90% of must_haves with 0 critical-step failures; the eval runs nightly/manual against the live API with a recorded CI fixture, never per-PR live"
  artifacts:
    - "red-then-green tests for: native dispatch emission (agent/agents/handoffs/permission.task) + the fail-closed dispatch lint; 2-level x 4-category gate map + per-agent allowlist; per-target `model:` emission + the Carter->target model-name table (sync marker + non-empty-per-role test) + the carter check model advisory; `runSubagent`-absent body-parity; `temperature`-absent parity"
    - "updated carter/config.py, carter/scaffold.py, templates/agents/*.j2, statics agents/*.md, mcp/* as needed; the new `models:` block in DEFAULT_CONFIG + the model-name table with a MODEL LAUNCH sync marker"
    - "docs reconciled: README.md per RFC-0005 §6c claims-commitment, docs/strictness-policy.md, docs/getting-started.md, docs/reference/frontmatter.md (models block + 4-category allowlist + dispatch keys); instructions + carter-plan/rfc/adr skills carry the date-fetch step"
    - "evals/ implementer-adherence scenario + its recorded CI fixture; a nightly/manual runner that is NOT wired into per-PR CI"
  key_links:
    - "docs/adr/0010-agent-platform-refresh.md"
    - "docs/rfcs/0005-native-subagent-orchestration/README.md"
---

# Plan: Agent Platform Refresh (RFC-0005 / ADR-0010)

## Objective
Execute the nine decisions of ADR-0010: native subagent dispatch with a fail-closed allowlist,
per-agent model via a `models:` block, two strictness levels (`loose` purged), a 4-category taxonomy
with a first-class narrator and an enforced gate-tier redaction handoff, time-awareness by instruction,
a `temperature` drop, a staleness purge, and the implementer-adherence eval that gates the cheap tier.

## Milestones
| # | Milestone | Deliverables |
|---|-----------|--------------|
| M1 | Correctness floor (no behaviour change) | P0 staleness purge + time-awareness; clean review baseline |
| M2 | Strictness + taxonomy + narrator | P1 two levels (`loose` purged) → P2 4-category allowlist + enforced redaction |
| M3 | Native dispatch | P3 `agent`/`agents:`/`handoffs:`/`permission.task` + fail-closed lint + `/fleet` rule |
| M4 | Per-agent model, gated on the eval | P4 `models:` block + model-name table + advisory; P4-eval clears the pass-bar |

## Steps
| # | Step | Status | File |
|---|------|--------|------|
| 1 | P0 — staleness purge + time-awareness (no behaviour change) | done | [step-01.md](step-01.md) |
| 2 | P1 — two strictness levels; `loose` purged entirely | done | [step-02.md](step-02.md) |
| 3 | P2 — 4-category taxonomy + first-class narrator + enforced redaction | done | [step-03.md](step-03.md) |
| 4 | P3 — native dispatch + fail-closed allowlist lint + `/fleet` rule | done | [step-04.md](step-04.md) |
| 5 | P4 — per-agent model (`models:` block, name table, advisory) | done | [step-05.md](step-05.md) |
| 6 | P4-eval — implementer-adherence eval; gates the cheap-tier default | done | [step-06.md](step-06.md) |

## Risks
- **P2 test re-baseline churn** (27 `loose` refs + R-key tables) — mitigated by P1-first; full
  re-baseline budgeted, not patching.
- **Cheap-tier accuracy** — mitigated by Sonnet-not-Haiku + the fixed doc-quality contract + the
  Step-6 eval (≥90% must_haves, 0 critical-step failures).
- **Model-name drift / CI cost** — sync marker + test (Step 5); eval is nightly/manual + recorded CI
  fixture (Step 6), never per-PR live. Suggest `carter-risk` for deeper analysis if needed.

## Progress log
- **2026-06-27 — Steps 1–3 DONE** on branch `feat/005-agent-platform-refresh` (commits
  `5aececf` P0, `d320613` P1, `b437465` P2). Tests: **476 passing**
  (`PYTHONPATH=. .venv/bin/python -m pytest tests/ -q -p no:cacheprovider`). Not pushed, no PR.
  - State now: `POLICY_LEVELS=(guarded,strict)`, default `guarded`, zero policy-level `loose`;
    4-category taxonomy (read/local-write/remote-write/dangerous), secret-access merged into
    remote-write, R6 overlay dropped; D4 allowlist (devops sole remote-write/dangerous holder;
    narrator first-class {read, local-write}); enforced `gate`-tier narrator→devops redaction
    handoff; `temperature` and `runSubagent` gone everywhere.
  - **One user-approved divergence from the literal RFC text (the durable record):**
    `_validate_policy` normalizes **any** out-of-vocabulary `policy.level` to `guarded`
    **silently** — no `loose` literal, no migration notice, no coercion branch. The behavioral
    consequence the maintainer chose deliberately: a **typo** level (e.g. `strikt`) no longer
    raises, it becomes `guarded` (override category/gate typos still fail fast). Locked by
    `tests/test_config.py::TestPolicyLevelValidation::test_unknown_level_normalizes_to_guarded`.
    The four literal RFC D3.1 requirements (no coercion branch, grep-clean of policy-level `loose`,
    stale `loose`→`guarded`, and typos still raising) are not simultaneously satisfiable; the
    maintainer chose the generic-normalize resolution.
- **2026-06-27 — Step 4 (P3 native dispatch) DONE.** Tests: **503 passing** (476 + 27 new).
  - `policy_native_keys` now emits the real per-target dispatch primitive on the **primary** only:
    copilot `tools: [agent]` + explicit `agents: [...]` + `handoffs: [...]`; opencode
    `permission.task` (`'*': deny` + explicit per-specialist `allow`). Specialists carry
    `agents: []` (flat chain). Names honor `agent_suffix` (emitted suffixed; the post-render rewrite
    is idempotent over them). New `PRIMARY_ROLE` + `dispatch_specialists()` helpers in `config.py`.
  - **Fail-closed dispatch lint** (`_lint_dispatch_allowlist` in `scaffold.py`, wired into
    `lint_policy`): `carter check` **errors (exit non-zero)** when the primary's `agents:`/
    `permission.task` is `'*'`, a glob, or absent — verified end-to-end.
  - **`/fleet` context-injection rule** added to the maestro template + static prose (D1.D2):
    inject active-plan + knowledge + acceptance into every `/fleet` prompt. (Worded as "required
    outcomes", not the literal `must_haves` token, to keep the spec_handoff gating test honest.)
  - Re-baked all 7 static agent frontmatters (maestro dispatch keys; specialists `agents: []`).
    `docs/reference/frontmatter.md` documents the dispatch keys + the fail-closed lint.
  - New `tests/test_dispatch.py` (14) + `TestDispatchLint` (10) + `TestFleetContextRule` (2);
    re-baselined the 3 "empty-scope omits tools" tests for the maestro's `tools: [agent]`.
- **2026-06-27 — Step 5 (P4 per-agent model) DONE.** Tests: **527 passing**.
  - `models:` block added to `DEFAULT_CONFIG` (dict-shaped: default/thinkers/implementers/overrides).
    `MODEL_NAMES` table + `MODEL TIERS` map + `resolve_model()` (overrides > tier > default) in
    `config.py`, anchored by a `MODEL LAUNCH` sync-marker comment. Model ids re-verified against the
    bundled `claude-api` skill: Opus 4.8 = `claude-opus-4-8`, Sonnet 4.6 = `claude-sonnet-4-6`,
    Haiku 4.5 = `claude-haiku-4-5` (Haiku opt-in via overrides only).
  - `policy_native_keys` emits a SINGLE per-target `model:` string on every agent (display name for
    copilot, `provider/model` for opencode). Re-baked all 7 static frontmatters with their resolved
    model. Added `model` to the native-key drift lint.
  - Required `carter check` advisory (`model_advisory` in scaffold.py, wired into cli.py) — always
    prints each agent's pinned model + the can't-verify-subscription caveat + the global-effort note.
  - No effort key, no temperature (parity tests still green). Docs: `frontmatter.md` (models block +
    name table + advisory + effort), `getting-started.md` (models block + `--effort high` note),
    `strictness-policy.md` (model/effort quick-ref rows).
  - New `tests/test_models.py` (23) + `test_static_agents_carry_resolved_model` parity.
- **2026-06-27 — Step 6 (P4-eval) DONE. PLAN 005 COMPLETE.** Tests: **527 unit + 46 offline
  evals = 573 passing** (`-m "not live"`); 8 live deselected. Lint + format + mypy clean.
  - Fitted the implementer-adherence eval into the existing `evals/` framework (offline/live
    split, `live` marker, `EVAL_MODEL=claude-sonnet-4-6` single-sourced):
    - `evals/scenarios/implementer_adherence.yaml` — a thinker plan (token-bucket rate limiter)
      with `must_haves.truths` (named files, class, 429 path, tests) + `acceptance` checks +
      a stated `doc_quality_contract` (Opus bar).
    - `evals/adherence.py` — deterministic evidence-pattern grader: `adherence` (fraction of
      truths) + `critical_failures` (critical truths + acceptance); pass-bar ≥0.90 AND 0 critical.
    - `evals/fixtures/implementer_adherence_sonnet.json` — recorded Sonnet 4.6 transcript that
      clears the bar (adherence 1.0, 0 critical) — the empirical cheap-tier-shippable evidence.
    - `evals/test_adherence.py` (11, NO live marker) — replays the fixture deterministically;
      runs on the per-PR gate. `evals/test_adherence_live.py` (live) — billed Sonnet run,
      `EVAL_RECORD=1` re-records the fixture; weekly cron / manual only.
  - CI: `ci.yml` offline step now runs `evals/ -m "not live"` (includes the replay); `evals-live.yml`
    cron now runs `-m live` (includes the live adherence run). Live API NEVER on per-PR CI.
  - Also fixed 2 pre-existing C420 (my Step 4 dict-comprehensions) + 1 pre-existing E501 to leave
    the branch lint-clean.
- **Plan 005 status:** all 6 steps DONE on `feat/005-agent-platform-refresh`. NOT pushed, no PR
  (push_policy: manual). Commits: 5aececf P0, d320613 P1, b437465 P2, 0a2bc9b P3, d2543f6 P4, +P4-eval.
