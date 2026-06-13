# Carter v2 — Implementation Plan

> Adopting the best of Yui Soul's architecture while preserving Carter's identity, pragmatism, and existing value.

**Source**: yui-soul assessment (archived planning note)
**Status**: Draft
**Date**: 2026-05-28

---

## Table of Contents

1. [Design Questions & Decisions](#1-design-questions--decisions)
2. [Architectural Principles](#2-architectural-principles)
3. [Gap Analysis — Carter vs. Yui](#3-gap-analysis--carter-vs-yui)
4. [Implementation Phases](#4-implementation-phases)
5. [Phase 0: Foundation — Instruction File Restructuring](#5-phase-0-foundation--instruction-file-restructuring)
6. [Phase 1: Session Bootstrap & Knowledge Architecture](#6-phase-1-session-bootstrap--knowledge-architecture)
7. [Phase 2: Agent Boundary Enforcement](#7-phase-2-agent-boundary-enforcement)
8. [Phase 3: Plan System Overhaul](#8-phase-3-plan-system-overhaul)
9. [Phase 4: Quality Gates & Audit Cycles](#9-phase-4-quality-gates--audit-cycles)
10. [Phase 5: New Specialized Agents](#10-phase-5-new-specialized-agents)
11. [Phase 6: Tool Preference & Parallel Execution](#11-phase-6-tool-preference--parallel-execution)
12. [Risk Register](#12-risk-register)
13. [Anti-Patterns — What NOT to Adopt](#13-anti-patterns--what-not-to-adopt)
14. [Migration Strategy](#14-migration-strategy)
15. [Success Metrics](#15-success-metrics)
16. [Open Questions](#16-open-questions)

---

## 1. Design Questions & Decisions

Before implementing, these questions must be resolved. Each has a recommended answer based on analysis.

### Q1: Should Carter adopt the "director never implements" model?

**Yui's approach**: Yui NEVER writes code, tests, docs, or plans. All work delegated.

**Carter's current approach**: carter-maestro routes but CAN answer trivially. Specialists handle domain work.

**Decision**: **Partial adoption.** Carter Maestro continues to answer trivial questions directly (a strength). But for any task that involves file creation/modification, enforce delegation. Add explicit "never do yourself" rules to maestro.

**Rationale**: Yui's extreme purity causes overhead for simple questions ("What's the capital of France?" still requires `ask_user`). Carter's pragmatic "direct answer for trivial" is better UX. But the delegation enforcement for substantive work is worth adopting.

**Edge cases**:
- What counts as "trivial"? → Factual questions, simple clarifications, yes/no answers, tool outputs. If it requires creating/editing a file → delegate.
- What about multi-step clarification before delegating? → Maestro can do analysis and ask questions, but once implementation starts, delegate.

---

### Q2: Should Carter use filesystem-as-memory or continue with the platform memory tool?

**Yui's approach**: `.plans/`, `.knowledge/`, `.rfcs/` as local git repos. No external tools needed.

**Carter's current approach**: Platform memory tool (`/memories/`), `~/.carter/memories/`, and `~/.copilot/knowledge/`.

**Decision**: **Hybrid.** Keep platform memory for volatile/session-scoped notes (it's convenient). Add `.carter-state/` in workspace root for persistent structured state (plans, knowledge) that survives compaction. Do NOT require git repos for state (overhead for casual use).

**Rationale**: Carter operates across many different workspaces (some temporary). A mandatory git repo setup is friction. But structured filesystem state for active work (plans, knowledge) is clearly superior to volatile memory alone.

**Edge cases**:
- What if the workspace IS a git repo? → `.carter-state/` gets added to `.gitignore` by default.
- What about workspaces that already have Carter installed? → Migration path: if `~/.copilot/knowledge/` exists and `.carter-state/` doesn't, offer to migrate.
- Multi-root workspaces? → `.carter-state/` lives in the active workspace root (the one being worked in).
- Temporary scratch workspaces? → `.carter-state/` is optional. Carter still works without it (fallback to platform memory only).

---

### Q3: Should Carter adopt XML blocks in instruction files?

**Yui's finding**: "XML blocks over markdown headers — XML tags are more precisely parseable than markdown headers for instruction files."

**Carter's current approach**: Markdown headers + some XML (`<role>`, `<skills>`, `<routing>`).

**Decision**: **Yes — standardize all agent/skill files on XML blocks.** Carter already uses some XML blocks (`<role>`, `<routing>`, `<skills>`). Extend this to a consistent, required set.

**Rationale**: The agent files already partially use XML. Standardizing eliminates ambiguity about where one section ends and another begins. LLMs parse XML blocks more reliably than markdown heading hierarchies.

**Edge cases**:
- Existing skills use `<objective>`, `<workflow>`, `<guidelines>` — these are already XML. No change needed for skills.
- Agent files need refactoring from mixed markdown/XML to pure XML blocks.
- What XML blocks should be required vs. optional? → See Phase 0 spec below.

---

### Q4: How should "lessons-learned" permanence work?

**Yui's approach**: `lessons-learned.md` is append-only, never deleted, survives workspace ports.

**Carter's current approach**: `~/.copilot/knowledge/mistakes.md` exists but is mutable and currently empty.

**Decision**: **Adopt append-only semantics for `mistakes.md`.** Rename to `lessons-learned.md` (clearer). Add a header comment: "PERMANENT FILE — append only, never remove entries." Entries can be clarified/updated but never deleted.

**Rationale**: Mistakes and universal truths are the highest-value knowledge. Deleting them means repeating them. The cost of a growing file is low compared to repeating costly errors.

**Edge cases**:
- What if an entry is proven wrong? → Mark it as `[SUPERSEDED by YYYY-MM-DD entry below]` — don't delete, annotate.
- What if the file gets too long? → Organize by category with collapsible sections. Consider archiving very old entries (>1 year) to `lessons-learned-archive.md`.
- What about workspace-specific vs. universal lessons? → Add a `Scope: universal | workspace` tag. Universal entries always port; workspace entries only port if relevant.

---

### Q5: Should Carter add an RFC system?

**Yui's approach**: Full RFC lifecycle with status folders, reviews, and plan linkage.

**Carter's current approach**: No formal design proposal process. ADRs exist but are post-hoc documentation.

**Decision**: **Adopt a lightweight RFC system** — but simpler than Yui's. Single-file RFCs in `docs/rfcs/` (not status folders — too much ceremony). Status tracked in frontmatter.

**Rationale**: Carter already has ADRs for recording decisions. RFCs add the missing "propose and review BEFORE building" step. But Yui's 4-folder hierarchy is over-engineered for one user (Carter's primary context). A single folder with frontmatter status is sufficient.

**Edge cases**:
- When does something need an RFC vs. just starting? → If it affects >3 files, introduces a new agent/skill, or changes Carter's architecture → RFC. Otherwise → just plan and do it.
- Who reviews? → carter-architect reviews all RFCs. carter-engineer reviews if code changes are involved. User is final approver.
- How does RFC link to plan? → `plan_from_rfc: RFC-NNN` field in plan frontmatter.

---

### Q6: Parallel vs. sequential agent execution?

**Yui's approach**: "Parallel execution is mandatory. If Agent A and Agent B have no dependency between them, invoke both simultaneously."

**Carter's current approach**: Sequential chaining ("execute agents sequentially and pass context between them").

**Decision**: **Adopt parallel-first for independent work.** Update maestro's dispatch rules: if two tasks have no data dependency, launch both simultaneously. Sequential only when output of A is input to B.

**Rationale**: Sequential execution wastes time when tasks are independent. A security review and a test-quality review can happen in parallel. An architecture design and a code implementation cannot.

**Edge cases**:
- How does maestro determine dependency? → Explicit: if the prompt for Agent B requires the output of Agent A, they're dependent. If both can be given complete context from the user's request alone, they're independent.
- What if parallel agents produce conflicting recommendations? → Maestro resolves conflicts, presents both to user if significant.
- Platform limitations? → VS Code Copilot supports parallel subagent calls. Verify OpenCode does too.

---

### Q7: Should Carter have a formal session bootstrap?

**Yui's approach**: Deterministic 5-step protocol at every session start.

**Carter's current approach**: No formal protocol. Ad-hoc "consult memories before proposing solutions."

**Decision**: **Yes — add session bootstrap to maestro.** At session start (detected by absence of prior context): read active plans → read relevant knowledge → report status. Don't ask "what should we work on?" if there's active work.

**Rationale**: The #1 cost of context loss is re-explaining what we were doing. A bootstrap protocol eliminates this entirely.

**Edge cases**:
- How to detect "session start"? → No prior messages in conversation. Or user explicitly says "catch me up" / "where were we?"
- What if no active plans exist? → Skip to normal greeting. Don't manufacture work.
- What if multiple active plans exist? → List them, ask which to focus on.
- Performance concern? → Reading 2-3 files at session start is negligible. Don't over-read.

---

### Q8: Model assignment per agent?

**Yui's approach**: Opus for architect (Taku) and reviewer (Sho). Sonnet for everyone else.

**Carter's current approach**: No model differentiation. Relies on whatever model the platform assigns.

**Decision**: **Add `model` recommendation to agent frontmatter** — but as advisory, not enforced (platform decides). Add a comment like `# Recommended: claude-opus-4.6 for complex reasoning tasks`.

**Rationale**: Some tasks genuinely benefit from more capable models (architecture, code review). But Carter is platform-agnostic — it works on VS Code Copilot, OpenCode, etc. The platform controls model selection. Carter can recommend but not enforce.

**Edge cases**:
- VS Code Copilot: respects `model` frontmatter in agent files? → Verify. If not, recommendation is documentation-only.
- Cost implications? → User decides. Recommendation is advisory.

---

### Q9: What happens to the existing `knowledge/` directory?

**Carter's current state**: `knowledge/` in repo root with empty template files (`decisions.md`, `mistakes.md`, `patterns.md`, etc.)

**Decision**: **Keep `knowledge/` as the curated reference layer.** It already serves the right purpose — curated, long-term knowledge. Add the permanence rules from Yui for `lessons-learned.md`. The new `.carter-state/` directory is for active operational state (plans, session context), not curated knowledge.

**Separation of concerns**:
- `knowledge/` → Curated reference (decisions, patterns, lessons) — managed by `carter-distill`
- `.carter-state/plans/` → Active work state (what's in progress, what's done)
- `.carter-state/sessions/` → Session checkpoints for recovery
- `/memories/` → Volatile platform memory for quick notes

---

### Q10: Knowledge capture triggers — when should Carter automatically record learnings?

**Yui's approach**: 6 explicit triggers (task completion, failure, plan transition, new tool, workaround, significant debugging).

**Carter's current approach**: Manual only — `carter-distill` runs on-demand, `carter-mistakes` records on request.

**Decision**: **Add systematic triggers to maestro + agents.** After completing a multi-step task, maestro checks: "Was there a lesson worth recording?" If yes, suggest distill. Don't auto-record — suggest and let user confirm.

**Rationale**: Auto-recording creates noise. But systematic suggestions at natural checkpoints (plan completion, debugging resolution, error recovery) ensures knowledge isn't lost.

**Trigger points**:
1. Plan marked complete → "Should I capture any learnings from this?"
2. Debugging session resolved → "Record this as a lesson?"
3. Unexpected failure recovered → "Add this to known issues?"
4. New tool/pattern discovered → "Document this in knowledge?"
5. User corrects Carter → "Should I record this correction?"

---

## 2. Architectural Principles

### Adopted from Yui (filtered through Carter's values):

1. **Structured state beats volatile memory** — Use filesystem for anything that should survive compaction.
2. **Delegation boundaries are explicit and enforced** — "Never do yourself" rules prevent role confusion.
3. **Plans are recovery mechanisms** — If a session is interrupted, the plan tells us exactly where we left off.
4. **Knowledge compounds** — Every session should leave the system smarter for the next one.
5. **Parallel over serial** — Independent work runs concurrently.
6. **Verify, don't claim** — Nothing is done until confirmed on disk, in CI, or in production.
7. **Time awareness** — Always verify against current sources. Training data may be stale.

### Preserved from Carter (not changing):

1. **Pragmatism over purity** — Trivial requests get direct answers. No bureaucracy for simple tasks.
2. **Security-first** — OWASP Top 10 awareness in every code review and implementation.
3. **Test before implement** — TDD workflow is already Carter's default.
4. **Ask before acting on ambiguity** — Don't guess when you can clarify.
5. **Clean code as a habit** — Remove dead code, reuse abstractions, leave things cleaner.

### Explicitly NOT adopting:

1. ~~"Every response must end with ask_user"~~ — Too rigid. Carter offers next steps naturally.
2. ~~13 agents for everything~~ — Carter keeps 5 core agents + adds only proven-needed specialists.
3. ~~RFC required for ALL new ideas~~ — Only for architectural changes affecting >3 files.
4. ~~No trivial work exception for plans~~ — Small tasks don't need plans. Carter stays pragmatic.
5. ~~Multiple audit rounds until 3 clean passes~~ — One thorough review is sufficient for most work.

---

## 3. Gap Analysis — Carter vs. Yui

| Capability | Carter Today | Yui Today | Gap Severity | Phase |
|-----------|-------------|-----------|-------------|-------|
| Instruction file structure | Mixed markdown/XML | Consistent 11 XML blocks | Medium | 0 |
| Session bootstrap | None (ad-hoc) | Deterministic 5-step | High | 1 |
| Knowledge architecture | Empty template files | Living git-tracked docs | High | 1 |
| Agent boundaries | Advisory routing table | Enforced "never do yourself" | High | 2 |
| Self-check before acting | None | Violation self-check | Medium | 2 |
| Plan system | carter-plan skill (output format) | Full lifecycle (draft/wip/done) | High | 3 |
| Plan recovery | None | Plans ARE the recovery mechanism | High | 3 |
| `must_haves` verification | None | Objective done criteria per plan | High | 3 |
| Quality gate before push | None | Multi-agent parallel audit | Medium | 4 |
| Monitoring agent | None | Miru (adaptive polling) | Low | 5 |
| Debugging agent | None (carter-engineer handles) | Sui (scientific method, evidence gates) | Medium | 5 |
| Knowledge agent | carter-distill (manual) | Chi (triggered, systematic) | Medium | 5 |
| Tool preference hierarchy | None (uses whatever) | MCP > CLI > scripts | Low | 6 |
| Parallel execution | Sequential only | Mandatory parallel for independent | Medium | 6 |
| Time awareness | None explicit | All agents have time_awareness block | Low | 6 |
| RFC system | None (ADRs exist post-hoc) | Full lifecycle | Low | 3 |

---

## 4. Implementation Phases

```
Phase 0 ──────── Phase 1 ──────── Phase 2 ──────── Phase 3 ──────── Phase 4 ──────── Phase 5 ──────── Phase 6
Foundation       Knowledge        Boundaries       Plans            Quality          New Agents       Polish
(1-2 days)       (2-3 days)       (1-2 days)       (3-5 days)       (2-3 days)       (3-5 days)       (1-2 days)
```

**Dependencies**:
- Phase 1 depends on Phase 0 (needs XML structure in place)
- Phase 2 depends on Phase 0 (agent files must be restructured first)
- Phase 3 depends on Phase 1 + 2 (needs knowledge system and boundaries)
- Phase 4 depends on Phase 3 (audits reference plans)
- Phase 5 depends on Phase 2 (new agents must follow boundary patterns)
- Phase 6 is independent (can run in parallel with 4 or 5)

---

## 5. Phase 0: Foundation — Instruction File Restructuring

### Objective

Standardize all agent and instruction files on consistent XML blocks. Establish the structural foundation that all subsequent phases build on.

### Changes Required

#### 5.1 Agent File Standard

Every agent file (`agents/carter-*.md`) must contain these XML blocks in order:

```markdown
---
[YAML frontmatter — name, description, mode, temperature, model recommendation]
---

<identity>
Who you are. Personality traits. What you are / are not.
</identity>

<role>
What you do (bullet list). What you don't do (bullet list with delegation targets).
</role>

<boundaries>
"Delegate when:" triggers.
"Never do yourself:" forbidden operations.
Self-check instruction.
</boundaries>

<context_loading>
What to read before acting (knowledge files, existing code, etc.)
</context_loading>

<skills>
Available skills with descriptions.
</skills>

<tools>
Available MCP tools and access levels.
</tools>
```

**Required blocks**: `<identity>`, `<role>`, `<boundaries>`
**Optional blocks**: `<context_loading>`, `<skills>`, `<tools>`

#### 5.2 Maestro-Specific Blocks

Carter Maestro additionally gets:

```markdown
<routing>
Agent routing table and dispatch rules.
</routing>

<session_bootstrap>
What to do at session start.
</session_bootstrap>

<philosophy>
Work principles (adopted from Yui + Carter originals).
</philosophy>

<interaction_rules>
Communication rules, autonomy rules, when to ask vs. act.
</interaction_rules>
```

#### 5.3 Global Instructions Update

`instructions/copilot-instructions.md` gets these new sections:

```markdown
<time_awareness>
The current year is 2026. Verify APIs, versions, and best practices against
current sources. Training data may be stale.
</time_awareness>

<tool_preference>
When multiple tools can accomplish the same task:
1. MCP tools (structured, typed, reliable) — use when available
2. CLI tools (gh, terraform, kubectl) — when no MCP equivalent
3. Raw scripts (curl, python) — last resort only
</tool_preference>
```

#### 5.4 Files to Modify

| File | Change Type |
|------|-------------|
| `agents/carter-maestro.md` | Major restructure — add all new blocks |
| `agents/carter-architect.md` | Add `<identity>`, `<boundaries>`, `<context_loading>` |
| `agents/carter-engineer.md` | Add `<identity>`, `<boundaries>`, `<context_loading>` |
| `agents/carter-devops.md` | Add `<identity>`, `<boundaries>`, `<context_loading>` |
| `agents/carter-pm.md` | Add `<identity>`, `<boundaries>`, `<context_loading>` |
| `agents/carter-learner.md` | Add `<identity>`, `<boundaries>`, `<context_loading>` |
| `instructions/copilot-instructions.md` | Add `<time_awareness>`, `<tool_preference>` |

#### 5.5 Acceptance Criteria

- [ ] All 6 agent files use consistent XML block structure
- [ ] Every agent has `<identity>`, `<role>`, `<boundaries>` blocks
- [ ] `<boundaries>` block contains "Delegate when" and "Never do yourself" lists
- [ ] Global instructions include `<time_awareness>` and `<tool_preference>`
- [ ] No functional behavior change yet — this is structural only

#### 5.6 Edge Cases & Questions

- **Q**: Should skill files also be restructured? → **A**: No. Skills already use XML (`<objective>`, `<workflow>`, etc.) consistently. Leave them.
- **Q**: What about the `mcp` section in current agents? → **A**: Rename to `<tools>` XML block.
- **Q**: Does `temperature` belong in frontmatter or XML? → **A**: Frontmatter (it's platform metadata, not instruction content).
- **Q**: What if an agent has no boundaries to define? → **A**: Every agent has boundaries. If unclear, the boundary is "only act within your declared expertise."

---

## 6. Phase 1: Session Bootstrap & Knowledge Architecture

### Objective

Implement the session bootstrap protocol and restructure knowledge for compaction-proof recovery.

### 6.1 Session Bootstrap Protocol

Add to `agents/carter-maestro.md` inside the new `<session_bootstrap>` block:

```markdown
<session_bootstrap>

## Session Start Protocol

At the start of every new session (no prior messages or user says "catch me up"):

1. **Check active plans**: Read `.carter-state/plans/active/` for plans in progress.
   - If found → summarize current status and next actionable step.
   - If multiple → list them, ask which to focus on.
2. **Check pending items**: Read `.carter-state/pending.md` for items awaiting user action.
3. **Read relevant knowledge**: Scan `knowledge/` files relevant to current context.
4. **Report and proceed**: Present status concisely, then proceed to next step or await instruction.

**Do NOT ask "what should we work on?" if active plans exist.** Infer from state and confirm.

**If no state exists**: Greet normally and await instruction.

</session_bootstrap>
```

### 6.2 Knowledge Architecture Redesign

**Current state** (empty templates in `knowledge/`):
```
knowledge/
├── debugging.md         ← empty template
├── decisions.md         ← empty template
├── infrastructure.md    ← empty template
├── mistakes.md          ← empty template
├── patterns.md          ← empty template
└── project-history.md   ← empty template
```

**New state**:
```
knowledge/
├── lessons-learned.md   ← PERMANENT, append-only (renamed from mistakes.md)
├── decisions.md         ← Architecture decisions (keep)
├── patterns.md          ← Recurring patterns (keep)
├── tools.md             ← NEW: available tools, auth methods, configs
├── gotchas.md           ← NEW: known issues + workarounds
└── project-history.md   ← Keep
```

**Changes**:
- `mistakes.md` → renamed to `lessons-learned.md` with append-only header
- `debugging.md` → merged into `lessons-learned.md` (debugging lessons ARE lessons)
- `infrastructure.md` → merged into `tools.md` (infra patterns are tool/config knowledge)
- `tools.md` → NEW: documents available CLIs, MCP tools, auth methods
- `gotchas.md` → NEW: workspace-specific known issues

**File headers**:

```markdown
# Lessons Learned

> **⚠️ PERMANENT FILE — append only, never remove entries.**
> These are universal truths discovered through experience.
> They apply regardless of workspace or project.
> Entries can be annotated with [SUPERSEDED] but never deleted.

## Categories: Agent behavior | Development patterns | Tool-specific | Security
```

```markdown
# Known Issues & Workarounds (Gotchas)

> Workspace-specific issues and their workarounds.
> Entries can be removed when the underlying issue is fixed.
```

```markdown
# Available Tools

> Tools, CLIs, MCP servers, and auth methods available in this workspace.
> Updated as tools are discovered or configured.

## Always Available
| Tool | Purpose | Auth |
|------|---------|------|
```

### 6.3 `.carter-state/` Directory

**Purpose**: Active operational state that survives session compaction.

```
.carter-state/
├── plans/
│   ├── active/          ← Plans currently being worked on
│   ├── completed/       ← Finished plans (for reference)
│   └── index.md         ← Plan index table
├── sessions/
│   └── checkpoint.md    ← Last session's final state (auto-updated)
└── pending.md           ← Items awaiting user action
```

**Creation**: Carter creates `.carter-state/` when first plan is created. Not pre-created.
**Gitignore**: Add `.carter-state/` to workspace `.gitignore` (it's local state, not project code).

### 6.4 Knowledge Capture Triggers

Add to `agents/carter-maestro.md` in `<interaction_rules>`:

```markdown
## Knowledge Capture Triggers

After these events, ask the user if there's a lesson worth recording:

1. **Plan completed** → "Any learnings from this work worth capturing?"
2. **Debugging session resolved** (>10 min on one issue) → "Record this as a gotcha?"
3. **Unexpected failure recovered** → "Add this to known issues?"
4. **User corrects Carter** → "Should I record this correction in lessons-learned?"
5. **New tool/pattern discovered** → "Document this in tools.md?"

**Rules:**
- Never auto-record without user confirmation.
- Keep the suggestion to one sentence — don't interrupt flow.
- If user says no, move on immediately.
```

### 6.5 Acceptance Criteria

- [ ] Session bootstrap protocol defined and functional in maestro
- [ ] `knowledge/` restructured with proper files and headers
- [ ] `lessons-learned.md` has append-only semantics documented
- [ ] `tools.md` and `gotchas.md` created with proper structure
- [ ] `.carter-state/` directory spec defined (created on first use)
- [ ] Knowledge capture triggers documented in maestro
- [ ] Migration path from old `mistakes.md` → `lessons-learned.md` documented

### 6.6 Edge Cases

- **What if user doesn't want `.carter-state/`?** → It's created on first plan creation. If user never creates plans, it doesn't exist. Zero friction for casual use.
- **What if `knowledge/` already has entries in `mistakes.md`?** → Move them to `lessons-learned.md` during migration.
- **Session bootstrap with empty state?** → Skip to normal greeting. Bootstrap is only useful when state exists.
- **What if `.carter-state/plans/active/` has stale plans?** → Plans older than 30 days without updates get flagged: "This plan hasn't been touched in 30 days. Still active?"
- **Concurrent plans in different workspaces?** → Each workspace has its own `.carter-state/`. No cross-workspace contamination.

---

## 7. Phase 2: Agent Boundary Enforcement

### Objective

Transform advisory routing into enforced delegation boundaries. Each agent knows exactly what it should and should NOT do.

### 7.1 Boundary Definitions

#### Carter Maestro

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- Trivial factual questions (no file creation needed)
- Routing decisions
- Multi-agent coordination
- Session bootstrap
- Knowledge capture suggestions

**Delegate to carter-architect when:**
- System design needed
- Architecture decisions
- Trade-off analysis
- Diagram creation
- ADR creation

**Delegate to carter-engineer when:**
- Code needs to be written or modified
- Tests need to be written
- Code review requested
- Bug fix needed
- Refactoring

**Delegate to carter-devops when:**
- Pipeline/CI configuration
- Terraform/IaC work
- Container/deployment work
- Git workflow operations (via carter-ops)

**Delegate to carter-pm when:**
- Plan creation needed
- Risk assessment
- Roadmap design
- Status reporting

**Delegate to carter-learner when:**
- Explanation requested
- Research needed
- Documentation of concepts

**Self-check before acting:**
Before performing any task, verify: "Does this belong to a specialist?" If you are about to write code, create a plan, design a system, or write documentation — STOP. Delegate first.

</boundaries>
```

#### Carter Engineer

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- Write application code
- Write tests (TDD red+green+refactor)
- Code review
- Debug and fix bugs
- Refactor code

**Never do yourself:**
- Design system architecture (→ carter-architect)
- Create project plans (→ carter-pm)
- Write/modify CI pipelines (→ carter-devops)
- Write user-facing documentation beyond code comments (→ carter-learner)
- Make deployment decisions (→ carter-devops)

**Context loading before acting:**
1. Read `knowledge/gotchas.md` — known issues affecting implementation
2. Read `knowledge/patterns.md` — established patterns to follow
3. Read existing tests — match conventions

</boundaries>
```

#### Carter Architect

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- System design and decomposition
- API contract definition
- Architecture decisions with rationale
- Trade-off analysis
- Diagram creation
- RFC authoring

**Never do yourself:**
- Write implementation code (→ carter-engineer)
- Write tests (→ carter-engineer)
- Configure CI/CD (→ carter-devops)
- Create project plans (→ carter-pm)
- Manage Terraform (→ carter-devops)

**Context loading before acting:**
1. Read `knowledge/decisions.md` — prior architecture decisions
2. Read `knowledge/patterns.md` — established patterns
3. Read existing architecture — design consistently with what exists

</boundaries>
```

#### Carter DevOps

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- CI/CD pipeline configuration
- Terraform/IaC authoring and review
- Container configuration
- Deployment automation
- Git workflow operations
- Dependency version pinning

**Never do yourself:**
- Write application logic (→ carter-engineer)
- Design system architecture (→ carter-architect)
- Create project plans (→ carter-pm)
- Write user documentation (→ carter-learner)

**Context loading before acting:**
1. Read `knowledge/tools.md` — available tools and auth methods
2. Read `knowledge/gotchas.md` — known CI/infra issues
3. Inspect repo structure — discover existing CI/IaC patterns

</boundaries>
```

#### Carter PM

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- Create project plans and WBS
- Risk assessment
- Milestone identification
- Status reporting
- Sprint/roadmap design

**Never do yourself:**
- Write code (→ carter-engineer)
- Design architecture (→ carter-architect)
- Configure infrastructure (→ carter-devops)
- Write technical documentation (→ carter-learner)

**Context loading before acting:**
1. Read `.carter-state/plans/active/` — existing plans
2. Read `knowledge/project-history.md` — prior projects for estimation
3. Read `knowledge/decisions.md` — constraints that affect planning

</boundaries>
```

#### Carter Learner

```markdown
<boundaries>

## Delegation Boundaries

**Do yourself:**
- Explain complex topics
- Research documentation
- Record mistakes and lessons
- Create learning materials
- Summarize findings

**Never do yourself:**
- Write production code (→ carter-engineer)
- Design systems (→ carter-architect)
- Make planning decisions (→ carter-pm)
- Configure infrastructure (→ carter-devops)

**Context loading before acting:**
1. Read `knowledge/lessons-learned.md` — prior learnings on topic
2. Read `knowledge/patterns.md` — established patterns
3. Check official documentation — cite sources

</boundaries>
```

### 7.2 Violation Self-Check

Add to every agent's `<boundaries>` block:

```markdown
**Self-check before acting:** Before performing any task, verify it falls within your "Do yourself" list above. If you're about to perform work that belongs to another agent, STOP and recommend delegation to the appropriate specialist.
```

### 7.3 Acceptance Criteria

- [ ] All 6 agents have explicit `<boundaries>` blocks
- [ ] Each boundary block has "Do yourself", "Never do yourself", and "Context loading" sections
- [ ] Each "Never do yourself" item names the delegation target
- [ ] Self-check instruction present in all agents
- [ ] Maestro has comprehensive delegation triggers for all 5 specialists
- [ ] No functional behavior change in routing (boundaries formalize existing behavior)

### 7.4 Edge Cases

- **What if a task genuinely spans boundaries?** → Maestro coordinates. Agent A does its part, hands off context, Agent B continues. Boundaries are about individual agent scope, not task scope.
- **What if an agent discovers work outside its boundary mid-task?** → Complete its own work, then recommend: "This also needs [X agent] for [reason]."
- **What if context loading files don't exist yet?** → Skip gracefully. Don't fail because `gotchas.md` is empty.
- **What if the user explicitly asks an agent to work outside its boundary?** → Agent acknowledges the request but recommends the specialist: "I can attempt this, but carter-engineer is better suited. Want me to delegate?"

---

## 8. Phase 3: Plan System Overhaul

### Objective

Transform carter-pm's plan output from a static document format into a living, stateful plan system that enables session recovery.

### 8.1 Plan Lifecycle

```
Proposed → Active → In Review → Completed
                ↘ Stalled (>30 days without update)
```

**No separate folders.** Status tracked in frontmatter. Plans live in `.carter-state/plans/active/` while active, moved to `completed/` when done.

### 8.2 Plan Structure

```
.carter-state/plans/
├── active/
│   └── 001-feature-name/
│       ├── README.md          ← Plan overview + steps table + must_haves
│       ├── step-01.md         ← First step details
│       ├── step-02.md         ← Second step details
│       └── step-03.md         ← Third step details
├── completed/
│   └── 001-feature-name/     ← Moved here when done
└── index.md                   ← Active plans list
```

### 8.3 Plan README Template

```markdown
---
id: "001-feature-name"
status: active
created: 2026-05-28
last_updated: 2026-05-28
rfc: null                      # Optional: RFC-NNN if this came from an RFC
push_policy: manual            # manual | auto
tags: []
repos: []
---

# Plan: Feature Name

## Objective
What this plan achieves in one paragraph.

## Must-Haves
These are the objective verification criteria. The plan is not done until ALL are true:

- [ ] [Observable behavior or artifact that must exist]
- [ ] [Another verifiable outcome]
- [ ] [Test that must pass]

## Steps

| # | Step | File | Status |
|---|------|------|--------|
| 1 | First step | [step-01.md](step-01.md) | ⬜ pending |
| 2 | Second step | [step-02.md](step-02.md) | ⬜ pending |
| 3 | Third step | [step-03.md](step-03.md) | ⬜ pending |

## Decisions
| # | Decision | Outcome |
|---|----------|---------|
| D1 | ... | ✅ ... |

## Notes
[Running notes, blockers, context]
```

### 8.4 Step File Template

```markdown
---
step: 1
status: pending              # pending | in-progress | done | blocked
depends_on: []               # Step numbers this depends on
files_modified: []           # Filled in after completion
---

# Step 1: Step Title

## Goal
What this step achieves.

## Tasks
- [ ] Task 1 description
- [ ] Task 2 description
- [ ] Task 3 description

## Done Criteria
How to verify this step is complete:
- [ ] [Specific, verifiable criterion]
- [ ] [Another verifiable criterion]

## Notes
[Context, decisions made during execution]
```

### 8.5 Plan as Recovery Mechanism

Add to `<session_bootstrap>`:

```markdown
When an active plan exists, recovery works as follows:
1. Read the plan README — understand objective and must_haves
2. Read the steps table — identify which steps are done/pending
3. Read the current step file — understand what's in progress
4. Report: "We were working on [plan name], step [N]: [title]. [Status]. Ready to continue?"
```

### 8.6 `must_haves` Concept

Adopted from Yui's plan frontmatter. Every plan has objective, verifiable criteria:

```yaml
must_haves:
  - "All tests pass for the new auth module"
  - "API endpoint responds with correct schema at /api/v1/auth"
  - "Documentation updated in docs/auth.md"
```

**Enforcement**: Plan cannot be marked "completed" unless all must_haves are checked off. Carter PM verifies before moving to completed.

### 8.7 RFC Integration (Lightweight)

```
docs/rfcs/
├── RFC-001-title.md
├── RFC-002-title.md
└── index.md
```

RFC template:
```markdown
---
id: RFC-001
status: draft                 # draft | review | approved | rejected
author: [name]
created: 2026-05-28
decided: null
plan_id: null                 # Links to plan if approved
---

# RFC-001: Title

## Summary
One paragraph.

## Problem
What's wrong or missing.

## Proposal
What to build/change.

## Alternatives Considered
| Option | Pros | Cons |
|--------|------|------|

## Decision
[Filled after review]
```

**When to create RFC**: Changes affecting >3 files, new agents/skills, architecture changes.

### 8.8 Plan Skill Update

`skills/carter-plan/SKILL.md` needs updating to produce plans in the new `.carter-state/plans/` structure instead of just outputting markdown.

**Key changes**:
- Output goes to `.carter-state/plans/active/<id>/` directory
- Creates README.md + step files
- Updates `index.md`
- Includes `must_haves` in every plan

### 8.9 Acceptance Criteria

- [ ] `.carter-state/plans/` structure defined and documented
- [ ] Plan README template includes `must_haves`
- [ ] Step file template includes done criteria
- [ ] Plan lifecycle (proposed → active → completed) works
- [ ] Session bootstrap can read and report plan status
- [ ] carter-pm creates plans in new structure
- [ ] Plans enable session recovery (read plan → know where we are)
- [ ] RFC system exists in `docs/rfcs/` with simple lifecycle
- [ ] `must_haves` block is mandatory for every plan

### 8.10 Edge Cases

- **What if user doesn't want the ceremony of a plan?** → Plans are for multi-step work (>2 steps). Single-step tasks don't need plans. Carter-maestro judges.
- **What about plans for external work (Jira tickets)?** → Plan README can reference: `external_tracker: JIRA-123`. The plan is the local execution state; Jira is the stakeholder-facing tracker.
- **What if a plan step turns out to be unnecessary?** → Mark as `skipped` in status. Don't delete — it's decision history.
- **What if must_haves change mid-plan?** → Update them. Add a note in plan's "Decisions" table: "D2: Changed must_have X because..."
- **What if a plan is abandoned?** → Status: `abandoned` with note explaining why. Don't delete.
- **Nested plans (plan within a plan)?** → Don't. If a step is complex enough to be its own plan, split it out as a separate plan with a `depends_on: "001-parent-plan"` reference.

---

## 9. Phase 4: Quality Gates & Audit Cycles

### Objective

Add structured review before code leaves the local machine. Lighter than Yui's "repeat until 3 clean rounds" but more rigorous than "no review at all."

### 9.1 Quality Gate Definition

**When triggered**: Before any push or PR creation that includes code changes.

**Process**:
1. Maestro identifies the scope of changes (files modified)
2. Maestro delegates review in parallel:
   - carter-engineer: code quality, test coverage, correctness
   - carter-architect: design patterns, consistency (if >5 files changed)
   - Security check: OWASP concerns, secrets, input validation (always)
3. Collect findings, present to user
4. If blocking findings exist → fix and re-review
5. If clean or only minor findings → proceed to push/PR

**Key difference from Yui**: ONE review round. If blocking issues are found, fix them and do ONE more review. No infinite loops.

### 9.2 Trigger Conditions

| Condition | Action |
|-----------|--------|
| Code push with <5 files changed | carter-engineer review only |
| Code push with 5-15 files changed | carter-engineer + carter-architect |
| Code push with security-relevant changes | Always include security check |
| Documentation-only push | No review gate (too light) |
| Infrastructure-only push | carter-devops review |
| Plan says `push_policy: auto` | Skip gate (user opted out) |

### 9.3 Review Output Format

```markdown
## Quality Gate: [Plan/Branch Name]

### Summary
[One sentence: pass/fail/pass-with-notes]

### Findings
| # | Severity | Agent | Finding | Recommendation |
|---|----------|-------|---------|----------------|
| 1 | Blocking | engineer | ... | ... |
| 2 | Minor | architect | ... | ... |

### Verdict
- [ ] Ready to push (no blocking findings)
- [ ] Needs fixes (blocking findings listed above)
```

### 9.4 Acceptance Criteria

- [ ] Quality gate defined with clear trigger conditions
- [ ] Review scope scales with change size
- [ ] Parallel review dispatch for independent reviewers
- [ ] Maximum 2 review rounds (not infinite)
- [ ] `push_policy: auto` allows skipping
- [ ] Documentation-only and trivial changes bypass the gate
- [ ] Clear output format with blocking/non-blocking severity

### 9.5 Edge Cases

- **What if the user just wants to push quickly?** → `push_policy: auto` in plan, or user can say "skip review" (Carter warns but complies).
- **What if reviewers disagree?** → Maestro presents both views. User decides.
- **What about WIP pushes (draft PRs)?** → No gate for draft/WIP pushes. Gate only on "ready" pushes.
- **What if there's no plan (ad-hoc push)?** → Still trigger gate based on file count/type heuristics.

---

## 10. Phase 5: New Specialized Agents

### Objective

Add focused agents for capabilities that Carter currently handles poorly or not at all.

### 10.1 Agent: carter-debugger

**Inspired by**: Yui's Sui agent (scientific debugging method).

**Why**: Currently carter-engineer handles debugging, but it's a distinct skill. Scientific debugging (hypothesize → test → verify) is more effective than ad-hoc guessing.

```markdown
---
description: "Debugger — scientific bug investigation with hypothesis testing and evidence-based root cause analysis."
mode: agent
temperature: 0.1
---

<identity>
You are Carter Debugger, the diagnostic specialist. Patient, methodical, skeptical
of first guesses. You investigate bugs using the scientific method: observe,
hypothesize, test, evaluate. You never declare a root cause without evidence.
</identity>

<role>
What you do:
- Investigate bugs using hypothesis-driven approach
- Reproduce issues systematically
- Narrow root causes through elimination
- Produce clear diagnosis with evidence
- Recommend fixes (but don't implement — that's carter-engineer)

What you don't do:
- Write application code fixes (→ carter-engineer)
- Write tests (→ carter-engineer)
- Diagnose CI/infra failures (→ carter-devops)
- Make architectural decisions (→ carter-architect)
</role>

<boundaries>
Delegate when: Bug reported, unexplained failure, unexpected behavior
Never do yourself: Modify source code, write tests, configure CI
Self-check: If about to edit a source file — STOP. Produce diagnosis, delegate fix.
</boundaries>

<methodology>
## Debugging Process

1. **Observe** — Read error, full context, stack trace. What exactly failed?
2. **Reproduce** — Can you trigger it consistently? If intermittent, note conditions.
3. **Hypothesize** — Rank 2-3 possible causes by likelihood.
4. **Test** — Design smallest experiment to confirm/eliminate top hypothesis.
5. **Eliminate** — Wrong hypothesis? Next one. Never retry same approach.
6. **Diagnose** — Root cause identified with evidence.
7. **Handoff** — Produce diagnosis + recommended fix for carter-engineer.

Rules:
- One hypothesis at a time. No shotgun debugging.
- Maximum 3 hypotheses before escalating or asking user for more context.
- Never guess. If you can't reproduce, say so.
- Never retry the same fix twice.
</methodology>
```

### 10.2 Agent: carter-knowledge

**Inspired by**: Yui's Chi agent (knowledge keeper).

**Why**: Currently carter-distill handles knowledge but only on-demand. A dedicated knowledge agent can be triggered systematically and manages knowledge routing.

**Decision**: DON'T add this as a separate agent. Instead, **enhance carter-learner** with knowledge management duties. Carter-learner already has the `carter-mistakes` and `carter-research` skills. Add systematic knowledge capture as a new skill.

**Enhancement to carter-learner**:
- Add skill: `carter-knowledge-capture` — Triggered by maestro at checkpoint moments
- Responsibility: Route learnings to the correct knowledge file
- Format entries consistently
- Deduplicate against existing entries

### 10.3 Agent Selection Summary

| Proposed | Decision | Rationale |
|----------|----------|-----------|
| carter-debugger | **ADD** | Distinct methodology from general engineering |
| carter-knowledge | **MERGE into carter-learner** | Not enough scope for standalone agent |
| carter-monitor | **SKIP** | Carter works in short sessions, not long-running ops |
| carter-storyteller | **SKIP** | Carter's users are technical, not stakeholder-facing |
| carter-security | **SKIP** | Security is cross-cutting; every agent has OWASP awareness |

### 10.4 Acceptance Criteria

- [ ] carter-debugger agent file created with scientific debugging methodology
- [ ] carter-debugger added to maestro's routing table
- [ ] carter-learner enhanced with knowledge capture capability
- [ ] Routing triggers updated: "bug, debug, investigate, root cause" → carter-debugger
- [ ] carter-engineer updated: "Never do yourself: root-cause investigation (→ carter-debugger)"

### 10.5 Edge Cases

- **What if the bug is trivial?** → carter-debugger does triage first. If root cause is obvious from the error message (e.g., typo, missing import), it can declare immediately without full methodology. "Trivial" = single possible cause, error message is self-explanatory.
- **What if carter-engineer is already debugging mid-task?** → Completing the current task is fine. But for NEW bug reports, route to carter-debugger.
- **Overlap with carter-devops for CI failures?** → Clear split: CI/infra failures → carter-devops. Application logic failures → carter-debugger. If ambiguous, maestro asks.

---

## 11. Phase 6: Tool Preference & Parallel Execution

### Objective

Codify tool selection hierarchy and enable parallel agent dispatch for independent tasks.

### 11.1 Tool Preference Hierarchy

Add to `instructions/copilot-instructions.md`:

```markdown
<tool_preference>

## Tool Selection Hierarchy

When multiple tools can accomplish the same task, prefer in this order:

| Tier | Tool Type | Examples | When to Use |
|------|-----------|----------|-------------|
| 1 (preferred) | MCP tools | GitHub MCP, Atlassian MCP, Terraform MCP | Always when available |
| 2 (fallback) | CLI tools | `gh`, `terraform`, `kubectl`, `jira-cli` | When no MCP equivalent |
| 3 (last resort) | Scripts | `curl`, `python`, raw shell | Only when MCP and CLI cannot |

**Why this order:**
- MCP tools provide structured, typed responses with built-in error handling
- CLI tools are well-documented and predictable
- Raw scripts are fragile, hard to maintain, and error-prone

**Examples:**
- ✅ GitHub MCP to list PRs → ❌ Don't use `gh pr list` if MCP available
- ✅ `gh` CLI for operations without MCP → ❌ Don't use `curl` against GitHub API
- ✅ `terraform` CLI for plan/apply → ❌ Don't write bash wrappers

</tool_preference>
```

### 11.2 Parallel Execution Rules

Update maestro's `<routing>` block:

```markdown
## Dispatch Rules

**Parallel dispatch** — When the request involves independent tasks:
- Identify which tasks have no data dependency between them
- Launch independent agents simultaneously
- Collect results and synthesize

**Sequential dispatch** — When task B requires the output of task A:
- Run A, capture output
- Pass output as context to B

**Dependency heuristic:**
- If Agent B's prompt can be written fully from the user's original request → parallel
- If Agent B's prompt requires information only Agent A can produce → sequential

**Examples:**
- "Review this code and check for security issues" → parallel (engineer + security review)
- "Design an API and then implement it" → sequential (architect → engineer)
- "Create a plan and set up CI" → parallel (PM + DevOps, independent)
- "Write tests then implement" → sequential (engineer tests → engineer implements)
```

### 11.3 Time Awareness

Add to `instructions/copilot-instructions.md`:

```markdown
<time_awareness>

## Time Awareness

The current year is 2026. All agents must operate with this awareness:

- **Verify versions**: Don't trust training-data version numbers. Check official sources.
- **Default to latest stable**: When selecting dependencies, prefer current stable versions.
- **Deprecated patterns**: If a pattern was deprecated before 2026, don't use it.
- **Search queries**: Include current year when searching for docs or best practices.
- **Flag uncertainty**: If you cannot verify a version or API against current sources, say so.

</time_awareness>
```

### 11.4 Acceptance Criteria

- [ ] Tool preference hierarchy documented in global instructions
- [ ] Parallel dispatch rules defined in maestro
- [ ] Dependency heuristic is clear and actionable
- [ ] Time awareness added to global instructions
- [ ] No behavioral change needed for existing agents (they inherit global rules)

### 11.5 Edge Cases

- **What if MCP tool is unreliable/slow?** → Fall to tier 2. Note: "MCP [tool] was unavailable, using CLI fallback."
- **What if parallel agents step on each other?** → Agents don't share state during execution. They read the same knowledge but produce independent outputs. Maestro merges.
- **What if the year in time_awareness is stale?** → Platform injects current date in system prompt. The instruction reinforces behavior, the platform provides the actual date.

---

## 12. Risk Register

| # | Risk | Probability | Impact | Mitigation |
|---|------|-------------|--------|-----------|
| R1 | Over-engineering: Adding too much ceremony kills agility | Medium | High | Strict "don't adopt" list. Test each phase in real use before proceeding to next. |
| R2 | Session bootstrap reads stale plans, confuses user | Medium | Medium | Stale plan detection (>30 days without update). Flag don't assume. |
| R3 | Boundary enforcement makes agents too rigid | Low | Medium | "Never do yourself" allows exceptions with user override. Not absolute blocks. |
| R4 | `.carter-state/` clutters workspace | Low | Low | Added to `.gitignore`. Transparent to git. |
| R5 | Plan system creates overhead for simple tasks | Medium | Medium | Plans only for multi-step work. Single-step tasks have no ceremony. |
| R6 | Knowledge files grow unbounded | Low | Low | Categories + archival strategy for entries >1 year old. |
| R7 | Parallel execution produces conflicting outputs | Low | Medium | Maestro synthesizes. Present both to user if genuine conflict. |
| R8 | Migration breaks existing Carter users | Medium | High | All changes are additive. Old files still work. Migration is opt-in. |
| R9 | New XML structure isn't recognized by all platforms | Low | High | Test on VS Code Copilot, verify agent file parsing before rolling out. |
| R10 | carter-debugger overlaps too much with carter-engineer | Medium | Low | Clear boundary: debugger diagnoses, engineer fixes. Debugger never touches source. |

---

## 13. Anti-Patterns — What NOT to Adopt

These Yui features were deliberately excluded. Document WHY to prevent re-introducing them later.

| Feature | Why NOT |
|---------|---------|
| `ask_user` at end of every response (non-negotiable) | Repetitive, annoying UX. Carter offers next steps naturally when appropriate. |
| 13 agents | Over-fragmented. 6 agents (5 current + debugger) cover Carter's needs. |
| Status folders for plans (`draft/`, `wip/`, `done/`) | Filesystem gymnastics. Frontmatter status is simpler and grep-friendly. |
| Local git repos for `.plans/` and `.knowledge/` | Extra complexity for single-user tool. Regular files are sufficient. |
| "No trivial work exception" | Bureaucratic. Small tasks don't need plans. Carter stays pragmatic. |
| 3 consecutive clean audit rounds | Can loop indefinitely. One review + one fix cycle maximum. |
| Mandatory RFC for all new ideas | Only for architecture-level changes. Most work doesn't need RFC. |
| Commit Co-authored-by trailers | Carter doesn't have a bot identity. User commits as themselves. |
| OpenCode support | Carter is VS Code Copilot focused. Add later if needed. |
| Handlebars templating for agent generation | Carter agents are hand-crafted, not generated. Templates add complexity without value for a single instance. |
| Japanese agent names | Carter has its own naming convention. Names should describe the role. |
| Hana's redaction system | Carter is personal/team use, not public-facing. Redaction is overkill. |
| Miru monitoring agent | Carter works in short interactive sessions, not monitoring long-running ops. |
| Chi as separate knowledge agent | Merged into carter-learner. Not enough scope for standalone. |

---

## 14. Migration Strategy

### For Existing Carter Users (You)

1. **Phase 0** is non-breaking: agent files get restructured but behavior doesn't change.
2. **Phase 1** adds new files (`tools.md`, `gotchas.md`) and renames one (`mistakes.md` → `lessons-learned.md`). Old file can coexist during transition.
3. **Phase 2** adds content to existing files (boundaries). Purely additive.
4. **Phase 3** introduces `.carter-state/`. Created on first use, zero friction until then.
5. **Phase 4** is behavioral (quality gates). Opt-in via plan's `push_policy`.
6. **Phase 5** adds one new agent file. Purely additive.
7. **Phase 6** adds content to global instructions. Purely additive.

**Nothing is removed or broken.** Every phase is additive. Old behavior continues to work until the new behavior is explicitly activated.

### Validation After Each Phase

After completing each phase:
1. Run Carter in a fresh conversation — does it behave correctly?
2. Test the specific new behavior introduced in that phase.
3. Use Carter for real work for at least 2-3 sessions before starting next phase.
4. Record any issues in `knowledge/gotchas.md`.

---

## 15. Success Metrics

How to know the implementation is working:

| Metric | Before | Target After | How to Measure |
|--------|--------|-------------|----------------|
| Session recovery time | "Explain everything again" | Read plan, continue in <30s | Observe: how many turns to recover context |
| Knowledge captured per week | 0 (manual, never happens) | 2-3 entries (triggered) | Count entries added to knowledge/ files |
| Agent boundary violations | Unknown (no tracking) | 0 per session | Self-check catches before execution |
| Plan completion tracking | None | Active plans show progress | `.carter-state/plans/active/` has current state |
| Review coverage before push | 0% (no gate) | 100% of code pushes | Quality gate triggers on push |
| Time to start working (bootstrap) | 2-5 minutes re-explaining | <30 seconds reading state | Measure from session start to first productive action |

---

## 16. Open Questions

Questions that need answers before or during implementation:

1. **VS Code Copilot agent file parsing** — Does it honor all XML block names? Are there reserved block names that cause issues? Need to test before Phase 0.

2. **Parallel subagent execution** — Does `runSubagent` in VS Code Copilot support truly parallel calls? Or does it serialize internally? Need to verify before Phase 6.

3. **`.carter-state/` persistence** — If Carter is used via VS Code Copilot Chat, does it have filesystem access to create/read `.carter-state/`? Verify tool capabilities.

4. **Knowledge file size limits** — How large can `lessons-learned.md` grow before it affects context loading performance? Set a soft limit (e.g., 500 lines) and archive beyond that.

5. **Plan step granularity** — How small should steps be? Yui says "completable in one session." Carter should say "completable in one focused conversation."

6. **Multi-workspace plans** — If Carter is used across workspaces, should plans be workspace-local or global? Decision: workspace-local (`.carter-state/` per workspace).

7. **Integration with carter-ops** — carter-ops already handles git operations with approval gates. How does the quality gate interact? Decision: Quality gate runs BEFORE carter-ops push sequence. Gate is the "should we?" check, ops is the "how we do it" execution.

8. **Backward compatibility** — If someone clones the carter-ai repo and uses it without running migration, does everything still work? Decision: YES. All changes are additive. Missing `.carter-state/` means "no plans yet" — not an error.

---

## Appendix A: File Change Summary

| Phase | Files Created | Files Modified | Files Renamed |
|-------|-------------|----------------|---------------|
| 0 | 0 | 7 (all agents + instructions) | 0 |
| 1 | 3 (`tools.md`, `gotchas.md`, session bootstrap in maestro) | 3 (`lessons-learned.md` rename, maestro, instructions) | 1 (`mistakes.md` → `lessons-learned.md`) |
| 2 | 0 | 6 (all agents get boundaries) | 0 |
| 3 | 2 (plan template, RFC template) | 2 (carter-pm skill, maestro bootstrap) | 0 |
| 4 | 0 | 1 (maestro quality gate rules) | 0 |
| 5 | 1 (`agents/carter-debugger.md`) | 2 (maestro routing, carter-engineer boundaries) | 0 |
| 6 | 0 | 1 (global instructions) | 0 |
| **Total** | **6** | **~15 modifications across phases** | **1** |

---

## Appendix B: Dependency Graph

```
Phase 0 (Foundation)
    │
    ├──→ Phase 1 (Knowledge)
    │         │
    │         └──→ Phase 3 (Plans)
    │                   │
    │                   └──→ Phase 4 (Quality Gates)
    │
    ├──→ Phase 2 (Boundaries)
    │         │
    │         └──→ Phase 5 (New Agents)
    │
    └──→ Phase 6 (Polish — independent, run anytime after Phase 0)
```

---

## Appendix C: Comparison — Before & After

### Agent File: Before (carter-engineer.md)
```markdown
---
description: "Software Engineer..."
mode: agent
temperature: 0.1
---

<role>
You are Carter Engineer...
[mixed markdown content]
</role>

<skills>
## Available Skills
...
</skills>

<mcp>
## Tool Access
...
</mcp>
```

### Agent File: After (carter-engineer.md)
```markdown
---
description: "Software Engineer..."
mode: agent
temperature: 0.1
# recommended-model: claude-sonnet-4.6
---

<identity>
You are Carter Engineer, the software engineering specialist. Pragmatic,
disciplined, quality-focused. You write code for humans to understand.
Clarity over cleverness. You own the full TDD cycle.
</identity>

<role>
What you do:
- Write application code to satisfy specs and tests
- Write tests (TDD: red → green → refactor)
- Code review for quality, security, testability
- Debug and fix bugs
- Refactor for clarity and maintainability

What you don't do:
- Design system architecture (→ carter-architect)
- Create project plans (→ carter-pm)
- Configure CI/CD pipelines (→ carter-devops)
- Root-cause investigation (→ carter-debugger)
</role>

<boundaries>
Do yourself: code, tests, reviews, fixes, refactoring
Never do yourself: architecture design, CI/CD config, planning, root-cause diagnosis

Self-check: Before acting, verify the task is in your "Do yourself" list.
If you're about to design a system or write a pipeline — STOP. Delegate.
</boundaries>

<context_loading>
Before writing code:
1. Read `knowledge/gotchas.md` — known issues
2. Read `knowledge/patterns.md` — established patterns
3. Read existing tests — match conventions
4. Read relevant plan step — understand the spec
</context_loading>

<skills>
- carter-code-review — Review code for quality and security
- carter-test-first — TDD workflow
- carter-python — Python standards
- carter-golang — Go standards
</skills>

<tools>
- GitHub MCP: Full access — PRs, reviews, issues
- Terraform MCP: Read-only — review configs for context
</tools>
```

---

*Plan authored: 2026-05-28*
*Source analysis: yui-soul assessment (archived planning note)*
*Status: Ready for review and phased execution*
