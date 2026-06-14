---
id: ADR-0002
status: accepted
created: 2026-06-06
decided: 2026-06-06
supersedes: []
superseded_by: null
tags: [agents, generation, scaffold, parity]
---

# ADR-0002: Single-source agent definitions via build-time generation

**Status:** Accepted (phase 1 + follow-ups shipped); phase 2 (build-time generation) Won't Do — see Current Status
**Date:** 2026-06-06 (phase 2 abandoned 2026-06-07)
**Deciders:** Carter maintainer (mauriciomem), Carter Maestro
**Reference format:** Michael Nygard ADR (<https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions>)
**Related:** ADR-0001 (added the narrator's static source; surfaced the dual-source sync burden)

---

## Current Status (verified 2026-06-06)

> This ADR accreted several follow-ups in one session. Read this block first; the
> historical Context/sketch sections below are preserved as the decision record
> and some of their "current state" claims are **superseded** (marked inline).

| Item | Status | Where |
|------|--------|-------|
| Phase 1 — parity tests | **DONE** | `tests/test_parity.py` (8 tests), commit `ef0a1ad` |
| Phase 1 — CI | **DONE & green** | `.github/workflows/ci.yml` (py3.11/3.13), commits `ef0a1ad`/`68c2c2b`/`f8ba618` |
| Frontmatter divergence | **FIXED** | templates emit frontmatter byte-matching static; commit `7712f59` |
| `mode` vocabulary | **RESOLVED** | maestro `primary`, six specialists `subagent`; commit `7712f59` |
| Scaffold-agent discovery | **FIXED** | `_render_and_write` honors `config["target"]`, writes discovery paths; commit `74311a6` |
| Agent name collision → `agent_suffix` | **FIXED** | workspace agents suffixed (default `local`) to stay distinct from global; commit `9512cbe` |
| `carter init` `--target`/`--agent-suffix` flags | **DONE** | scaffold target/suffix without editing YAML; commit `c7c6c75` |
| Narrator/redaction edge-case guard | **DONE** | `config_warnings` warns on init/update/check when narrator on + redaction off; commit `c7c6c75` |
| Phase 2 — build-time generation + drift check | **WON'T DO** | premise falsified — static and template are different agent *designs*, not the same content; see “Phase 2 abandoned” below |

**Ground truth at audit:** 7 static agents + 7 templates (frontmatter parity
verified for all 7), 22 skills, 231 unit tests + 28 offline evals, CI green.
Discovery + naming **confirmed end-to-end** in VS Code (workspace
`carter-engineer-local` loads and is distinct from the global agent).

**Where this ADR landed:** phases 1 + follow-ups (parity tests, CI, frontmatter,
modes, discovery, `agent_suffix`, init flags, redaction guard) are all shipped.
**Phase 2 (build-time generation) is abandoned** — the dual sources are not
duplicates but two distinct agent designs, so generation would rewrite shipped
content rather than dedup it. The drift risk it targeted is already covered by
`tests/test_parity.py`. This ADR is effectively complete.

---

## Context

Carter defines each agent in **two** places:

- `agents/carter-*.md` — static Markdown, **copied** verbatim by `carter install`
  to `~/.copilot/` ([carter/installer.py](../../carter/installer.py) `install_agents`, plain `shutil.copy2`).
- `templates/agents/carter-*.md.j2` — Jinja, **rendered** against `carter.yaml`
  by `carter init` / `carter update` ([carter/scaffold.py](../../carter/scaffold.py) `render_agents`).

This is a deliberate split (two delivery models: global-ready vs. per-workspace
customizable), but it carries a **dual-source sync burden**: a behavioral change
must be applied to both files or they drift. ADR-0001 was itself partly a drift
incident — the narrator had only a template and no static file, so `carter install`
silently shipped 6 agents instead of 7.

The natural "DRY" reaction is *templates-only, render at install time*. A prior
analysis rejected that (Jinja in the install critical path; a synthetic
system-level config with no `carter.yaml`; conditional security content; manifest
non-determinism; the duplication merely relocating into test fixtures). The
remaining candidate is **build-time generation**: keep one hand-edited source,
render the static artifacts during packaging, and commit them as generated files.

### Blocking finding (verified) — the two sources have already diverged structurally

> **⚠ Superseded (2026-06-06):** the divergence described here was the *pre-fix*
> state. Templates now emit frontmatter that byte-matches the static files
> (commit `7712f59`). Retained as the decision-time rationale; see Current Status.

Build-time generation assumes the static file *is* the template rendered with a
default config. **It is not.** Rendering `templates/agents/carter-engineer.md.j2`
with `generate_default_config()` and diffing against `agents/carter-engineer.md`:

| Aspect | Static `agents/carter-engineer.md` | Rendered from template |
|--------|-----------------------------------|------------------------|
| YAML frontmatter | `description:` / `mode: agent` / `temperature: 0.1` | **none** |
| First line | `---` | `<!-- Generated by Carter v2 … -->` |
| Identity prose | "You are … an expert in: …" | "Pragmatic, disciplined, quality-focused." |
| Role section | prose expertise list | `What you do:` / `What you don't do:` bullets |
| Trailing block | none | `## Available Agents` footer |

They are **two independently-authored definitions** that share a name, not one
artifact in two formats. This has three consequences:

1. **Build-time generation is not a no-op refactor.** Generating `agents/*.md`
   from the templates would *change what `carter install` ships* — stripping the
   `mode: agent` / `temperature` frontmatter (which the Copilot/OpenCode agent
   loaders likely rely on) and adding a "Generated by Carter v2" banner + agents
   footer.
2. **It cannot be adopted until the sources are reconciled** — the templates must
   first be made to emit exactly what install should ship (frontmatter included).
   Because the same templates feed `carter init`, that reconciliation also changes
   **scaffolded-workspace** output.
3. **A latent question falls out:** scaffolded agents currently render *without*
   frontmatter. If the agent runtimes need `mode`/`temperature`, workspace agents
   may be subtly under-specified today — independent of this ADR.

### Infrastructure reality

> **⚠ Superseded (2026-06-06):** CI now exists
> ([.github/workflows/ci.yml](../../.github/workflows/ci.yml)). The text below
> describes the pre-CI state.

This repo has **no CI workflow and no pre-commit config** of its own (only
`yui-soul/` and `external/` carry workflows). Any "drift check" guardrail is
**net-new infrastructure**, not a tweak to an existing pipeline.

---

## Decision (proposed)

**Do not adopt build-time generation yet.** The artifacts are not equivalent, so
generation would regress shipped content. Instead, sequence it:

1. **Now — keep dual-source; add a parity contract.** Replace "remember to edit
   both" with tests that assert the *invariants* that matter exist in both
   sources (not byte-equality, which is currently false). Example already in
   place: `TestNarratorAgent` asserts the static narrator carries all 7 redaction
   categories. Extend this pattern to the security/structural invariants that must
   never drift.
2. **Later (separate, deliberate project) — reconcile, then generate.** Decide the
   canonical shape (frontmatter + body), make the templates emit it, regenerate
   `agents/*.md` as committed generated artifacts, and add a CI drift-check. Only
   then is the sync burden truly removed.

The rest of this ADR sketches step 2 so the cost is visible, and records why it is
gated behind step 1.

---

## Phase 2 abandoned — verified 2026-06-07

When phase 2 was finally attempted, the prerequisite check killed it. Rendering
the templates with the default config (`agent_suffix=""`) and diffing against the
current static `agents/*.md`:

```
carter-architect.md   92 diff lines
carter-devops.md      88
carter-engineer.md   111
carter-learner.md     79
carter-maestro.md    178
carter-narrator.md   106
carter-pm.md          86
files differing: 7/7
```

This is **not** frontmatter drift (that was reconciled in commit `7712f59`). The
**bodies are two different agent designs**:

| Aspect | Static `agents/*.md` (shipped by `carter install`) | Template-rendered |
|--------|----------------------------------------------------|-------------------|
| Identity | `<role>` "You are … an expert in: …" prose | `<identity>` "Pragmatic, disciplined, quality-focused" |
| Role | prose paragraphs | `What you do:` / `What you don't do:` bullets |
| Skills | explicit `<skills>` block (+ this session's review-register voice) | none |
| Tool access | explicit `<mcp>` block | none |
| Extras | — | `<boundaries>`, `## Available Agents` footer, config-gated blocks |

**Conclusion:** the static and template agents are **two independently authored
designs that share a name**, not one artifact duplicated. Build-time generation
would therefore *overwrite all 7 shipped agents with the template design* —
discarding the richer static content. That is a product change to every
`carter install`, not the mechanical dedup phase 2 was framed as.

**Decision: do not generate (Won't Do).** The drift risk phase 2 targeted is
already covered by `tests/test_parity.py`, which locks the invariants that must
not diverge (frontmatter, redaction categories, ops one-liner, mode vocabulary,
agent-set parity). Keeping the two designs is acceptable — they may both be
intentional. Reviving generation would first require a deliberate *content*
project to choose/merge a single canonical agent design for all seven; that is
out of scope here and not currently justified.

> The sketch below is retained for historical context only. **Do not implement
> it** without first resolving the design-reconciliation question above.

---

## Sketch — build-time generation + drift check (NOT pursued)

The abandoned design, recorded for context: **(A)** a `scripts/generate_agents.py`
renders every template with the system default config and writes the static
`agents/*.md`; **(B)** a hatchling custom build hook (`hatch_build.py`) runs it
during the wheel build so committed agents match templates; **(C)** a net-new CI
job runs the generator then `git diff --exit-code agents/` to fail on drift
(optionally mirrored in a pre-commit hook); **(D)** generated files carry a
`<!-- generated — edit templates/ -->` banner + a CODEOWNERS/README note.

The hard prerequisite — and the reason it was abandoned — is that the templates
must first emit install-ready output (frontmatter + the richer static body).
Until that reconciliation, the generator would *regress* all 7 shipped agents to
the leaner template design (see "Phase 2 abandoned"). Canonical source would be
the **templates** (they already carry the conditional logic; static files cannot
mechanically re-introduce `{% if redaction %}`).

---

## Options Considered

### Axis A — How to remove the sync burden

**A1 — Templates-only, render at install time.** Rejected previously: Jinja in the
install critical path; synthetic config with no `carter.yaml`; security content
becomes conditional; manifest non-determinism; duplication relocates to fixtures.

**A2 — Build-time generation (this sketch).** Single hand-edited source; install
stays a dumb copy; shipped artifact stays inspectable/grep-able in git. Cost: a
build step, a "don't edit generated files" rule, **and a prerequisite
reconciliation** because the sources currently diverge. Net-new CI for the drift
check.

**A3 — Keep dual-source + parity tests (CHOSEN for now).** Lowest cost; no build
or CI changes; keeps both artifacts inspectable. Does not achieve single-source —
the burden remains, mitigated rather than removed.

**A4 — Status quo, nothing added.** Rejected: leaves the drift risk that already
bit once (ADR-0001) with no guardrail.

### Axis B — If generating, which source is canonical

**B1 — Templates canonical (CHOSEN if we proceed).** Templates already carry the
conditional logic; static files are derivable. Requires templates to emit
frontmatter and the desired body.

**B2 — Static canonical, generate templates from them.** Backwards — you cannot
mechanically re-introduce conditional logic (`{% if redaction %}`) from a flat
rendered file. Rejected.

### Axis C — Drift-check enforcement

**C1 — CI `git diff --exit-code` (CHOSEN if we proceed).** Authoritative, blocks
merge on drift. Cost: stand up CI (none exists).

**C2 — Pre-commit only.** Faster locally but bypassable; insufficient alone.

**C3 — Build-hook only (regenerate silently at build).** Hides drift instead of
failing on it; a hand-edit to a generated file would be silently overwritten.
Rejected as a sole mechanism.

---

## Consequences

### If we adopt step 1 (parity tests) now
- **Positive:** drift guardrail with zero build/CI changes; invariants enforced;
  both artifacts stay inspectable.
- **Negative:** sync burden remains (two files to edit); parity tests assert
  invariants, not full equivalence, so non-invariant wording can still drift.

### If we later adopt step 2 (generation + drift check)
- **Positive:** one hand-edited source; shipped artifact still materialized and
  diffable; Jinja stays out of the install path; drift caught in CI.
- **Negative / costs:**
  - **Reconciliation project** to make templates emit install-ready output
    (frontmatter, body), which also alters `carter init` output.
  - **Net-new CI** (and optional pre-commit) infrastructure.
  - **Render determinism** becomes a requirement (whitespace, dict ordering,
    trailing newline) or the committed artifacts churn.
  - New contributor rule: never hand-edit `agents/*.md`.
  - The default-config used for generation becomes a load-bearing input.

### Risks
- **Silent content regression** during reconciliation (e.g., dropping
  `mode: agent`). Mitigation: snapshot the current static files and diff the first
  generation against them deliberately, line by line, before committing.
- **Scaffold behavior change** for existing workspaces on `carter update`.
  Mitigation: treat the frontmatter question as its own decision first.

---

## Recommendation

1. **Adopt A3 now** — add parity/invariant tests around the security- and
   structure-critical parts of the dual sources (starting from the existing
   `TestNarratorAgent` pattern).
2. **Separately investigate the frontmatter divergence** — determine whether
   scaffolded agents *should* carry `mode`/`temperature`. This answer is a
   prerequisite input to any generation work and may be a bug fix in its own right.
3. **Defer A2** (build-time generation + CI drift check) until 1–2 are resolved;
   revisit with this ADR as the basis. Do not pursue A1 (install-time rendering).

---

## Open Decisions (please react during review)

1. **Proceed with parity tests now (A3)?** Or accept status quo (A4)?
2. **Is the missing frontmatter in scaffolded agents a bug** to fix independently?
3. **Appetite for net-new CI** (GitHub Actions) for this repo — yes/no? It's the
   gating cost for any drift check.
4. **Scope of "invariants"** to lock with parity tests: redaction categories +
   `ops:` one-liner + agent count are obvious; what else must never drift?

## Resolved (review 2026-06-06)

1. **Parity tests now — YES.** `tests/test_parity.py` added (phase 1 / A3).
2. **Frontmatter divergence — noted as a separate follow-up**, not fixed here. It
   is a prerequisite input to phase 2 (generation) and may be a scaffold bug in
   its own right.
3. **Net-new CI — YES.** `.github/workflows/ci.yml` runs the unit suite + offline
   evals on Python 3.11 and 3.13. The *agent-generation drift check* remains
   deferred (phase 2) because generation would regress shipped content today.
4. **Invariants locked:** agent-set parity (static ↔ template), static-agent
   frontmatter (`description:`/`mode:`), the `ops:` one-liner, and the narrator's
   redaction contract + "write for the reader" principle in both sources.

---

## Follow-up — Frontmatter divergence investigated & fixed (2026-06-06)

The frontmatter divergence flagged above was investigated against the official
agent-format docs. Findings:

1. **Templates emitted no frontmatter at all.** The base template started at the
   `<!-- Generated -->` comment; no agent template carried `description`/`mode`/
   `temperature`. So `carter init` produced agents missing fields the runtimes use.
2. **The frontmatter is load-bearing.** Per OpenCode docs, markdown agents use
   frontmatter and **`description` is required**; `temperature` and `mode` are
   honored. VS Code surfaces `description` in the agents picker. The installer
   itself treats the frontmatter files as the canonical format
   ([carter/installer.py](../../carter/installer.py): "store canonical files and
   copy to both locations as-is").
3. **The data lived only in the static `.md` files** — `carter.yaml`/`DEFAULT_CONFIG`
   carried no per-agent metadata.

**Fix applied (this change):** added a `frontmatter` Jinja block to
[templates/base_agent.md.j2](../../templates/base_agent.md.j2) and literal
`description`/`mode`/`temperature` to all 7 agent templates, with values copied
from the static files. Rendered output now begins with valid YAML frontmatter that
**byte-matches the static files' frontmatter** (verified for all 7). Two parity
tests in `tests/test_parity.py` lock this: rendered agents must have valid
frontmatter, and it must equal the static file's. This also **unblocks phase 2** —
`render_agents` now produces install-ready output.

### Recorded open items (NOT changed here — deliberate)

These were found during the investigation but are *not* safe to change blindly,
because the static files are the live, working Copilot format:

- **`mode` vocabulary mismatch.** The agents use `mode: agent` (specialists) /
  `mode: primary` (maestro). OpenCode's documented values are
  `primary | subagent | all` — so `mode: agent` is not a valid OpenCode value and
  likely defaults to `all` there (specialists would also appear as primary). This
  is a **pre-existing** cross-platform format issue in the static files, not
  introduced by the template fix. Changing it requires live OpenCode/Copilot
  testing and likely a **per-target format translation** at install time. Tracked
  for a separate decision; the template fix faithfully preserves the current
  values so nothing regresses.

  **Resolved (2026-06-06):** adopted the pure-orchestrator model — `maestro` is
  the sole `mode: primary`; the other six agents (architect, devops, engineer,
  learner, pm, narrator) are `mode: subagent`. All values are now valid OpenCode
  modes. In OpenCode the specialists leave the primary/Tab cycle and are reached
  via Maestro routing or `@`-mention (still "direct access"); `mode` is not used
  by the VS Code/Copilot format (which uses `user-invocable`/
  `disable-model-invocation`), so Copilot behavior is unchanged. A parity test
  (`test_mode_vocabulary_is_valid_and_orchestrator_only`) locks this. README
  examples that selected a specialist as the top-level `--agent` were reconciled
  to Maestro + `@`-mention.
- **Scaffold-agent discovery is undocumented.** `carter init` wrote agents to
  `<workspace>/agents/`, which no tool discovers.

  **RESOLVED & IMPLEMENTED (2026-06-06) — confirmed bug, then fixed.**
  `_render_and_write` ([carter/cli.py](../../carter/cli.py)) ignored
  `config["target"]` and wrote undiscoverable paths. Fix: honor `config["target"]`
  (`copilot`/`opencode`/`all`) and render to the documented discovery paths —
  Copilot `.github/agents/*.md` + `.github/copilot-instructions.md`; OpenCode
  `.opencode/agents/*.md` + `AGENTS.md`. Carter-owned `carter-*` agents are always
  (re)written so `carter update` refreshes them; `AGENTS.md` /
  `.github/copilot-instructions.md` are skip-if-exists to avoid clobbering user
  files. `carter check`/`update --dry-run` follow suit. Six `TestRenderDiscovery`
  tests cover all three targets + skip-if-exists; getting-started.md tree updated.
  Still needs manual VS Code/OpenCode load confirmation (no runtime here).

  **Follow-up — agent name collision → `agent_suffix` (2026-06-07).** With
  discovery fixed, a workspace that *also* has Carter globally installed showed
  **two** indistinguishable `carter-engineer` agents. Fix: a configurable
  `agent_suffix` (default `local`, empty = none) in `carter.yaml` that suffixes the
  filename AND every `carter-<role>` reference via a centralized `carter.scaffold`
  transform scoped to configured roles (skill names untouched). Global install
  unaffected. Covered by `TestAgentSuffix` (10 tests); verified end-to-end
  (`.github/agents/carter-engineer-local.md` with `-local` routing throughout).

---

## References

- ADR-0001 — narrator first-class + content suite ([0001-narrator-content-suite.md](0001-narrator-content-suite.md)); Hatchling build hooks — <https://hatch.pypa.io/latest/plugins/build-hook/reference/>
- OpenCode agents (frontmatter, required `description`, `mode`, `temperature`) — <https://opencode.ai/docs/agents/>; VS Code custom agents — <https://code.visualstudio.com/docs/copilot/customization/custom-agents>
- Evidence: `render_agents(generate_default_config(...))` vs `agents/carter-engineer.md` (divergence), gathered 2026-06-06.
