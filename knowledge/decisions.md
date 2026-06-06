# Decisions

> Architecture Decision Records and trade-off analyses tracked by Carter.

<!-- Entries are added by the carter-distill skill. Format:
## YYYY-MM-DD | Title
- **Context:** ...
- **Decision:** ...
- **Rationale:** ...
- **Alternatives considered:** ...
- **Tags:** ...
-->

## 2026-06-06 | Deep audit: ADR-0001/0002 status verified + edge case found
- **Context:** Full audit of agents, skills, source, and tests against the ADRs to produce an updated status. Everything verified consistent: 7 agents (maestro primary, 6 subagent), 7 templates with frontmatter byte-matching static, 22 skills, 205 unit + 28 offline eval tests, CI green, anti-drift contracts honored in the real skill files.
- **Decision:** Added a "Current Status" block to ADR-0002 (consolidating its scattered follow-ups) and marked its stale Blocking-finding/Infrastructure sections superseded; added an "Implementation Status" stamp to ADR-0001. No code changes — docs/status only.
- **Edge case recorded (not fixed):** the narrator template gates redaction on `config.redaction.enabled`; a workspace with redaction off + narrator enabled scaffolds a narrator with NO redaction rules while maestro still routes external content to it. The parity test reads the template raw so it misses this. Future guard: warn/assert when narrator is enabled but redaction is off.
- **Tags:** audit, adr-0001, adr-0002, status, edge-case, redaction

- **Context:** The narrator was the only agent without a static source (template-only), so `carter install` shipped 6 agents and never the narrator. Narrative voice was fragmented with no developer-docs or public-storytelling skill.
- **Decision:** (D1) Add `agents/carter-narrator.md` so the narrator is always installed (6→7 agents, redaction ON/7 categories baked in). (D2) New `carter-docs` skill (Diátaxis + Keep a Changelog/Conventional Commits + git-aware doc-audit). (D3) New `carter-story` skill (public-facing narrative). (D4) Terse ticket/PR/issue responses are a **Brief register**, not a skill. Skills 20→22.
- **Rationale:** Completes the dual-source agent pattern; puts style in globally-installed skills while redaction stays at the narrator agent gate; reuses the register + Scope Gate patterns; delegation (carter-adr, carter-diagram, pptx/docx) prevents drift.
- **Alternatives considered:** Keep narrator scaffold-only (rejected: orphan/inconsistent); render template at install time (rejected: Jinja in installer = over-engineering); one-skill-per-surface (rejected: overlap); mega narrate skill (rejected: kitchen sink); split into 3–4 ADRs (rejected: would duplicate/orphan the anti-drift table).
- **Tags:** architecture, agents, skills, narrator, documentation, adr-0001

## 2026-06-06 | Agent source parity + CI; build-time generation deferred (ADR-0002)
- **Context:** Each agent is defined twice — static `agents/*.md` (copied by `carter install`) and `templates/agents/*.j2` (rendered by `carter init`). This dual-source sync burden caused the ADR-0001 narrator drift. Rendering revealed the two sources have structurally diverged (static files carry YAML frontmatter; templates do not), so build-time generation is not a drop-in.
- **Decision:** Phase 1 now — add `tests/test_parity.py` locking cross-source invariants (agent-set parity, static frontmatter, ops one-liner, narrator redaction + reader principle in both sources) and stand up `.github/workflows/ci.yml` (unit suite + offline evals on py3.11/3.13). Phase 2 (reconcile templates to emit install-ready output, then generate `agents/*.md` at build time with a CI `git diff --exit-code` drift check) is deferred.
- **Rationale:** Generating agents today would regress shipped content (strip frontmatter). Parity tests give the drift guardrail now at near-zero cost; install stays a dumb copy; the shipped artifact stays inspectable in git. Install-time rendering (A1) rejected: Jinja in the install path, synthetic config, conditional security content.
- **Alternatives considered:** Templates-only render-at-install (rejected); status quo with no guardrail (rejected); static-as-canonical generate-templates (rejected — can't recover conditional logic from flat files).
- **Tags:** architecture, agents, build, ci, testing, adr-0002

## 2026-06-06 | Agent templates now emit frontmatter (ADR-0002 follow-up)
- **Context:** Investigation confirmed `carter init` rendered agents with NO YAML frontmatter, while static `agents/*.md` carry `description`/`mode`/`temperature`. Per OpenCode docs `description` is required and `mode`/`temperature` are honored; VS Code surfaces `description`. So scaffolded agents were under-specified (a real bug) and templates couldn't be used to generate static files (phase-2 blocker).
- **Decision:** Add a `frontmatter` Jinja block to `templates/base_agent.md.j2` and literal `description`/`mode`/`temperature` to all 7 agent templates, values copied from the static files. Rendered frontmatter now byte-matches the static files (verified); 2 new parity tests lock it.
- **Rationale:** Fixes the scaffold bug and unblocks ADR-0002 phase-2 generation, while faithfully preserving the current working values (no regression).
- **Alternatives considered:** Config-driven per-agent metadata (deferred — only needed if workspace-level overrides are wanted); leave templates frontmatter-less (rejected — the bug + the phase-2 blocker).
- **Open items recorded (not changed):** `mode: agent` is not a valid OpenCode value (`primary|subagent|all`) — pre-existing cross-platform issue needing per-target translation; scaffold-agent discovery (`<workspace>/agents/`) is undocumented and may not be auto-loaded.
- **Tags:** architecture, agents, templates, scaffold, frontmatter, adr-0002

## 2026-06-06 | Pure-orchestrator agent modes (ADR-0002 follow-up)
- **Context:** Agents used `mode: agent`, which is not a valid OpenCode mode (`primary|subagent|all`) and falls back to `all` (specialists wrongly appear as primary).
- **Decision:** Adopt the pure-orchestrator model — `carter-maestro` is the sole `mode: primary`; the other six (architect, devops, engineer, learner, pm, narrator) are `mode: subagent`, in both static files and templates. Parity test `test_mode_vocabulary_is_valid_and_orchestrator_only` locks it.
- **Rationale:** Matches Carter's architecture (maestro orchestrates, specialists are routed to / `@`-mentioned). In OpenCode specialists leave the primary cycle but stay reachable via routing + `@`-mention; `mode` is unused by the VS Code/Copilot format so Copilot is unchanged.
- **Alternatives considered:** `mode: all` (keep specialists directly selectable as primary too) — rejected in favor of the cleaner one-front-door model; README `--agent <specialist>` examples reconciled to Maestro + `@`-mention.
- **Open item still tracked:** scaffold-agent discovery (`<workspace>/agents/`) undocumented.
- **Tags:** architecture, agents, mode, opencode, adr-0002

## 2026-06-06 | Scaffold-agent discovery is a confirmed bug (ADR-0002, fix deferred)
- **Context:** `carter init`/`_render_and_write` writes agents to `<workspace>/agents/` and instructions to `<workspace>/instructions/`, but no tool discovers those paths. `config["target"]` exists (default copilot) yet is ignored. yui-soul already renders to the correct paths.
- **Decision:** Investigated and confirmed it's a bug; fix DESIGNED but DEFERRED (not implemented this session). Correct paths: Copilot → `.github/agents/*.md` + `.github/copilot-instructions.md`; OpenCode → `.opencode/agents/*.md` + `AGENTS.md`. Fix = make `_render_and_write` honor `config["target"]`.
- **Rationale:** It's a scaffold-contract change with blast radius (also `carter check` validates `<workspace>/agents/`, `carter update` shares the render path, getting-started.md tree, new test, existence-guards) and cannot be live-verified here — so recorded for deliberate implementation rather than rushed before a pause.
- **Alternatives considered:** Implement blind now (rejected — unverifiable contract change before pause); document-as-limitation only (rejected — current behavior is broken, not just undocumented).
- **Open decisions for the fix:** honor single `config["target"]` vs always-both; overwrite vs skip pre-existing `AGENTS.md`.
- **Tags:** architecture, scaffold, discovery, init, adr-0002



