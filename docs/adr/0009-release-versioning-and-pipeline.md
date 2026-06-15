---
id: ADR-0009
status: accepted
created: 2026-06-15
decided: 2026-06-15
supersedes: []
superseded_by: null
rfc: null
tags: [ci, release, semver, versioning, packaging, quality-gate, evals]
---

# ADR-0009: SemVer release pipeline, tag-driven versioning, quality gates & eval economics

**Status:** Accepted
**Date:** 2026-06-15
**Deciders:** mauriciomem (author)

## Context

Carter ships as a Python CLI installed from git (`uv tool install
git+https://github.com/...`); it is a scaffolder, not a service. Its release and
quality posture today has concrete, source-verified gaps:

- **Version is hardcoded in two places and drifts.** `[project].version = "2.0.0a1"`
  in `pyproject.toml` AND `__version__ = "2.0.0a1"` in `carter/__init__.py`. The
  latter is **dead code** — never imported anywhere. The CLI's `--version` reads
  **package metadata** (`carter/cli.py`: `@click.version_option(package_name=
  "carter-ai")` → `importlib.metadata.version`), so the two literals can silently
  diverge. The build backend is **static** `hatchling` (no VCS versioning).
- **There are zero git tags and no releases.** `git tag` is empty; `git describe`
  yields a bare SHA. There is no `CHANGELOG`, no GitHub Release, and no machine
  link between "what changed" and "what version". `uv tool upgrade` is a documented
  no-op while the version stays pinned at `2.0.0a1`.
- **CI is a single `test` job** (`.github/workflows/ci.yml`, py3.11/3.13). There is
  **no lint, no type-check, no release automation, and no real install verification**.
  The `dev` extras contain only `pytest`. Actions are tag-pinned, not SHA-pinned.
- **The largest module is a 1,171-LOC monolith** (`carter/installer.py`) mixing
  console output, path resolution, JSONC parsing, VS Code detection, MCP config and
  install/uninstall orchestration.
- **The eval harness already measures accuracy but discards cost.** `evals/`
  has offline (key-free, deterministic), live (real-model), and LLM-judge layers,
  but every call reads `choices[0].message.content` and **ignores the `usage`
  token block** the APIs return. The default model name also **drifts** between the
  README and the code (`claude-sonnet-4-20250514` vs `claude-sonnet-4.6`).

The repo already uses **Conventional Commits** repo-wide (`feat`, `fix`,
`refactor`, `chore`, `docs`, …) — exactly the input automated SemVer needs.

This ADR records the decision executed by plan
`004-pipeline-versioning-and-evals`.

## Decision

One coherent modernization of the release/quality pipeline, as five
interdependent sub-decisions sharing a single boundary — *what the CI/release
pipeline produces and guarantees*.

- **D1 — Tag-driven dynamic version (`hatch-vcs`).** The git tag becomes the
  **single source of truth** for the version. Switch the build to `hatch-vcs`
  (`dynamic = ["version"]`, `[tool.hatch.version] source = "vcs"`), **remove** the
  static `[project].version`, and **delete** the dead `carter/__init__.py`
  `__version__` (or re-export a build-time `_version.py`). An untagged checkout
  resolves to an informative dev version (`X.Y.Z.devN+g<sha>`); a tagged one
  resolves exactly.
- **D2 — SemVer automation via python-semantic-release (PSR).** PSR reads
  Conventional Commits since the last tag and derives the bump: `fix:` → PATCH,
  `feat:` → MINOR, `feat!:`/`BREAKING CHANGE:` → MAJOR; `docs/chore/refactor/test/
  ci/build/style` → no release. PSR owns the `vX.Y.Z` tag, the `CHANGELOG`, and the
  GitHub Release. The version literal is **never** written back into source (D1).
- **D3 — Baseline tag `v2.0.0`.** A one-time, manually created annotated tag at the
  chosen `main` commit graduates the current `2.0.0a1` pre-release and gives PSR and
  `hatch-vcs` a starting point. Every subsequent version is computed.
- **D4 — Quality gates in CI.** `ruff` (lint + format-check) and `mypy carter/`
  become **required** checks, plus an **`install-smoke`** job that performs a real
  `uv tool install` then `carter --version` / `init` / `check` on **Linux and
  macOS**. All new/edited Actions are **SHA-pinned** (`uses: owner/action@<sha> #
  vX.Y.Z`). `mypy` starts non-strict and ratchets per-module.
- **D5 — Eval economics: offline gate + live cron.** Offline evals remain the
  **key-free, deterministic, required PR gate**. Live/accuracy evals move to a
  **scheduled (weekly) workflow** using a **repo-secret key** and a **budgeted
  low-cost model**, capturing **token usage, latency, and estimated cost** per
  scenario. PR CI never needs a key.

## Options Considered

### Versioning (D1)

**Option A — Keep the two hardcoded literals (status quo).**
- **Pros:** zero effort.
- **Cons:** the two strings drift; `--version` and the wheel can disagree; manual
  bumps; dead `__version__`; no tags/releases.

**Option B — File-driven PSR (PSR writes the version back into source).**
- **Pros:** a version literal stays greppable in the tree.
- **Cons:** reintroduces the **drift-prone literal** D1 set out to remove, and adds
  a `chore(release)` commit to `main` per bump (noisy history, push-on-release).

**Option C (CHOSEN) — Tag-driven `hatch-vcs` + PSR computes the tag.**
- **Pros:** the tag is the only source; nothing version-like is committed; git
  install `@vX.Y.Z` is exact; kills the dual-source bug at the root.
- **Cons:** the working-tree version is a dev string until a tag exists; one new
  build dependency.

### Eval execution in CI (D5)

**Option A — Run live evals on every PR.**
- **Pros:** maximal accuracy signal per change.
- **Cons:** costs money per PR; non-deterministic → flaky merge gate; needs a key
  exposed to all PR runs (incl. forks).

**Option B (CHOSEN) — Offline gate on PR + live cron canary.**
- **Pros:** deterministic, free, key-free merge gate; accuracy/cost tracked on a
  cadence with a bounded budget and a single trusted secret.
- **Cons:** accuracy regressions surface on the cron cadence, not per-PR.

**Option C — Drop live evals entirely.**
- **Pros:** simplest; no key, no spend.
- **Cons:** accuracy and token-cost are never measured — the explicit goal is lost.

## Rationale

- **Eliminate the drift at its source.** The version bug is *two literals that can
  disagree*. Only a single non-source source of truth (the tag, D1) removes it;
  Option B would re-create it. PSR (D2) makes the tag a deterministic function of
  the commit log the repo already keeps.
- **Cheap, honest accuracy signal.** The APIs already **return** `usage`; capturing
  it (D5) is near-zero cost and turns the existing harness into a cost dashboard.
  Live evals test the **prompt markdown sent to a raw model** — a good proxy for
  prompt quality, **not** the real VS Code tool-calling loop; the cron framing keeps
  that limitation honest and the spend bounded.
- **Key reality on CI runners.** Locally, evals reuse Copilot OAuth (no key). On CI
  runners that token is **unavailable** (`gh auth token` yields only the repo
  `GITHUB_TOKEN`, which has no Copilot API access; no `opencode/auth.json` exists),
  so live evals there **require** a dedicated secret — justifying the offline/cron
  split rather than gating PRs on a paid, flaky call.
- **Gates before refactor.** Landing `ruff`/`mypy`/`install-smoke` (D4) *before* the
  installer decomposition gives that refactor a real safety net (the 75 installer
  tests + a genuine end-to-end install), so structure can improve without behaviour
  drift.

## Consequences

### Positive
- `carter --version`, the wheel, and `git install @vX.Y.Z` always agree (D1).
- Releases, tags, and `CHANGELOG` are automatic and traceable to commits (D2/D3).
- Lint, types, and a real install path are enforced on every PR, on two OSes (D4).
- Accuracy **and** token/latency/cost are measured on a bounded budget (D5).

### Negative
- New build/release dependencies (`hatch-vcs`, `python-semantic-release`) and new
  workflows to maintain.
- The live cron consumes a paid API budget and requires a stored secret.
- An initial `mypy` debt surfaces on the large modules (paid down by ratchet).

### Risks
- **PSR ↔ `hatch-vcs` integration** is the main unknown → the plan front-loads a
  doc-verification spike and dry-runs releases on a throwaway branch before wiring
  `main`.
- **The baseline tag is one-way** once others pull → tag `v2.0.0` only after dynamic
  versioning resolves correctly.
- **Secret handling** for the live cron → never echo the key; restrict the workflow
  to non-fork triggers (`schedule`/`workflow_dispatch`).

## References

- `docs/testing.md`, `evals/README.md` — current test/eval layers.
- `.github/workflows/ci.yml`, `carter/cli.py`, `carter/__init__.py`,
  `pyproject.toml`, `carter/installer.py` — the surfaces this ADR changes.
- Plan `004-pipeline-versioning-and-evals` (private `.carter/` workspace) — the
  execution plan implementing D1–D5.
- Semantic Versioning 2.0.0 (https://semver.org); Conventional Commits 1.0.0
  (https://www.conventionalcommits.org); python-semantic-release; `hatch-vcs`.
- [ADR-0003](0003-knowledge-adr-rfc-plan-storage.md) (frontmatter contract),
  [ADR-0005](0005-risk-based-strictness-policy.md) (Carter is a scaffolder).
