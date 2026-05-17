# Memory and Knowledge

Carter has a three-tier system for accumulating and reusing experience across conversations: **visible memory** (Carter-managed files on disk), **platform memory** (VS Code's built-in memory tool), and **knowledge** (curated, structured entries). Visible memory is the primary store; platform memory provides auto-loading convenience on supported surfaces; knowledge is the long-term curated destination.

## Architecture Overview

```
Conversation
    │
    ├──→ carter-mistakes writes to:
    │      • ~/.carter/memories/ (visible, persistent, all surfaces)
    │      • /memories/ (platform, auto-loaded in VS Code)
    │
    ├──→ Session notes go to:
    │      • ~/.carter/memories/session/ (visible, cleaned on distill)
    │
    ▼
User runs: @carter-maestro distill
    │
    ├──→ Reads ~/.carter/memories/ (all scopes) + /memories/ (platform)
    ├──→ Promotes to ~/.copilot/knowledge/
    ├──→ Cleans up session files (with confirmation)
    └──→ Suggests: "Run carter-reflect to check for agent improvements"
              │
              ▼
         carter-reflect
              │
              ├──→ Reads memories + knowledge
              ├──→ Identifies patterns
              ├──→ Proposes edits to carter-*.md / SKILL.md
              └──→ Records improvement decisions
```

Four skills drive the system (`carter-mistakes`, `carter-distill`, `carter-reflect`), and global instructions tie it together across all surfaces.

## Tier 1: Visible Memory (`~/.carter/memories/`)

Visible memory is Carter-managed — plain Markdown files on disk that both the user and the AI can browse, edit, and track. This is the primary memory store.

### Directory structure

```
~/.carter/memories/
├── user/                     # Persistent cross-project notes
│   ├── jira-api-lessons.md
│   └── terraform-patterns.md
├── session/                  # Per-conversation working notes
│   ├── 2026-05-17-auth-refactor.md
│   └── 2026-05-15-ops-redesign.md
└── repo/                     # Per-project, organized by git repo name
    ├── ai-assistant/
    │   └── installer-quirks.md
    └── infra-platform/
        └── vpc-debugging.md
```

| Scope | Path | Persistence | Purpose |
|-------|------|-------------|---------|
| User | `~/.carter/memories/user/` | Permanent until deleted | Cross-project insights, general patterns, preferences |
| Session | `~/.carter/memories/session/` | Until distill cleanup or explicit deletion | Conversation-scoped working notes, in-progress analysis |
| Repo | `~/.carter/memories/repo/<name>/` | Permanent until deleted | Project-specific context, codebase conventions |

### Why visible memory exists

The platform `/memories/` tool (Tier 2) stores files deep inside VS Code's internal storage — invisible to users, not portable across surfaces, and not git-trackable. Visible memory solves these problems:

- **Browseable** — open `~/.carter/memories/` in any file explorer or editor
- **Portable** — works on all surfaces (VS Code, Copilot CLI, OpenCode)
- **Trackable** — can be git-tracked in the future (see v2 roadmap)
- **Editable** — users can manually add, modify, or delete notes

### What gets written here

1. **By carter-mistakes** — structured mistake/lesson notes go to `user/` (cross-project) or `repo/<name>/` (project-specific)
2. **By any agent** — ad-hoc notes when the user says "remember this" or an agent encounters something worth preserving
3. **Session notes** — conversation working state goes to `session/` for later promotion via distill

## Tier 2: Platform Memory (`/memories/`)

Platform memory is a **VS Code-provided tool** — not part of Carter's codebase. It provides one key advantage: **auto-loading**. The first 200 lines of user memory are injected into the agent's context automatically on every turn, without the agent needing to read any files.

### Physical storage

| Scope | Physical Path (macOS) |
|-------|------|
| User | `~/Library/Application Support/Code/User/globalStorage/github.copilot-chat/memory-tool/memories/` |
| Session | `~/Library/Application Support/Code/User/workspaceStorage/<id>/GitHub.copilot-chat/memory-tool/memories/<session-id>/` |
| Repo | Workspace `.github/copilot/` or internal workspace storage |

### Limitations

- **VS Code only** — OpenCode does not have this tool. Copilot CLI support varies.
- **Invisible** — files buried in VS Code internals, not browseable.
- **Not portable** — tied to the specific VS Code installation.
- **Session memory is ephemeral** — deleted when the conversation ends.

### How it coexists with visible memory

Carter writes to **both** visible memory and platform memory simultaneously:
- **Visible memory** (`~/.carter/memories/`) is the source of truth — always written, works everywhere
- **Platform memory** (`/memories/`) is a convenience layer — written when available (VS Code), provides auto-loading
- **On surfaces without platform memory** (OpenCode), only visible memory is used

When reading, `carter-distill` scans both locations and deduplicates.

## Tier 3: Knowledge (`~/.copilot/knowledge/`)

Knowledge is Carter's **curated, long-term store**. It lives on disk at `~/.copilot/knowledge/` and consists of six topic-specific Markdown files:

| File | Content Type | Key Fields |
|------|-------------|------------|
| `decisions.md` | Architecture Decision Records | Context, Decision, Rationale, Alternatives, Tags |
| `mistakes.md` | Failures and corrective lessons | Context, Mistake, Fix, Lesson, Tags |
| `patterns.md` | Recurring design patterns | Context, Pattern, When to use, Example, Tags |
| `debugging.md` | Debugging techniques and fixes | Context, Symptom, Root cause, Fix, Tags |
| `infrastructure.md` | Cloud/infra configurations | Context, Configuration, Outcome, Tags |
| `project-history.md` | Project milestones and outcomes | Project, Milestone, Outcome, Tags |

### Entry format

Every entry follows a consistent Markdown structure:

```markdown
## YYYY-MM-DD | Title
- **Context:** Where this happened (repo, file, project)
- **[Topic-specific fields]:** ...
- **Tags:** comma-separated keywords
```

The date prefix enables chronological reading. Tags enable searchability across files.

### How knowledge files are installed

The installer (`install.py`) copies template files from the repository's `knowledge/` directory to `~/.copilot/knowledge/`. Each template contains only the title, description, and a commented-out format guide — no entries.

**Critical behavior**: the installer uses a no-overwrite policy. If a knowledge file already exists at the destination, it is skipped entirely. This prevents the installer from wiping out user-curated entries on re-install or update.

### How knowledge is read

Two global rules files instruct every agent to consult both memory and knowledge:

- **`copilot-instructions.md`** (VS Code + Copilot CLI)
- **`AGENTS.md`** (OpenCode)

Both contain the same rules:
- Record mistakes and key learnings to `~/.carter/memories/` (visible) and `/memories/` (platform).
- Use `~/.carter/memories/user/` for cross-project notes, `repo/<name>/` for project-specific notes, and `session/` for conversation-scoped working notes.
- Consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing solutions.

## Skills

### carter-mistakes

**Owner**: `@carter-learner`

**Purpose**: Capture mistakes and failures as they happen, in a structured format.

**Trigger**: When a mistake or failure is identified during a conversation. The user might say "record this mistake" or the agent might proactively identify a failure worth capturing.

**Workflow**:
1. Identify the mistake — what specifically went wrong
2. Capture context — repository, file, what was being attempted
3. Root cause — why it happened (not surface symptoms)
4. Fix — what resolved it
5. Lesson — what to do differently next time (the core takeaway)
6. Write to visible memory (`~/.carter/memories/user/` or `repo/<name>/`)
7. Also write to platform memory (`/memories/`) if available
8. If enough notes have accumulated, suggest running `carter-distill`

**Guidelines**: No blame (focus on systemic cause), be specific, check for duplicates against existing `~/.copilot/knowledge/mistakes.md` and `~/.carter/memories/`, use meaningful tags.

### carter-distill

**Owner**: `@carter-maestro`

**Purpose**: Promote raw memory notes into curated knowledge entries.

**Trigger**: On-demand only — the user asks for it. Never auto-runs. Typical invocation: `@carter-maestro distill` or `distill my notes`.

**Workflow**:
1. **Read** — Scan notes from all sources:
   - `~/.carter/memories/user/` — persistent cross-project notes
   - `~/.carter/memories/repo/` — project-specific notes (all repos)
   - `~/.carter/memories/session/` — conversation working notes
   - `/memories/` — platform memory (if available)
2. **Classify** — Map each note to one of the six knowledge topics
3. **Deduplicate** — Check existing entries in the target knowledge file and across both memory sources
4. **Format** — Structure each entry using the standard Markdown format
5. **Append** — Add new entries to the appropriate `~/.copilot/knowledge/` file
6. **Report** — Show what was promoted: count per topic, skipped duplicates
7. **Cleanup** — Offer to delete promoted session files (with confirmation). Flag promoted user/repo files for optional deletion.
8. **Suggest reflect** — If multiple patterns or recurring mistakes were promoted, suggest running `carter-reflect`

**Guidelines**: Only run when asked, preserve the user's original meaning, ask when classification is unclear, create entries in multiple files if a note spans topics, deduplicate across both memory sources.

### carter-reflect

**Owner**: `@carter-maestro`

**Purpose**: Analyze accumulated memory and knowledge to propose improvements to Carter's agent and skill files.

**Trigger**: Explicit invocation (`@carter-maestro reflect`) or suggested at the end of distill. Never auto-runs.

**Workflow**:
1. **Read memory** — Scan all files in `~/.carter/memories/` (all scopes)
2. **Read knowledge** — Scan all files in `~/.copilot/knowledge/`, focusing on `mistakes.md`, `patterns.md`, and `debugging.md`
3. **Identify patterns** — Look for:
   - Recurring mistakes (same root cause across conversations)
   - Workarounds that should be codified as guidelines
   - Missing instructions that led to agent failures
   - Skill gaps — tasks the user repeatedly corrects the agent on
   - Outdated rules that no longer apply
4. **Map to targets** — Determine which file each improvement applies to (agent definition, skill file, global instructions, or OpenCode `AGENTS.md`)
5. **Propose changes** — For each improvement, show the source evidence, target file, proposed edit, and rationale
6. **Apply with approval** — Only apply changes the user approves
7. **Record** — Log the improvement in `~/.copilot/knowledge/decisions.md` as an architecture decision

**Guidelines**: Only run on-demand, be conservative (a single mistake is not a pattern), cite specific memory/knowledge entries as evidence, prefer adding guidelines over removing them, keep proposals minimal.

### carter-explain and carter-research

These are `@carter-learner` skills that read from both memory and knowledge but don't write to them. They may reference past decisions or patterns when explaining topics.

## Agent Roles

### carter-learner

The knowledge specialist. Has `carter-mistakes`, `carter-explain`, and `carter-research` as skills. Primary responsibilities:
- Recording mistakes and extracting learnable patterns
- Breaking down complex topics with cited sources
- Researching official documentation

Maestro routes requests to Learner when the user says things like: "explain," "learn," "document," "research," "why," "how does," "teach."

### carter-maestro

The orchestrator. Has `carter-distill` and `carter-reflect` as skills (alongside `carter-triage`). Maestro is the entry point for both the distill and reflect workflows.

### All agents

Every agent follows the global instruction to consult `~/.carter/memories/` and `~/.copilot/knowledge/` before proposing solutions. This rule lives in two global rules files: `copilot-instructions.md` (VS Code + Copilot CLI) and `AGENTS.md` (OpenCode). Both are maintained by the installer.

## Information Flow

The complete lifecycle from mistake to agent improvement:

```
1. Failure occurs during work
         │
         ▼
2. carter-mistakes records it to:
   • ~/.carter/memories/user/ (visible, persistent)
   • /memories/ (platform, auto-loaded in VS Code)
         │
         ▼
3. Note sits in ~/.carter/memories/ (browseable)
   May accumulate alongside other notes
         │
         ▼
4. User runs: @carter-maestro distill
         │
         ▼
5. carter-distill reads ~/.carter/memories/ + /memories/
   Classifies → Deduplicates → Formats → Appends
   Cleans up session files, suggests reflect
         │
         ▼
6. Entry lands in ~/.copilot/knowledge/mistakes.md
   (or decisions.md, patterns.md, etc.)
         │
         ▼
7. User runs: @carter-maestro reflect
         │
         ▼
8. carter-reflect reads memories + knowledge
   Identifies recurring patterns
   Proposes edits to carter-*.md / SKILL.md
   Applies approved changes, records decisions
         │
         ▼
9. Future conversations benefit from:
   • Updated agent/skill rules (reflect output)
   • Knowledge base consultation (global instruction)
   • Visible memory notes (browseable context)
```

Not all knowledge follows this exact path. Some entries bypass the memory step — a user might ask Maestro to distill directly from a conversation, manually edit memory or knowledge files, or skip straight to reflect.

## Cross-Surface Behavior

| Surface | Visible Memory | Platform Memory | Knowledge | Distill | Reflect |
|---------|---------------|----------------|-----------|---------|---------|
| VS Code | Read/write `~/.carter/memories/` | Read/write `/memories/` (auto-loaded) | Read `~/.copilot/knowledge/` | Works | Works |
| Copilot CLI | Read/write `~/.carter/memories/` | Read/write `/memories/` (if available) | Read `~/.copilot/knowledge/` | Works | Works |
| OpenCode | Read/write `~/.carter/memories/` | Not available | Read `~/.copilot/knowledge/` | Works | Works |

On surfaces without platform memory (OpenCode), agents write only to visible memory. The global rules in `AGENTS.md` reflect this — they reference `~/.carter/memories/` as the primary target and mention `/memories/` as secondary if available.

## Installation

The installer sets up both memory directories and knowledge templates:

```bash
uv run install.py                    # Creates ~/.carter/memories/{user,session,repo}
                                     # Copies templates to ~/.copilot/knowledge/
```

### What the installer does

1. Creates `~/.carter/memories/user/`, `~/.carter/memories/session/`, `~/.carter/memories/repo/` directories
2. Copies six knowledge template files to `~/.copilot/knowledge/`
3. **Skips existing files** — never overwrites user content (knowledge only; directories are always ensured)
4. Records all paths in the manifest (`.carter-manifest.json`)

### What the installer does NOT do

- Does not initialize a Git repository in the memory or knowledge directories (planned for v2)
- Does not sync memory or knowledge across machines (planned for v2)
- Does not create any platform `/memories/` files (those are VS Code-managed)

## Future: Git-Backed Sync (v2)

The v2 plan includes syncing both memory and knowledge across machines via Git repositories:

- **Knowledge sync**: `--knowledge-repo <url>` flag for `install.py`
- **Memory sync**: `~/.carter/memories/` could be git-tracked independently
- **Auto-commit**: `carter-distill` would commit after promoting entries
- **New skill**: `carter-knowledge-sync` for pull/push across machines
- **Push gating**: Push only on explicit request (`@carter-maestro distill --push`)

This is not yet implemented. Currently, both memory and knowledge files are local to the machine.
