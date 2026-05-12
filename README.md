# Carter

An AI assistant with expert personalities for software architecture, engineering, DevOps, learning, and project management.

Carter runs on **VS Code**, **Copilot CLI**, and **OpenCode CLI**. The same agents, skills, and MCP integrations work across all three surfaces.

## Quick Start

**Prerequisites:** [uv](https://docs.astral.sh/uv/) and Python 3.11+

```bash
# Clone
git clone git@github.com:mauriciomem/carter-ai.git ~/carter-ai
cd ~/carter-ai

# Install (all targets)
uv run install.py

# Or use the wrapper
./install.sh
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

After installation, see the [Getting Started Walkthrough](docs/getting-started.md) for two end-to-end examples:

1. **Non-operational task** — Ask Maestro to design an API, watch it route to the right specialist and produce an architecture
2. **Operational task** — Ask Maestro to commit and push code, watch it invoke carter-ops with dry-run approval

Both examples use the Copilot CLI and show the full conversation flow.

## Usage

### Through the Orchestrator

```
@carter-maestro help me design a microservice for user authentication
```

Maestro analyzes your request and routes to the right specialist or chains multiple specialists for cross-domain tasks.

### Direct Agent Access

```
@carter-architect review this architecture
@carter-engineer review this code for security issues
@carter-devops create a GitHub Actions pipeline for this Go project
@carter-learner explain how Terraform state locking works
@carter-pm create a project plan with WBS for this initiative
```

### Copilot CLI

```bash
copilot --agent carter-maestro -i "Help me plan a new API"
copilot --agent carter-devops -p "Create a Terraform module for S3" --allow-all
```

## Architecture

```
User
  │
  ├── @carter-maestro (orchestrator)
  │     ├─→ @carter-architect
  │     ├─→ @carter-engineer
  │     ├─→ @carter-devops
  │     ├─→ @carter-learner
  │     └─→ @carter-pm
  │
  └── Direct access to any agent
```

### Agents

| Agent | Domain | Skills |
|-------|--------|--------|
| **Maestro** | Orchestration, routing | triage, distill |
| **Architect** | System design, cloud, trade-offs | design-review, diagram, adr |
| **Engineer** | Code quality, testing, patterns | code-review, test-first, python, golang |
| **DevOps** | CI/CD, IaC, containers, git | pipeline, terraform, packer, python, golang |
| **Learner** | Explanation, research, memory | explain, mistakes, research |
| **PM** | Planning, risk, agile | plan, risk, atlassian |

### MCP Servers

| Server | Purpose |
|--------|---------|
| `carter-github` | Repos, PRs, issues, Actions |
| `carter-terraform` | Terraform configs, state, plans |
| `carter-atlassian` | Jira issues, Confluence pages |

## Carter-Ops

Carter-ops is a deterministic CLI executor for write operations (Git and Jira). It separates reads (handled by MCP servers and direct commands) from writes (handled by carter-ops with a two-phase approval flow).

The protocol is enforced by a single `carter-ops` skill that every agent loads when the user prefixes a request with `ops:`. A one-liner in each agent file triggers the skill, which contains the complete workflow, command reference, and anti-fabrication rules in one place.

```bash
# Dry-run — shows what would happen
carter-ops git-commit --message "feat: add auth" --files src/auth.py --dry-run

# Execute — does it after approval
carter-ops git-commit --message "feat: add auth" --files src/auth.py --execute
```

All output is structured JSON. Git commits are attributed to `carter-bot` and signed with your SSH key. Jira comments include a bot footer.

Operations: `git-branch`, `git-commit`, `git-push`, `git-flow` (composite), `jira-comment`, `jira-create`, `jira-update` (composite).

See [docs/carter-ops.md](docs/carter-ops.md) for the full reference.

## Installer

```bash
# Install all targets (VS Code + Copilot CLI + OpenCode)
uv run install.py

# Install specific target
uv run install.py --target copilot
uv run install.py --target opencode

# Include MCP server configuration
uv run install.py --mcp

# Custom bot name for git attribution
uv run install.py --bot-name "my-bot"

# Uninstall
uv run install.py --uninstall

# Verbose output
uv run install.py -v

# Debug output
uv run install.py -vv
```

### What the Installer Does

1. Detects OS and checks prerequisites
2. Backs up existing Carter files
3. Copies agents and skills to `~/.copilot/` and `~/.config/opencode/`
4. Installs carter-ops to `~/.carter/ops/` with a wrapper at `~/.local/bin/carter-ops`
5. Generates `~/.carter/config.toml` with auto-detected signing key and bot name
6. Configures MCP servers in VS Code, Copilot CLI, and OpenCode (only with `--mcp`)
7. Initializes the knowledge base at `~/.copilot/knowledge/`
8. Writes a manifest for idempotent updates and clean uninstall

### Updating

```bash
cd ~/carter-ai
git pull
uv run install.py
```

The installer detects changes via file hashing. Only modified files are updated.

## Knowledge Base

Carter learns from experience through a two-tier memory system:

- **Fast capture** (`/memories/`) — Quick notes during conversations
- **Curated knowledge** (`~/.copilot/knowledge/`) — Structured entries promoted via `@carter-maestro distill`

Knowledge files: `decisions.md`, `mistakes.md`, `patterns.md`, `debugging.md`, `infrastructure.md`, `project-history.md`

## Testing

The test suite has 97 tests across two test files — installer tests (`test_install.py`) and carter-ops tests (`tests/ops/test_operations.py`) — covering file installation, idempotency, JSON merging, manifest management, ops CLI parsing, operation dry-runs, and mocked execution.

```bash
# Run all tests
uv run --with pytest pytest tests/ -v

# Run a specific class
uv run --with pytest pytest tests/test_install.py::TestMCPMerging -v
```

See [docs/testing.md](docs/testing.md) for the full testing guide — test coverage details, fixture reference, and how to extend the suite.

## Project Structure

```
carter-ai/
├── install.py              # Installer (PEP 723, stdlib only)
├── install.sh              # Wrapper script
├── agents/                 # Agent definitions (6 agents)
├── skills/                 # Skill definitions (18 skills)
├── ops/                    # carter-ops CLI executor
│   ├── carter_ops.py       # Entry point
│   ├── operations/         # Plugin-based operations
│   ├── config.py           # Config loader (TOML + env vars)
│   ├── attribution.py      # Bot attribution helpers
│   └── output.py           # Structured JSON output
├── knowledge/              # Knowledge base templates
├── mcp/                    # MCP server config templates
│   ├── copilot/            # VS Code format
│   └── opencode/           # OpenCode format
├── instructions/           # Global instructions
├── docs/                   # Documentation and design logs
└── tests/                  # Installer + ops tests
```

## Troubleshooting

### Agents not appearing in VS Code
Restart VS Code after installation. Agents are loaded from `~/.copilot/agents/` on startup.

### MCP server conflicts
If you have existing MCP servers (e.g., `github`), Carter installs alongside them as `carter-github`. Remove the original to avoid duplicate tools, or keep both if they use different credentials.

### Missing environment variables
Run `uv run install.py -v` to see which variables are missing and how to set them.

## License

GPL-3.0
