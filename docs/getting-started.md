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

**Strictness policy** is Carter's enforced safety posture. Each agent has a
deny-by-default tool allowlist, and actions are gated by risk category. One
`policy.level` setting (`guarded` / `strict`) decides how hard the in-scope gates
bite — see [strictness-policy.md](strictness-policy.md).

---

## Step 1: Install Carter

First, install the unified `carter` CLI once with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git
```

This installs a single `carter` executable into uv's tool bin directory
(`~/.local/bin` on macOS and Linux). **That directory may not be on your `PATH`
yet** — `uv` prints a warning if so. Put it on your PATH once:

```bash
uv tool update-shell      # adds the tool bin dir to your shell startup file
exec $SHELL               # reload the shell (or just open a new terminal)
carter --version          # verify: carter, version 2.0.0a1
```

> **`bash: carter: command not found`?** The install succeeded but `~/.local/bin`
> isn't on your `PATH`. Run `uv tool update-shell` and reload your shell (above),
> or for the current shell only: `export PATH="$HOME/.local/bin:$PATH"`.
> Alternatively, run the bundled installer straight from a repo checkout without
> touching your PATH: `./install.sh` (equivalent to `carter install`).

From there you have two paths depending on how you want to use Carter:

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

# Choose where agents are written, and the agent-name suffix
carter init ~/my-workspace --target all --agent-suffix local
#   --target copilot|opencode|all   (default copilot)
#   --agent-suffix <suffix>         (default local; "" for none)
```

> At both levels (`guarded`/`strict`) the narrator's redaction pass is **forced**
> regardless of `redaction.enabled`, so a rule-less narrator can never ship. If you
> set `redaction.enabled: false`, `carter check` flags the contradiction.

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
│       ├── plans/active/         ← One dir per plan: <NNN-slug>/README.md (+ step-NN.md)
│       ├── plans/completed/
│       └── sessions/            ← checkpoint.md (session recovery cursor)
└── .github/                  ← Copilot/VS Code discovery paths
    ├── agents/               ← Generated from templates
    │   ├── carter-maestro-local.md
    │   ├── carter-architect-local.md
    │   ├── carter-engineer-local.md
    │   ├── carter-devops-local.md
    │   ├── carter-pm-local.md
    │   ├── carter-learner-local.md
    │   └── carter-narrator-local.md   ← External-facing content + redaction agent
    └── copilot-instructions.md   ← Generated global instructions (skipped if it exists)
```

> **Why the `-local` suffix?** Workspace agents carry a suffix (default `local`)
> so they're distinct from any globally-installed Carter agents (`carter install`
> writes `carter-engineer`; `carter init` writes `carter-engineer-local`). Set
> `agent_suffix` in `carter.yaml` to change it, or `agent_suffix: ""` to use the
> same names as global. The suffix is applied to filenames, Maestro's routing,
> and cross-references — so invocation stays consistent.

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

# Suffix that distinguishes these workspace agents from globally-installed ones
# (carter-engineer-local). Use "" for no suffix (same names as global).
agent_suffix: local

# Where to write agents/instructions: copilot | opencode | all
target: copilot

# Risk-based strictness policy (ADR-0005 / ADR-0010). One knob; deny-by-default per agent.
policy:
  level: guarded        # guarded | strict
  unknown_tool: ask     # gate for a tool not in the risk map: allow | ask | deny
  overrides: {}         # category -> gate, e.g. {remote-write: deny} to tighten remote-write
  audit_overrides: true # log escape-hatch overrides via `carter ops`

# Per-agent model (ADR-0010 D2). Thinkers run on Opus, implementers on a cheaper
# Sonnet; resolved overrides > tier > default. One model: string per agent (never an
# array). Haiku is opt-in via overrides only.
models:
  default:      { copilot: "Claude Opus 4.8",   opencode: "anthropic/claude-opus-4-8" }
  thinkers:     { copilot: "Claude Opus 4.8",   opencode: "anthropic/claude-opus-4-8" }
  implementers: { copilot: "Claude Sonnet 4.6", opencode: "anthropic/claude-sonnet-4-6" }
  overrides: {}         # per-agent, e.g. {engineer: {copilot: "Claude Haiku 4.5", opencode: "anthropic/claude-haiku-4-5"}}

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

> **Reasoning effort is global, not per-agent.** No target exposes a per-agent effort
> field, so Carter emits none — effort is the harness's global knob
> (`copilot --effort high`, a VS Code/OpenCode setting). Default to **`high`** (the safe
> all-rounder), and raise it per-session to `xhigh` for thinker-heavy work (RFC/ADR/plan
> authoring). `carter check` prints which model each agent pins, with the caveat that
> Carter can't verify your subscription includes it.

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

## Releasing

Carter uses **automated SemVer releases** driven entirely by your commit messages —
there is no version number to bump by hand (ADR-0009). The git tag is the single
source of truth: `carter --version` and the built wheel both derive from the latest
`vX.Y.Z` tag via `hatch-vcs`. An untagged checkout reports a dev version like
`0.1.1.dev3+g<sha>`.

### How a release happens

Every push to `main` runs [`.github/workflows/release.yml`](../.github/workflows/release.yml),
which inspects the [Conventional Commits](https://www.conventionalcommits.org/) since
the last tag, computes the next version, creates the tag, updates `CHANGELOG.md`, and
publishes a GitHub Release with generated notes.

| Commit type | Example | Version effect (pre-1.0) |
|-------------|---------|--------------------------|
| `fix:` | `fix: handle missing settings.json` | PATCH — `0.1.0 → 0.1.1` |
| `feat:` | `feat: add opencode MCP target` | MINOR — `0.1.1 → 0.2.0` |
| `feat!:` / `BREAKING CHANGE:` | `feat!: drop python 3.10` | breaking — stays in `0.y` until 1.0 is declared |
| `docs:` `chore:` `refactor:` `test:` `ci:` `build:` `style:` | `docs: fix typo` | **no release** |

> The project is intentionally **pre-1.0** (`0.y.z`): the API is still unstable. The
> baseline tag is `v0.1.0`; `1.0.0` will be cut deliberately when we commit to API
> stability, not automatically.

### Pinning an exact release

Install a specific tagged version (reproducible, won't drift):

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git@v0.1.0
carter --version   # carter, version 0.1.0
```

Omit `@vX.Y.Z` to track the default branch's latest (a dev version).

## Next Steps

- [strictness-policy.md](strictness-policy.md) — Tutorial: gating actions by risk with `policy.level`
- [carter-ops.md](carter-ops.md) — Full reference for write operations
- [memory-and-knowledge.md](memory-and-knowledge.md) — Deep dive on the knowledge system
- [testing.md](testing.md) — How to run and extend the test suite
