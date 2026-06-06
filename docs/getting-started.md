# Getting Started

This guide walks you through setting up Carter and using it in real scenarios. It's written for someone new to multi-agent AI assistants — we'll explain concepts as we go.

## Prerequisites

- Python 3.11+ installed
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- VS Code with GitHub Copilot, or Copilot CLI
- Git installed and configured

## Concepts

Before diving in, here's the mental model:

**Agents** are specialized AI assistants with focused expertise. Each one knows what it should and shouldn't do. Carter has 7 agents: 6 conversational specialists (Maestro, Architect, Engineer, DevOps, Learner, PM) plus **Narrator**, which reframes and redacts external-facing content. All 7 are installed by `carter install` and scaffolded by `carter init`.

**Maestro** is the orchestrator — it receives your request and routes it to the right specialist. You can also talk to any agent directly.

**Skills** are instruction sets that agents load for specific tasks. Think of them as playbooks. They're hand-maintained (not generated from templates).

**Templates** are Jinja2 files that generate agent Markdown. You configure `carter.yaml`, and the templates produce consistent, customized agent instructions.

**carter-ops** is the protocol for write operations (git commits, pushes, Jira comments). It ensures you always see a plan before anything is executed.

---

## Step 1: Install Carter

First, install the unified `carter` CLI once with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git
```

This puts a single `carter` command on your PATH. From there you have two paths depending on how you want to use Carter:

### Path A: Global Install (system-level)

This copies agent files to `~/.copilot/` so they're available in every VS Code workspace.

```bash
carter install
```

### Path B: Workspace Scaffold (per-project)

This generates customized agents from templates into a specific workspace directory.

```bash
# Create a new workspace
carter init ~/my-workspace --name "my-project"
```

**What `carter init` creates** (agent/instruction locations depend on `target` in
`carter.yaml`; the tree below shows the default `target: copilot`):

```
my-workspace/
├── .carter/
│   ├── carter.yaml           ← Your configuration (drives everything)
│   ├── knowledge/            ← Learnings captured during work
│   │   ├── lessons-learned.md
│   │   ├── gotchas.md
│   │   ├── tools.md
│   │   ├── decisions.md
│   │   └── patterns.md
│   └── state/                ← Plans and session checkpoints
│       ├── plans/active/
│       ├── plans/completed/
│       └── sessions/
└── .github/                  ← Copilot/VS Code discovery paths
    ├── agents/               ← Generated from templates
    │   ├── carter-maestro.md
    │   ├── carter-architect.md
    │   ├── carter-engineer.md
    │   ├── carter-devops.md
    │   ├── carter-pm.md
    │   ├── carter-learner.md
    │   └── carter-narrator.md    ← External-facing content + redaction agent
    └── copilot-instructions.md   ← Generated global instructions (skipped if it exists)
```

> **Discovery paths by target.** Agents and instructions are written where each
> tool loads them. With `target: opencode`, `carter init` instead writes
> `.opencode/agents/*.md` and `AGENTS.md` (project root). With `target: all`, it
> writes both sets. Carter-owned `carter-*` agents are refreshed by
> `carter update`; instruction files are only created when absent, so your edits
> are preserved.

### Understanding carter.yaml

This is the file that drives all template rendering. Key sections:

```yaml
# What personality should Carter have?
personality:
  skepticism: scaled    # off | scaled | always
  style: reviewer       # helpful | reviewer | terse

# Which agents to generate
agents:
  - maestro
  - architect
  - engineer
  - devops
  - pm
  - learner
  - narrator

# Should Carter review your code before you push?
quality_gate:
  enabled: true
  max_iterations: 2     # How many review rounds max

# Test-driven development enforcement
tdd:
  strict: false          # true = always write tests first
  spec_handoff: true     # Document contracts before complex work
```

When you change `carter.yaml`, regenerate with:

```bash
carter update .
```

---

## Step 2: Your First Interaction

### Example 1: Non-Operational Task — Design an API

Non-operational tasks involve thinking and producing artifacts — nothing external is modified.

```
@carter-maestro I need to design a REST API for a task management app.
It should support users, projects, and tasks with role-based access.
```

**What happens behind the scenes:**

1. Maestro receives your message
2. It recognizes this as a system design task (keywords: "design", "API", "architecture")
3. It routes to **carter-architect**
4. Architect produces the deliverable using its domain expertise

**Example response:**

```
Carter (Maestro → Architect):

## Resource Model

| Resource | Key Fields | Relationships |
|----------|-----------|---------------|
| User     | id, email, name, role | has many Projects |
| Project  | id, name, owner_id | has many Tasks |
| Task     | id, title, status, assignee_id | belongs to Project |

## Core Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST   | /api/v1/auth/login | Public | Authenticate, return JWT |
| GET    | /api/v1/projects | User | List user's projects |
| POST   | /api/v1/projects/:id/tasks | Member | Create task |

Roles are enforced via middleware that checks JWT claims against project membership.
```

**Key takeaway:** No commands ran. No files changed. Maestro identified the domain, routed to the specialist, and Architect used its knowledge to produce the design.

---

### Example 2: Operational Task — Commit and Push Code

Operational tasks modify external state. They use the `ops:` prefix and follow a strict plan → approve → execute flow.

```
@carter-maestro ops: create a feature branch, commit src/auth.py, and push.
Use PROJ-42 as the ticket reference.
```

**What happens:**

1. Maestro sees the `ops:` prefix and enters operational mode
2. It **assesses** current state (runs `git status`, `git log`)
3. It **plans** — shows you the exact commands with bot attribution
4. It **waits for your approval** before executing anything
5. After approval, it **executes** the commands
6. It **audits** — logs the operation
7. It **reports** — tells you what happened (commit SHA, branch name)

**Example plan shown to you:**

```
**Operation:** git-flow
**Branch:** feature/PROJ-42-auth-module
**Message:** feat(auth): add authentication module
**Attribution:** carter-bot <carter-bot@users.noreply.github.com>, signed

Commands:
1. git checkout main && git pull origin main
2. git checkout -b feature/PROJ-42-auth-module
3. git add src/auth.py
4. git commit --author='carter-bot <...>' -S -m "feat(auth): add authentication module"
5. git push -u origin feature/PROJ-42-auth-module

Approve?
```

You say "yes" and it executes. You say "no" or ask for changes, and it revises the plan.

**Key takeaway:** You always see exactly what will happen before it happens. The bot attribution means you can always tell which commits came from Carter vs. you.

---

### Example 3: Quality Gate — Review Before Push

After making changes, ask Carter to review before you push:

```
@carter-maestro review my changes before pushing
```

**What happens:**

1. Maestro identifies the scope (which files changed, how many)
2. It dispatches reviewers:
   - **carter-engineer** reviews code quality, test coverage, security
   - **carter-architect** reviews design (only if >5 files or structural changes)
3. Reviewers report findings with severity:
   - 🚨 **Blocking** — must fix before push
   - ⚠️ **Suggestion** — should consider
   - 💡 **Nitpick** — informational
4. If blocking issues exist, it recommends fixes and offers to re-review

**Example output:**

```
## Review: auth module (3 files)

### 🚨 Blocking (1)
1. [src/auth.py:42] — No input validation on email parameter. SQL injection risk.

### ⚠️ Suggestions (2)
1. [src/auth.py:15] — Consider extracting JWT config to environment variables
2. [tests/test_auth.py:8] — Missing test for expired token scenario

### 💡 Nitpicks (1)
1. [src/auth.py:3] — Unused import: `from datetime import date`

**Verdict**: Fix 1 blocking issue
```

---

## Step 3: Understanding Agent Boundaries

Each agent has strict rules about what it will and won't do. This prevents confused output:

| Agent | Does | Does NOT |
|-------|------|----------|
| Architect | Design systems, ADRs, API contracts | Write code, configure CI |
| Engineer | Write code, tests, reviews | Design architecture, write pipelines |
| DevOps | Pipelines, Terraform, Docker | Write application code |
| PM | Plans, roadmaps, risk assessment | Write code, design systems |
| Learner | Research, explain, document | Write production code |

**Why this matters:** If you ask the engineer to "design the system architecture", it will recognize that's not its job and tell you to ask the architect instead. This keeps each agent focused and prevents hallucinated expertise.

---

## Step 4: Working With Knowledge

Carter accumulates knowledge as you work. The knowledge system has two layers:

### Workspace Knowledge (`.carter/knowledge/`)

Created by `carter init`. These files capture learnings specific to your workspace:

| File | Purpose | Example Entry |
|------|---------|---------------|
| `lessons-learned.md` | Universal truths (append-only) | "Always check for nil before accessing nested struct fields" |
| `gotchas.md` | Known issues + workarounds | "Terraform 1.6 breaks X; pin to 1.5.7" |
| `tools.md` | Available toolchain | "MCP servers: github, terraform, atlassian" |
| `decisions.md` | Architecture decisions | "Chose PostgreSQL over DynamoDB because..." |
| `patterns.md` | Recurring conventions | "All API responses use envelope format" |

### How Knowledge Is Captured

Carter doesn't auto-write to knowledge files. After certain events, Maestro asks:

- After completing a plan → "Any learnings worth capturing?"
- After debugging for >10 minutes → "Record this as a gotcha?"
- After you correct Carter → "Record this correction?"

You confirm or decline. If you decline, Carter moves on immediately.

### Knowledge Is Never Overwritten

Running `carter update` re-renders agent files but **never touches knowledge files**. Your accumulated learnings are safe — they're yours, not generated.

---

## What to Try Next

| Task | How |
|------|-----|
| Design review | `@carter-architect review this system design: [paste]` |
| Code review | `@carter-engineer review src/auth.py for security` |
| Build a pipeline | `@carter-devops create a GitHub Actions workflow for Go` |
| Explain a concept | `@carter-learner explain Terraform state locking` |
| Create a plan | `@carter-pm create a project plan for adding OAuth2` |
| Multi-domain task | `@carter-maestro plan, implement, and deploy a new feature` |
| Review before push | `@carter-maestro review my changes` |
| Git operations | `@carter-maestro ops: create branch, commit, push` |

## Next Steps

- [carter-ops.md](carter-ops.md) — Full reference for write operations
- [memory-and-knowledge.md](memory-and-knowledge.md) — Deep dive on the knowledge system
- [testing.md](testing.md) — How to run and extend the test suite
