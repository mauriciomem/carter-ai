---
id: 004-pipeline-versioning-and-evals
status: completed
created: 2026-06-14
updated: 2026-06-23
adr: ADR-0009
rfc: null
push_policy: manual
tags: [ci, release, semver, versioning, mypy, ruff, evals, packaging, quality-gate]
repos: [carter-ai]
must_haves:
  truths:
    - "Pushing a Conventional Commit to `main` triggers a release workflow that derives the next SemVer from commit types (fix→PATCH, feat→MINOR, `feat!`/`BREAKING CHANGE`→MAJOR), creates a matching `vX.Y.Z` git tag, and publishes a GitHub Release with generated notes"
    - "`carter --version` and the built wheel both report a version derived from the latest git tag as the single source of truth — no SemVer literal remains in `carter/__init__.py` or `[project].version`"
    - "CI runs `ruff check`, `ruff format --check`, and `mypy carter/` as required gates alongside the existing unit + offline-eval suites on py3.11 and py3.13"
    - "CI includes an `install-smoke` job that performs a real `uv tool install`, then `carter --version`, `carter init`, and `carter check`, green on Linux and macOS"
    - "The live-eval harness records per-scenario token usage (prompt/completion/total), wall-clock latency, and estimated cost; a SCHEDULED workflow runs live evals against a budgeted low-cost model via a repo secret, while PR CI uses only key-free offline evals"
    - "`carter/installer.py` is decomposed into a `carter/install/` package (no module > ~400 LOC) with behaviour preserved — every existing installer test passes unchanged"
  artifacts:
    - "docs/adr/0009-release-versioning-and-pipeline.md — the decision record this plan executes"
    - ".github/workflows/release.yml — semantic-release tag + CHANGELOG + GitHub Release"
    - ".github/workflows/ci.yml — extended with lint (ruff+mypy) and install-smoke jobs, SHA-pinned actions"
    - ".github/workflows/evals-live.yml — scheduled live evals with token/latency/cost metrics"
    - "pyproject.toml — dynamic version (hatch-vcs), [tool.ruff], [tool.mypy], semantic-release config, expanded dev extras"
    - "carter/install/ package replacing the monolithic installer.py; CHANGELOG.md from the first automated release"
    - "red→green tests for dynamic version resolution (tests/test_version.py) and eval-metrics capture (evals/test_metrics.py)"
  key_links:
    - "docs/testing.md"
    - "evals/README.md"
---

# Plan: Pipeline, SemVer Versioning & Eval Metrics (carter-ai)

## Objective
Move carter-ai from a hardcoded, untagged, single-job CI to an automated SemVer
release pipeline with tag-driven dynamic versioning, enforced code-quality gates
(ruff + mypy), a real install smoke test, a modular installer, and an eval harness
that measures accuracy AND cost. Every code step is TDD-first (red → green → refactor).

## Decisions (locked — authored as ADR-0009 in step 1)
- **Tag-driven version** via `hatch-vcs`: the git tag is the ONLY version source;
  remove the static `[project].version` + the dead `carter/__init__.py:__version__`.
  (Alt: file-driven PSR that writes a version literal back to source — REJECTED, it
  reintroduces a drift-prone string and a `chore(release)` commit per bump.)
- **python-semantic-release (PSR)** computes the bump from Conventional Commits and
  owns the `vX.Y.Z` tag, the CHANGELOG, and the GitHub Release.
- **Baseline tag `v0.1.0`** (amended from v2.0.0 — pre-1.0 to signal pre-stable); PSR computes bumps after.
- **Offline evals = key-free PR gate; live evals = budgeted weekly cron** with a
  repo-secret key (Copilot OAuth is unavailable on CI runners).

## Milestones
| #  | Milestone | Deliverables |
|----|-----------|--------------|
| M0 | Decision record | ADR-0009 (versioning + release + eval-metrics strategy) |
| M1 | Quality gates | ruff + mypy config, fixes, CI `lint` job |
| M2 | Dynamic versioning | hatch-vcs, drop static version, resolution tests |
| M3 | Release pipeline | PSR config, release.yml, baseline tag + first release |
| M4 | Install smoke | real install job (Linux + macOS) |
| M5 | Modular installer | split installer.py → carter/install/ |
| M6 | Eval metrics | tokens/latency/cost capture + scheduled live workflow |

## Progress (2026-06-23) — COMPLETED
All 10 steps done. Steps 1–4,7,9 merged earlier (`c551b39`,`874c4f2`). Steps 5,8,10 +
step-6 docs merged via PRs #2/#3, then three release-config fixes (PRs #4/#5): PSR
`allow_zero_version=true`+`major_on_zero=false` (stay pre-1.0), changelog `template_dir`
moved off Carter's `templates/`, and `build_command=""` (PSR Docker has no `uv`).
Baseline tag **v0.1.0**; first automated release **v0.1.1** (CHANGELOG + GitHub Release)
cut clean on 2026-06-23. Operational follow-up (not a plan step): add `ANTHROPIC_API_KEY`
repo secret for the weekly live-eval cron; remove README release badge (private repo,
PR #6).

## Steps
| #  | Step | Status | File |
|----|------|--------|------|
| 1  | ADR-0009 — release & versioning strategy | done | step-01.md |
| 2  | ruff config + autofix + CI ruff gate | done | step-02.md |
| 3  | mypy config + type fixes + CI mypy gate | done | step-03.md |
| 4  | hatch-vcs dynamic version + drop static version (TDD) | done | step-04.md |
| 5  | PSR config + release.yml (tag + CHANGELOG + Release) | done | step-05.md |
| 6  | Baseline tag v0.1.0 + first automated release (v0.1.1) + docs | done | step-06.md |
| 7  | install-smoke CI job (Linux + macOS) | done | step-07.md |
| 8  | Modularize installer.py → carter/install/ | done | step-08.md |
| 9  | Eval metrics: tokens/latency/cost + model-drift fix (TDD) | done | step-09.md |
| 10 | Pipeline eval strategy: offline gate + live cron + docs | done | step-10.md |

## Minimal pipeline tests for accuracy & functionality
**Per-PR gate (required · free · deterministic · NO key):** unit tests
(`pytest tests/`, 467) · offline evals (`test_routing.py`, `test_skills.py`, 28) ·
`ruff check` + `ruff format --check` · `mypy carter/` · `install-smoke` (real
install + `carter --version`/`init`/`check`).
**Weekly cron (accuracy canary · costs $ · key required):** live evals
(`test_live.py`) + LLM-judge → records pass-rate, mean judge score,
tokens/scenario, latency, $/run against a budgeted low-cost model.
*Minimum viable:* the per-PR set fully gates FUNCTIONALITY key-free; measuring
ACCURACY beyond structure REQUIRES live runs → one budgeted secret key on a cron.

## Risks
- **PSR ↔ hatch-vcs config** is the integration risk — step 5 opens with a doc
  spike (verify against 2026 PSR docs) before wiring; keep release.yml on a throwaway
  branch + dry-run until a tag verifies.
- **Baseline tag** is one-way: tag `v0.1.0` only after M2 lands or the build version
  resolves wrong.
- **mypy on installer.py** may surface many errors; step 3 starts non-strict and
  ratchets per-module (full strict tracked, not blocking M1 close).
- **installer split** is behaviour-preserving but broad — gated by step 7 smoke +
  steps 2-3 lint/type; intentionally LAST among code steps.

## Notes
Repo test cmd: `python -m pytest tests/ evals/test_skills.py evals/test_routing.py -q -p no:cacheprovider`
(exclude `evals/test_live.py` — it hangs). All NEW GitHub Actions SHA-pinned
(`uses: owner/action@<sha> # vX.Y.Z`). Conventional Commits already in use repo-wide —
PSR's input is ready. `push_policy: manual` → tags/releases are remote writes; never
push without explicit user approval.
