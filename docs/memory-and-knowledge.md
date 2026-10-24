# Memory and Knowledge

Carter accumulates experience as you work. This isn't a chatbot that forgets everything between sessions — it captures learnings, tracks decisions, and uses that context to give better answers over time.

This document explains how the knowledge system works, where things are stored, and how you interact with it.

## Quick Orientation

Carter has **two levels** of knowledge storage:

| Level | Location | Scope | Managed By |
|-------|----------|-------|-----------|
| **Workspace** | `.carter/knowledge/` | Per-workspace (your project) | `carter init` + you |
| **System** | `~/.carter/knowledge/` | Global (all projects) | `carter install` + `carter-distill` |

There's also a **memory layer** for raw, unprocessed notes that haven't been promoted to knowledge yet:

| Level | Location | Scope |
|-------|----------|-------|
| **Visible memory** | `~/.carter/memories/` | Cross-project + per-project |
| **Platform memory** | `/memories/` (VS Code internal) | Per-session + user-level |

**The key distinction:** Memory is raw notes. Knowledge is curated, structured, and consulted before acting.

---

## Workspace Knowledge (`.carter/knowledge/`)

When you run `carter init`, it creates five knowledge files inside `.carter/knowledge/`:

| File | Purpose | Rules |
|------|---------|-------|
| `lessons-learned.md` | Universal truths from experience | **Append-only** — never delete entries |
| `gotchas.md` | Known issues + workarounds | Can remove entries when fixed |
| `tools.md` | Available toolchain reference | Update as tools change |
| `decisions.md` | Architecture decisions + rationale | Mark old ones [SUPERSEDED] |
| `patterns.md` | Recurring conventions | Update as patterns evolve |

### How These Get Populated

Carter doesn't auto-write to knowledge files. After certain events, Maestro asks:

| Event | Prompt |
|-------|--------|
| Plan completed | "Any learnings worth capturing?" |
| Debugging >10 minutes | "Record this as a gotcha?" |
| Unexpected failure recovered | "Add to known issues?" |
| You correct Carter | "Record this correction?" |
| New tool discovered | "Document in tools.md?" |

You confirm or decline. If you decline, Carter moves on immediately — no nagging.

### Safe From Overwrites

`carter update` re-renders agent files from templates, but **never touches knowledge files**. Your accumulated learnings are safe. This is enforced in code — the `_init_knowledge_files()` function skips any file that already exists.

### Optional Git Tracking

By default, `carter init` runs `git init` inside `.carter/`. This gives you history on knowledge changes without requiring you to track them in your main repo. Disable with `--no-git-state`.

Run `carter save` at natural stopping points to commit a recovery snapshot of `.carter/` (plans, sessions, knowledge) — so a deleted plan or session is restorable from `.carter/.git`.

### Optional Entry Metadata (`scope` / `tags`)

The five workspace knowledge files keep their plain-Markdown shape. Individual entries **may** optionally carry lightweight YAML metadata when portability or filtering matters (per ADR-0003 D1):

```yaml
scope: workspace     # universal | workspace — does this apply everywhere, or just here?
tags: [terraform, auth]
```

This is genuinely optional — not half-mandatory. Use it on an entry you might later promote to system knowledge (`scope: universal`) or want to find by tag; skip it otherwise. The canonical schema is in [reference/frontmatter.md](reference/frontmatter.md).

---

## System Knowledge (`~/.carter/knowledge/`)

System-level knowledge is global — it applies across all your workspaces. It lives at `~/.carter/knowledge/` and contains six topic-specific files:

| File | Content Type |
|------|-------------|
| `decisions.md` | Architecture Decision Records |
| `mistakes.md` | Failures and corrective lessons |
| `patterns.md` | Recurring design patterns |
| `debugging.md` | Debugging techniques and fixes |
| `infrastructure.md` | Cloud/infra configurations |
| `project-history.md` | Project milestones and outcomes |

### Entry Format

Every entry follows a consistent structure:

```markdown
## YYYY-MM-DD | Title
- **Context:** Where this happened (repo, file, project)
- **[Topic-specific fields]:** ...
- **Tags:** comma-separated keywords
```

### How Entries Get Here

Entries are **promoted** from raw memory via `@carter-maestro distill`. This skill reads accumulated memory notes, classifies them by topic, deduplicates against existing entries, and appends to the appropriate file.

---

## Memory (Raw Notes)

Memory is where unprocessed observations land before they're promoted to knowledge. Think of it as a scratchpad.

### Visible Memory (`~/.carter/memories/`)

Plain Markdown files on disk that both you and Carter can browse and edit:

```
~/.carter/memories/
├── user/                     # Persistent cross-project notes
│   ├── jira-api-lessons.md
│   └── terraform-patterns.md
├── session/                  # Per-conversation working notes
│   └── 2026-05-17-auth-refactor.md
└── repo/                     # Per-project context
    └── carter-ai/
        └── installer-quirks.md
```

| Scope | Path | Persistence |
|-------|------|-------------|
| User | `~/.carter/memories/user/` | Permanent |
| Session | `~/.carter/memories/session/` | Until distill cleanup |
| Repo | `~/.carter/memories/repo/<name>/` | Permanent |

**Why visible memory exists:** VS Code's built-in `/memories/` tool stores files in internal storage — invisible, not portable, not git-trackable. Visible memory is browseable, works on all surfaces, and can be manually edited.

### Platform Memory (`/memories/`)

VS Code's built-in memory tool. Its key advantage: **auto-loading** — the first 200 lines are injected into the agent's context automatically.

| Scope | Persistence | Available On |
|-------|-------------|-------------|
| User | Permanent | VS Code only |
| Session | Conversation-scoped | VS Code only |
| Repo | Workspace-scoped | VS Code only |

**Limitations:** VS Code only, invisible to users, not portable across machines.

Carter writes to **both** visible and platform memory simultaneously when platform memory is available. Visible memory is always the source of truth.

---

## The Knowledge Lifecycle

How a mistake becomes an agent improvement:

```
1. Failure occurs during work
         │
         ▼
2. carter-mistakes records to ~/.carter/memories/
         │
         ▼
3. Notes accumulate (browseable by you or Carter)
         │
         ▼
4. You run: @carter-maestro distill
         │
         ▼
5. carter-distill promotes to ~/.carter/knowledge/
   (classifies, deduplicates, formats, appends)
         │
         ▼
6. You run: @carter-maestro reflect
         │
         ▼
7. carter-reflect analyzes patterns in knowledge
   Proposes improvements to agent/skill files
   Applies approved changes
         │
         ▼
8. Future conversations benefit from updated rules
```

### Skills That Drive the Lifecycle

| Skill | Owner | Purpose |
|-------|-------|---------|
| `carter-mistakes` | carter-learner | Capture failures as they happen |
| `carter-distill` | carter-maestro | Promote raw notes to curated knowledge |
| `carter-reflect` | carter-maestro | Propose agent/skill improvements from patterns |

All three are **on-demand only** — they never auto-run.

---

## Workspace vs. System Knowledge: When to Use Which

| Scenario | Where It Goes |
|----------|---------------|
| "This Terraform provider has a bug in v1.6" | `.carter/knowledge/gotchas.md` (workspace) |
| "Always validate JWT expiry before checking claims" | `~/.carter/knowledge/patterns.md` (system) |
| "We use envelope format for all API responses" | `.carter/knowledge/patterns.md` (workspace) |
| "Never use `rm -rf` without confirmation in agents" | `~/.carter/knowledge/mistakes.md` (system) |
| "Our CI uses Buildkite, not GitHub Actions" | `.carter/knowledge/tools.md` (workspace) |

**Rule of thumb:** If it applies only to this project → workspace. If it applies everywhere → system.

---

## Cross-Surface Behavior

| Surface | Visible Memory | Platform Memory | Knowledge | Distill | Reflect |
|---------|---------------|----------------|-----------|---------|---------|
| VS Code | ✅ Read/write | ✅ Read/write (auto-loaded) | ✅ Read | ✅ | ✅ |
| Copilot CLI | ✅ Read/write | Varies | ✅ Read | ✅ | ✅ |
| OpenCode | ✅ Read/write | ❌ Not available | ✅ Read | ✅ | ✅ |

---

## Installation

### Workspace-level (via `carter init`)

```bash
mkdir -p ~/my-workspace   # carter init requires an existing directory
carter init ~/my-workspace
```

Creates `.carter/knowledge/` with five template files. Never overwrites existing content.

### System-level (via `carter install`)

```bash
carter install
```

Creates:
- `~/.carter/memories/{user,session,repo}` directories
- `~/.carter/config.toml` (carter-ops attribution settings)
- `~/.carter/knowledge/` with six seed files — header + entry-format comment only, no
  entries (existing files are never overwritten)
- Records all paths in `~/.carter/manifest.json` for clean uninstall; backups of
  replaced files go to `~/.carter/backups/<timestamp>/`

### Upgrading from a `~/.copilot` install

Earlier versions kept knowledge, the manifest and backups under `~/.copilot/`. The
first `carter install` copies them to `~/.carter/knowledge/`, `~/.carter/manifest.json`
and `~/.carter/backups/`. Nothing in `~/.copilot` is deleted, and a destination file
that already exists with different content is kept (a warning names it). The
migration runs once; `~/.carter/.migrated-from-copilot` marks it done (delete that
file to run it again).

Copilot/VS Code files from the old install stay in place. `carter uninstall --legacy`
removes the Carter ones listed in the old `~/.copilot/.carter-manifest.json` (agents,
skills, instructions, `carter-*` MCP entries), skipping files you edited. Without
that manifest it only lists what to remove by hand.

### What the installer does NOT do

- Does not initialize Git in memory directories (workspace `.carter/` has its own git)
- Does not sync across machines (local only)
- Does not create platform `/memories/` files (VS Code manages those)
