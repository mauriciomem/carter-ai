# Carter

[![CI](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml)

An AI assistant with expert personalities for software architecture, engineering, DevOps, learning, and project management.

Carter runs on **VS Code**, **Copilot CLI**, and **OpenCode CLI**. The same agents, skills, and MCP integrations work across all three surfaces.

## What Is Carter?

Carter is a **multi-agent AI system**. Instead of one generic assistant, you get specialized agents, each with focused expertise, strict boundaries, and a defined role. A central orchestrator (Maestro) routes your requests to the right specialist.

Think of it like a team: you don't ask the architect to write tests, and you don't ask the engineer to plan your roadmap.

**Two installation modes:**

| Mode | What It Does | When To Use |
|------|-------------|-------------|
| `carter install` | Copies agents/skills to `~/.copilot/` (system-level) | You want Carter available globally |
| `carter init` | Scaffolds a workspace with generated agents from templates | You want per-workspace customization |

## Quick Start

**Prerequisites:** [uv](https://docs.astral.sh/uv/) and Python 3.11+

### Recommended: Install the `carter` CLI (Global)

Install directly from the repository — no clone required:

```bash
# Install the unified carter CLI as a global tool
uv tool install git+https://github.com/mauriciomem/carter-ai.git

# (later) upgrade in place
uv tool upgrade carter-ai
```

`pipx` works too:

```bash
pipx install git+https://github.com/mauriciomem/carter-ai.git
```

This gives you a single `carter` command that provides everything:

```bash
carter install            # System-level install to ~/.copilot/ (all targets)
carter install --mcp      # ...and configure MCP servers
carter init ~/my-workspace --name "my-project"   # Per-project scaffold
carter ops --list         # List carter-ops write operations
```

### System-Level Install (Global)

Install Carter's agents, skills, instructions, knowledge base, and MCP
configuration into `~/.copilot/` (and/or OpenCode):

```bash
carter install                    # all targets
carter install --target copilot   # Copilot only
carter install --mcp              # include MCP servers
carter install --bot-name my-bot  # custom git attribution
carter install --uninstall        # remove
```

### Workspace-Level Scaffold (Per-Project)

```bash
# Initialize a workspace (creates .carter/ config + generates agents from templates)
carter init ~/my-workspace --name "my-project"
```

This generates:
- `.carter/carter.yaml` — configuration that drives all template rendering
- `.carter/knowledge/` — knowledge files for capturing learnings
- `.carter/state/` — plans, sessions, checkpoints
- `agents/` — generated agent files (from Jinja2 templates)
- `instructions/copilot-instructions.md` — generated global instructions

### From a Local Checkout (Development)

```bash
git clone https://github.com/mauriciomem/carter-ai.git ~/carter-ai
cd ~/carter-ai

# Editable install of the carter CLI
uv venv && source .venv/bin/activate
uv pip install -e .

# Legacy bootstrap (delegates to `carter install`):
uv run install.py      # or ./install.sh
```

### Required Environment Variables

Set these before installing (add to `~/.zshrc` or `~/.bashrc`):

```bash
export GITHUB_TOKEN="ghp_your_token"
export TF_TOKEN="your_hcp_terraform_token"
export ATLASSIAN_API_TOKEN="your_atlassian_token"
export ATLASSIAN_EMAIL="you@company.com"
export ATLASSIAN_URL="https://your-domain.atlassian.net"
```

See [.env.example](.env.example) for the full list.

## Getting Started

After installation, see the [Getting Started Walkthrough](docs/getting-started.md) for:

1. **Non-operational task** — Ask Maestro to design an API, watch it route to the right specialist
2. **Operational task** — Ask Maestro to commit and push code with the `ops:` protocol
3. **Workspace scaffolding** — Use `carter init` to create a customized workspace

## Usage

### Through the Orchestrator

```
@carter-maestro help me design a microservice for user authentication
```

Maestro analyzes your request and routes to the right specialist or chains multiple specialists for cross-domain tasks.

### Direct Agent Access

Maestro is the primary orchestrator; the specialists are **subagents**. Invoke
any of them directly by `@`-mention:

```
@carter-architect review this architecture
@carter-engineer review this code for security issues
@carter-devops create a GitHub Actions pipeline for this Go project
@carter-learner explain how Terraform state locking works
@carter-pm create a project plan with WBS for this initiative
```

### Quality Gate (Review Before Push)

When you're ready to push, ask for a review:

```
@carter-maestro review my changes before I push
```

Carter dispatches reviewers (engineer for code quality, architect for design) who report findings with severity levels (🚨 Blocking, ⚠️ Suggestion, 💡 Nitpick). Configurable via `carter.yaml`.

### Copilot CLI

Maestro is the primary agent you launch; reach specialists by `@`-mention:

```bash
copilot --agent carter-maestro -i "Help me plan a new API"
copilot --agent carter-maestro -p "@carter-devops create a Terraform module for S3" --allow-all
```

## Architecture

```
User
  │
  ├── @carter-maestro (orchestrator)
  │     ├─→ @carter-architect   (design, trade-offs, ADRs)
  │     ├─→ @carter-engineer    (code, tests, reviews)
  │     ├─→ @carter-devops      (CI/CD, IaC, containers)
  │     ├─→ @carter-learner     (research, explanation)
  │     ├─→ @carter-pm          (planning, risk, roadmaps)
  │     └─→ @carter-narrator    (external content, redaction)
  │
  └── @-mention any specialist directly
```

### Agents

| Agent | Domain | Key Capabilities |
|-------|--------|-----------------|
| **Maestro** | Orchestration, routing, quality gates | Routes requests, triggers reviews, captures knowledge |
| **Architect** | System design, cloud, trade-offs | ADRs, diagrams, API contracts, design review |
| **Engineer** | Code quality, testing, patterns | TDD, code review, refactoring, security checks |
| **DevOps** | CI/CD, IaC, containers, git | Pipelines, Terraform, Packer, deployment |
| **Learner** | Explanation, research, memory | Documentation, mistake capture, topic research |
| **PM** | Planning, risk, agile | WBS, roadmaps, sprint planning, risk assessment |

> A 7th agent, **Narrator**, reframes and redacts external-facing content (PR
> descriptions, Jira comments, docs, announcements). It is installed by both
> `carter install` and `carter init`, and applies non-negotiable redaction rules
> before anything leaves the workspace (see [ADR-0001](docs/adr/0001-narrator-content-suite.md)).

### MCP Servers

| Server | Purpose |
|--------|---------|
| `carter-github` | Repos, PRs, issues, Actions |
| `carter-terraform` | Terraform configs, state, plans |
| `carter-atlassian` | Jira issues, Confluence pages |

## Carter-Ops

Carter-ops handles **write operations** (git, GitHub, Jira) with bot attribution and an approval gate. It separates reads (direct commands) from writes (plan → approve → execute → audit).

Trigger with the `ops:` prefix:

```
@carter-maestro ops: create a feature branch, commit my changes, and push
```

The agent shows you the exact commands it will run, waits for your approval, executes with bot attribution, and logs the operation. Under the hood it calls the `carter ops` subcommand:

```bash
carter ops --list                                   # available operations
carter ops git-flow --branch feature/x \
  --message "feat: x" --dry-run                     # preview
```

See [docs/carter-ops.md](docs/carter-ops.md) for the full reference.

## Template System (Carter v2)

Carter v2 introduces a **template-driven generation system**. Instead of hand-editing agent Markdown files, you configure `carter.yaml` and regenerate:

```bash
# Edit configuration
vim .carter/carter.yaml

# Regenerate agent files from templates
carter update .

# Verify workspace integrity
carter check .
```

### What's Configurable

| Feature | Config Key | Effect |
|---------|-----------|--------|
| Skepticism level | `personality.skepticism` | How much Carter challenges your decisions |
| Quality gates | `quality_gate.enabled` | Multi-agent review before push |
| TDD strictness | `tdd.strict` | Force test-first workflow |
| Redaction | `redaction.enabled` | Sanitize external-facing content |
| Agent roster | `agents` | Which agents to generate |

Templates use **Jinja2 inheritance** — a base template defines the structure (`<identity>`, `<role>`, `<boundaries>`), and each agent template fills in its specific content. Conditional blocks mean unused features don't appear in the rendered output.

See `templates/` for the template source and `carter.yaml` for the full schema.

## Installer (System-Level)
```bash
# Install all targets (VS Code + Copilot CLI + OpenCode)
carter install

# Install specific target
carter install --target copilot
carter install --target opencode

# Include MCP server configuration
carter install --mcp

# Custom bot name for git attribution
carter install --bot-name "my-bot"

# Uninstall
carter install --uninstall
```

> The legacy `uv run install.py` / `./install.sh` entry points still work —
> they are thin shims that delegate to `carter install`.

### What the Installer Does

1. Detects OS and checks prerequisites
2. Backs up existing Carter files
3. Copies agents and skills to `~/.copilot/` and `~/.config/opencode/`
4. Generates `~/.carter/config.toml` with auto-detected signing key and bot name
   (write operations run via the `carter ops` subcommand — no separate wrapper)
5. Configures MCP servers in VS Code, Copilot CLI, and OpenCode (only with `--mcp`)
6. Initializes the knowledge base at `~/.copilot/knowledge/`
7. Writes a manifest for idempotent updates and clean uninstall

### Updating

```bash
uv tool upgrade carter-ai
carter install
```

The installer detects changes via SHA-256 file hashing. Only modified files are updated.

## Memory and Knowledge

Carter learns from experience through a structured knowledge system:

- **Workspace knowledge** (`.carter/knowledge/`) — Per-workspace learnings: lessons, gotchas, tools, decisions, patterns
- **System knowledge** (`~/.copilot/knowledge/`) — Global curated entries promoted via `@carter-maestro distill`
- **Platform memory** (`/memories/`) — VS Code's built-in memory tool (auto-loaded into context)

Three skills drive the lifecycle: `carter-mistakes` (capture) → `carter-distill` (promote) → `carter-reflect` (improve agents from patterns).

See [docs/memory-and-knowledge.md](docs/memory-and-knowledge.md) for the full reference.

## Testing

```bash
# Run all tests (requires the venv)
source .venv/bin/activate
python -m pytest tests/ -v

# Or without a venv
uv run --with pytest pytest tests/ -v
```

The test suite covers:
- **Installer tests** (`tests/test_install.py`) — file installation, idempotency, JSON merging, manifest management, memory directories
- **Scaffold tests** (`tests/test_scaffold.py`) — template rendering, config validation/merging, workspace initialization, discovery-path output, quality gates, narrator redaction
- **Parity tests** (`tests/test_parity.py`) — invariants that must not drift between the static agent files and their templates
- **Carter-ops tests** (`tests/ops/test_operations.py`) — CLI parsing, operation dry-runs/execution, GitHub/Jira/git operations, config and audit subcommands

211 tests in total, run on every push and PR via [GitHub Actions](.github/workflows/ci.yml). See [docs/testing.md](docs/testing.md) for the full testing guide.

## Project Structure

```
carter-ai/
├── carter/                 # Carter v2 CLI package
│   ├── cli.py              # Entry points: install, init, update, check, ops
│   ├── installer.py        # System-level installer (used by `carter install`)
│   ├── resources.py        # Resolves bundled data (wheel) vs checkout
│   ├── config.py           # carter.yaml loading + validation
│   ├── scaffold.py         # Jinja2 rendering engine
│   ├── state.py            # .carter/ directory management
│   └── ops/                # carter-ops executor (`carter ops`)
│       ├── carter_ops.py   # Subcommand entry point
│       ├── operations/     # Plugin-based operations
│       ├── config.py       # Config loader
│       ├── attribution.py  # Bot attribution helpers
│       └── output.py       # Structured JSON output
├── templates/              # Jinja2 agent + instruction templates
│   ├── base_agent.md.j2    # Base template (inheritance)
│   ├── agents/             # Per-agent templates (extend base)
│   └── instructions/       # Global instructions template
├── install.py              # Legacy bootstrap shim → `carter install`
├── install.sh              # Wrapper script
├── agents/                 # Source-of-truth agent definitions
├── skills/                 # Skill definitions (hand-maintained)
├── knowledge/              # Knowledge base templates
├── mcp/                    # MCP server config templates
├── instructions/           # Global instructions source
├── docs/                   # Documentation
└── tests/                  # All test suites
    ├── test_install.py     # Installer tests
    ├── test_scaffold.py    # Template + scaffold tests
    └── ops/                # Carter-ops tests
```

## Troubleshooting

### Agents not appearing in VS Code
Restart VS Code after installation. Agents are loaded from `~/.copilot/agents/` on startup.

### MCP server conflicts
If you have existing MCP servers (e.g., `github`), Carter installs alongside them as `carter-github`. Remove the original to avoid duplicate tools, or keep both if they use different credentials.

### Missing environment variables
Run `uv run install.py -v` to see which variables are missing and how to set them.

### `carter` command not found
Make sure you've installed the package: `uv pip install -e .` from the carter-ai directory, with your venv activated.

## License

GPL-3.0
