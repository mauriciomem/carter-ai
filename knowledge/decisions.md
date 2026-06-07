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

## 2026-06-07 | Cross-platform install hardening (macOS + Linux)
- **Context:** A Fedora user hit `bash: carter: command not found` after `uv tool install`. Root cause was PATH (uv installs to ~/.local/bin, not always on PATH) — not Carter — but the docs wrongly claimed install "puts carter on your PATH". Audit also found vestigial prereqs and a fragile VS Code settings path.
- **Decision:** (1) Docs: correct the PATH claim, add `uv tool update-shell` + reload step, a "command not found" troubleshooting note, and the `./install.sh` PATH-free fallback (getting-started + README). (2) Drop `jq`/`terraform` from `check_prerequisites` — the installer uses neither (json via Python; terraform unrelated). (3) Harden `_vscode_settings_path`: detect VSCodium/Insiders/Flatpak variants, prefer an existing variant dir, and add `_vscode_detected` so `--mcp` SKIPS writing settings.json when no VS Code config dir exists (no phantom file).
- **Rationale:** The actual failure was a doc/UX gap, fixed first. Prereq/VS Code changes remove misleading warnings and silent no-ops on Linux (esp. Fedora Flatpak). Core installer was already platform-neutral (~/.copilot, ~/.config/opencode, ~/.carter) with one correct Darwin branch.
- **Alternatives considered:** Auto-add ~/.local/bin to PATH from the installer (rejected — too invasive, uv owns that via update-shell); keep jq/terraform as "optional" (rejected — they're not install-related at all).
- **Verified:** +8 tests (TestCrossPlatform 7, MCP-skip 1); suite 231→239. No behavior change under base_dir (tests green).
- **Tags:** install, cross-platform, linux, fedora, path, vscode, mcp

## 2026-06-07 | Phase 2 build-time agent generation ABANDONED (ADR-0002, Won't Do)
- **Context:** Phase 2 aimed to dedup the dual agent sources by generating static `agents/*.md` from the templates at build time, guarded by a CI `git diff --exit-code agents/` drift check.
- **Decision:** WON'T DO. The prerequisite check (render default config with agent_suffix='' vs current static files) showed all 7 agents differ by 79–178 BODY lines — not frontmatter (already reconciled), but two different agent *designs*: static has `<role>` expert-prose + explicit `<skills>`/`<mcp>` blocks (incl. this session's review-register voice); templates have `<identity>` + What you do/don't bullets + `<boundaries>` + Available Agents footer.
- **Rationale:** Static and template are two independently-authored designs sharing a name, NOT one artifact duplicated. Generating would overwrite all 7 shipped agents with the template design — a product change to every `carter install`, not a refactor. The drift risk phase 2 targeted is ALREADY covered by tests/test_parity.py (frontmatter, redaction categories, ops one-liner, modes, agent-set parity).
- **Alternatives considered:** Reconcile designs then generate (rejected now — a deliberate content project choosing/merging one canonical agent body for all 7, not currently justified); generate anyway (rejected — silently rewrites shipped content). 
- **Outcome:** ADR-0002 effectively complete. Dual-source kept; parity tests are the guardrail. No agent files changed.
- **Tags:** architecture, agents, build, generation, wont-do, adr-0002

## 2026-06-07 | carter init --target/--agent-suffix flags + narrator redaction guard (ADR-0002)
- **Context:** `carter init` had no way to set target/suffix without hand-editing carter.yaml (the `sed` workaround). And the recorded edge case (narrator enabled + redaction off → narrator with no redaction rules) had no guard.
- **Decision:** (1) Add `--target {copilot,opencode,all}` and `--agent-suffix` flags to `carter init`; they override config before it's persisted (so carter.yaml matches what was scaffolded), with eager validation (bad suffix/target exits non-zero). (2) Add `carter.scaffold.config_warnings(config)` — a pure function flagging the narrator/redaction gap — emitted by `carter init`, `update`, and `check` (non-fatal `⚠`).
- **Rationale:** Flags remove the YAML-edit friction for the common case; the warning surfaces the security-relevant gap at the three natural touchpoints without blocking (config-gating redaction is by design per ADR-0001).
- **Alternatives considered:** Make the redaction gap a hard error (rejected — redaction-off is a legitimate choice); only warn in check (rejected — init/update are where it's first introduced).
- **Verified:** end-to-end `carter init --target all --agent-suffix demo`; warning fires in update + check with redaction off; 10 new tests (TestConfigWarnings 3, TestInitFlags 7). Suite 221→231.
- **Tags:** cli, scaffold, init, redaction, warning, adr-0002

## 2026-06-07 | Configurable agent_suffix to distinguish workspace vs global agents (ADR-0002)
- **Context:** Manual `carter init` testing showed that with discovery fixed, a workspace with Carter ALSO installed globally shows two `carter-engineer` agents (global `~/.copilot/agents/` + workspace `.github/agents/`), indistinguishable in the picker.
- **Decision:** Add `agent_suffix` to carter.yaml (default `local`, empty = no suffix). Workspace renders suffix the filename AND every `carter-<role>` reference (routing table, agents footer, cross-refs, instructions) via a centralized transform in `carter.scaffold._apply_agent_suffix`, scoped to configured roles so skill names (carter-ops, carter-docs) are untouched. Global `carter install` unaffected (copies static plain-named files). `carter check`/`update` honor it.
- **Rationale:** User chose "configurable, default local" over fixed `-local` / workspace-name / precedence-only. Centralized transform avoids `{{ suffix }}` scattered across 6 templates and is safer (one tested function). Empty-suffix escape hatch subsumes the "keep names" option.
- **Alternatives considered:** Fixed `-local` suffix (less flexible); workspace-name suffix (needs sanitization); precedence-only/no rename (doesn't fix picker ambiguity); per-template `{{ suffix }}` interpolation (~20 error-prone edits incl. prose).
- **Verified:** end-to-end `carter init` → `.github/agents/carter-engineer-local.md` with `-local` routing; 10 TestAgentSuffix tests; no skill-name false positives.
- **Tags:** scaffold, agents, naming, agent_suffix, cli, adr-0002

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

## 2026-06-06 | Scaffold-discovery FIXED — render to per-target discovery paths (ADR-0002)
- **Context:** `carter init`/`update` wrote agents to `<workspace>/agents/` + instructions to `<workspace>/instructions/` — paths no tool discovers, so scaffolded agents never loaded. (Supersedes the "confirmed bug, fix deferred" entry below.)
- **Decision:** `_render_and_write` now honors `config["target"]` and writes discovery paths: copilot → `.github/agents/*.md` + `.github/copilot-instructions.md`; opencode → `.opencode/agents/*.md` + `AGENTS.md`; all → both. Carter-owned `carter-*` agents always (re)written (so `carter update` works); instruction files skip-if-exists (never clobber user content). `carter check` validates new paths; dry-run previews them.
- **Rationale:** Decisions chosen by user: (a) honor target (the field existed for this), (b) skip-if-exists for instructions (mirrors installer's AGENTS.md behavior). 6 TestRenderDiscovery tests added; getting-started.md updated.
- **Caveat:** Cannot live-verify VS Code/OpenCode actually load them (no runtime); output now lands in documented discovery paths — needs manual end-to-end confirmation.
- **Tags:** scaffold, discovery, init, cli, adr-0002

## 2026-06-06 | Scaffold-agent discovery is a confirmed bug (ADR-0002, fix deferred)
- **Context:** `carter init`/`_render_and_write` writes agents to `<workspace>/agents/` and instructions to `<workspace>/instructions/`, but no tool discovers those paths. `config["target"]` exists (default copilot) yet is ignored. yui-soul already renders to the correct paths.
- **Decision:** Investigated and confirmed it's a bug; fix DESIGNED but DEFERRED (not implemented this session). Correct paths: Copilot → `.github/agents/*.md` + `.github/copilot-instructions.md`; OpenCode → `.opencode/agents/*.md` + `AGENTS.md`. Fix = make `_render_and_write` honor `config["target"]`.
- **Rationale:** It's a scaffold-contract change with blast radius (also `carter check` validates `<workspace>/agents/`, `carter update` shares the render path, getting-started.md tree, new test, existence-guards) and cannot be live-verified here — so recorded for deliberate implementation rather than rushed before a pause.
- **Alternatives considered:** Implement blind now (rejected — unverifiable contract change before pause); document-as-limitation only (rejected — current behavior is broken, not just undocumented).
- **Open decisions for the fix:** honor single `config["target"]` vs always-both; overwrite vs skip pre-existing `AGENTS.md`.
- **Tags:** architecture, scaffold, discovery, init, adr-0002



