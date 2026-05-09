# Carter

An AI assistant with expert personalities for software architecture, engineering, DevOps, learning, and project management.

Carter runs on **VS Code Copilot**, **Copilot CLI**, and **OpenCode CLI** — the same agents, skills, and MCP integrations work across all three surfaces.

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

## Usage

### Through the Orchestrator

```
@carter-maestro help me design a microservice for user authentication
```

Maestro analyzes your request and routes to the right specialist — or chains multiple specialists for cross-domain tasks.

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
| **DevOps** | CI/CD, IaC, containers, git | pipeline, terraform, git-strategy, python, golang |
| **Learner** | Explanation, research, memory | explain, mistakes, research |
| **PM** | Planning, risk, agile | plan, risk |

### MCP Servers

| Server | Purpose |
|--------|---------|
| `carter-github` | Repos, PRs, issues, Actions |
| `carter-terraform` | Terraform configs, state, plans |
| `carter-atlassian` | Jira issues, Confluence pages |

## Installer

```bash
# Install all targets (VS Code + Copilot CLI + OpenCode)
uv run install.py

# Install specific target
uv run install.py --target copilot
uv run install.py --target opencode

# Uninstall
uv run install.py --uninstall

# Verbose output
uv run install.py -v

# Debug output
uv run install.py -vv
```

### What the Installer Does

1. Detects OS and checks prerequisites
2. Validates environment variables for MCP servers
3. Backs up existing Carter files
4. Copies agents and skills to `~/.copilot/` and `~/.config/opencode/`
5. Configures MCP servers in VS Code, Copilot CLI, and OpenCode
6. Initializes the knowledge base at `~/.copilot/knowledge/`
7. Writes a manifest for idempotent updates and clean uninstall

### Updating

```bash
cd ~/carter-ai
git pull
uv run install.py
```

The installer detects changes via file hashing — only modified files are updated.

## Knowledge Base

Carter learns from experience through a two-tier memory system:

- **Fast capture** (`/memories/`) — Quick notes during conversations
- **Curated knowledge** (`~/.copilot/knowledge/`) — Structured entries promoted via `@carter-maestro distill`

Knowledge files: `decisions.md`, `mistakes.md`, `patterns.md`, `debugging.md`, `infrastructure.md`, `project-history.md`

## Testing

```bash
uv run --with pytest pytest tests/ -v
```

## Project Structure

```
carter-ai/
├── install.py              # Installer (PEP 723, stdlib only)
├── install.sh              # Wrapper script
├── agents/                 # Agent definitions (6 agents)
├── skills/                 # Skill definitions (17 skills)
├── knowledge/              # Knowledge base templates
├── mcp/                    # MCP server config templates
│   ├── copilot/            # VS Code format
│   └── opencode/           # OpenCode format
├── instructions/           # Global instructions
├── prompts/                # Original design prompts
├── docs/                   # Plan and conversation log
└── tests/                  # Installer tests
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
