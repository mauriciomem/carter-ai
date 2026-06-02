# Carter — Implementation Plan (As-Built)

> AI assistant with expert personalities for software architecture, engineering, DevOps, learning, project management, and output redaction.

> **Status:** Shipped. This document reflects the system as built and installed today
> via the unified `carter` CLI (`uv tool install`). Sections describe what exists in
> the codebase, not deferred or abandoned ideas.

---

## 1. Overview

Carter is a multi-personality AI assistant built on top of the VS Code Copilot agent system, Copilot CLI, and OpenCode CLI. It provides seven specialized agents, each with domain-specific skills, backed by MCP servers for reads, a deterministic `carter ops` executor for writes, and a persistent knowledge base for learning from experience. Everything ships as a single installable Python package (`carter-ai`) exposing one `carter` command.

### Surfaces

| Surface | Agent/Skill Source | MCP Config |
|---|---|---|
| VS Code Copilot | `~/.copilot/agents/`, `~/.copilot/skills/` | VS Code `settings.json` → `mcp.servers` |
| Copilot CLI | `~/.copilot/agents/`, `~/.copilot/skills/` (shared) | `~/.copilot/mcp-config.json` via `copilot mcp add` |
| OpenCode CLI | `~/.config/opencode/agents/`, `~/.config/opencode/skills/` | `~/.config/opencode/opencode.json` → `mcp` |

### Name & Prefix

All Carter-owned files and config entries use the `carter-` prefix to avoid collisions with other agent systems.

---

## 2. Architecture

### 2.1 Orchestration Model

- **Hybrid runtime**: No custom orchestration code. Uses the native agent/skill systems of VS Code Copilot, Copilot CLI, and OpenCode.
- **Orchestrator + direct access**: One orchestrator agent (`carter-maestro`) routes to specialist agents. All specialist agents are also directly addressable by the user.
- **Multi-agent chaining**: Maestro can invoke agents sequentially, passing context between them for tasks that span domains.

### 2.2 Agent Architecture

```
User
  │
  ├── @carter-maestro (orchestrator)
  │     ├── runSubagent → @carter-architect
  │     ├── runSubagent → @carter-engineer
  │     ├── runSubagent → @carter-devops
  │     ├── runSubagent → @carter-learner
  │     └── runSubagent → @carter-pm
  │
  ├── @carter-architect (direct access)
  ├── @carter-engineer  (direct access)
  ├── @carter-devops    (direct access)
  ├── @carter-learner   (direct access)
  ├── @carter-pm        (direct access)
  └── @carter-narrator  (utility — output redaction)
```

### 2.3 File Placement

| Scope | Path | Purpose |
|---|---|---|
| User-level (Copilot) | `~/.copilot/agents/` | Agent definitions (shared VS Code + CLI) |
| User-level (Copilot) | `~/.copilot/skills/` | Skill definitions (shared VS Code + CLI) |
| User-level (Copilot) | `~/.copilot/instructions/` | Global instructions |
| User-level (Copilot) | `~/.copilot/knowledge/` | Curated knowledge base |
| User-level (OpenCode) | `~/.config/opencode/agents/` | OpenCode agent definitions |
| User-level (OpenCode) | `~/.config/opencode/skills/` | OpenCode skill definitions |
| Workspace-level | `.copilot/instructions.md` | Per-repo overrides (user-managed, not installed) |

---

## 3. Agents

### 3.1 Agent Definitions

| Agent | File | Mode | Temperature | MCP Access |
|---|---|---|---|---|
| Maestro | `carter-maestro` | `primary` (OpenCode) | 0.2 | None (delegates) |
| Architect | `carter-architect` | `agent` | 0.4 | GitHub (read), Terraform (read) |
| Engineer | `carter-engineer` | `agent` | 0.1 | GitHub (full), Terraform (read) |
| DevOps | `carter-devops` | `agent` | 0.1 | GitHub (full), Terraform (full) |
| Learner | `carter-learner` | `agent` | 0.3 | Confluence (read) |
| PM | `carter-pm` | `agent` | 0.2 | Jira (full), Confluence (full), GitHub (read) |
| Narrator | `carter-narrator` | `agent` | 0.1 | None (redacts agent output before display) |

- Model is not hardcoded — uses a `${CARTER_MODEL}` placeholder that resolves to the user's default or a configured value.
- Per-agent tool restrictions enforce least-privilege access to MCP servers.
- Agents are generated from Jinja2 templates (`templates/agents/*.md.j2`); the
  default agent set and personality are driven by `.carter/carter.yaml`.
- **Narrator** is a redaction utility agent (enabled via the `redaction` block in
  `carter.yaml`); it is generated from a template and has no source `.md` of its own.

### 3.2 Maestro Routing

The `carter-triage` skill classifies the user's request and delegates:

| Domain | Agent | Triggers |
|---|---|---|
| System design, architecture, trade-offs | @carter-architect | design, architecture, scalability, diagram, ADR |
| Code quality, implementation, testing | @carter-engineer | code, review, test, refactor, debug, Python, Go |
| Infrastructure, CI/CD, deployment, IaC | @carter-devops | deploy, pipeline, terraform, container, git, AWS |
| Learning, documentation, explanation | @carter-learner | explain, learn, document, research, why |
| Planning, project management, tracking | @carter-pm | plan, roadmap, risk, milestone, sprint, standup |

If a task spans multiple domains, Maestro chains agents sequentially, passing context between them. If uncertain, Maestro asks the user.

---

## 4. Skills

### 4.1 Skill Map

Twenty skills ship in `skills/` (source of truth), bundled into the wheel and
installed alongside the agents.

| Agent | Skill | Description |
|---|---|---|
| **Maestro** | `carter-triage` | Classify request, route to specialist agent(s) |
| | `carter-distill` | Promote `/memories/` notes to curated knowledge |
| | `carter-reflect` | Analyze accumulated memory/knowledge to improve agents & skills |
| **Architect** | `carter-design-review` | Analyze architecture for patterns, anti-patterns, security |
| | `carter-diagram` | Generate Mermaid architecture diagrams |
| | `carter-adr` | Create Architecture Decision Records |
| **Engineer** | `carter-code-review` | Review code for quality, patterns, security, testability |
| | `carter-test-first` | Generate tests before implementation (TDD workflow) |
| **DevOps** | `carter-pipeline` | Create/modify GitHub Actions workflows, git/gh strategy |
| | `carter-terraform` | Write/review Terraform configurations |
| | `carter-packer` | Build machine images with HashiCorp Packer |
| **Learner** | `carter-explain` | Break down complex topics into understandable parts |
| | `carter-mistakes` | Record mistakes and lessons learned to memory |
| | `carter-research` | Fetch and summarize official documentation |
| **PM** | `carter-plan` | Create project plans, WBS, task dictionaries |
| | `carter-risk` | Risk identification and mitigation planning |
| | `carter-atlassian` | Jira/Confluence best practices (stories, bugs, epics) |
| **Shared** | `carter-python` | Python coding standards and enforcement |
| | `carter-golang` | Go coding standards and enforcement |
| **Cross-cutting** | `carter-ops` | Deterministic write-operation protocol (`carter ops`) |

### 4.2 Language Skills (Shared by Engineer & DevOps)

Both `carter-python` and `carter-golang` are reference skills + checklist enforcers. They cover:

| Section | Python | Go |
|---|---|---|
| **Project structure** | `src/` layout, `pyproject.toml`, namespace packages | Standard Go layout, `cmd/`/`internal/`/`pkg/` |
| **Design patterns** | Dataclasses, protocols, ABC, DI, composition over inheritance | Interfaces, embedding, functional options, DI |
| **Testing** | pytest, fixtures, table-driven tests, `unittest.mock`, coverage | `testing` package, table-driven, testify, subtests, benchmarks |
| **Security** | OWASP top 10, `bandit`, input validation, `pip-audit` | `gosec`, input validation, `govulncheck` |
| **Code quality** | `ruff` (lint+format), `mypy` type hints, docstrings | `golangci-lint`, `go vet`, `gofmt`/`goimports`, godoc |
| **Error handling** | Exception hierarchy, custom exceptions, context managers | Error wrapping (`%w`), sentinel errors, custom error types |
| **Concurrency** | `asyncio`, `concurrent.futures` | Goroutines, channels, `sync`, context propagation |
| **Dependency mgmt** | `uv`, pinned deps, minimal dependencies | Go modules, `go.sum`, minimal dependencies |
| **Extensibility** | Plugin pattern, strategy pattern, registry pattern | Interfaces, plugin pattern, interface registries |

Sources: PEP 8, Effective Go, Google style guides (cited inline in each skill).

Each skill includes a **checklist prompt** — when invoked, it reviews code against the standards and flags violations.

---

## 5. MCP Servers

### 5.1 v1 Servers

| Server | Config Name | Purpose |
|---|---|---|
| GitHub | `carter-github` | Repos, PRs, issues, Actions |
| Terraform / HCP | `carter-terraform` | Terraform configs, state, plans |
| Atlassian | `carter-atlassian` | Jira issues, Confluence pages |

### 5.2 Naming & Conflict Handling

All MCP entries use the `carter-` prefix. This creates a clear ownership boundary:

- The installer **only** manages `carter-*` entries
- Non-prefixed entries are never modified
- If a non-prefixed server with the same base name exists (e.g., `github` alongside `carter-github`), the installer warns:

```
→ Configuring MCP servers...
  ⚠ Existing "github" server found in settings.json
    Carter will install as "carter-github" (separate entry).
    You may want to remove "github" to avoid duplicate tools.
  ✓ carter-github → settings.json
```

### 5.3 Per-Target MCP Configuration

| Target | Method | Config Location |
|---|---|---|
| VS Code | JSON merge into `mcp.servers` | `~/Library/Application Support/Code/User/settings.json` (macOS) or `~/.config/Code/User/settings.json` (Linux) |
| Copilot CLI | `copilot mcp add` / `copilot mcp remove` | `~/.copilot/mcp-config.json` (managed by CLI) |
| OpenCode | JSON merge into `mcp` | `~/.config/opencode/opencode.json` |

### 5.4 Credential Management

Credentials are **never** stored in config files. MCP configs reference environment variables:

```json
"carter-github": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
}
```

Required environment variables:

| Variable | Server/Tool | Required |
|---|---|---|
| `GITHUB_TOKEN` | carter-github | Yes |
| `TF_TOKEN` | carter-terraform | Yes |
| `ATLASSIAN_API_TOKEN` | carter-atlassian, carter-ops | Yes |
| `ATLASSIAN_EMAIL` | carter-atlassian, carter-ops | Yes |
| `ATLASSIAN_URL` | carter-atlassian, carter-ops | Yes |
| `JIRA_TOKEN` | carter-ops (Jira operations) | For Jira ops |

The installer validates these at install time and warns on missing values with setup instructions.

### 5.5 MCP Servers Deferred to v2

| Server | Notes |
|---|---|
| AWS | Larger blast radius, needs careful guardrails |
| Vault | Sensitive secrets management, needs dedicated security review |

---

## 6. Memory & Knowledge

### 6.1 Two-Tier Memory Model

| Tier | Location | Purpose | Lifecycle |
|---|---|---|---|
| **Fast capture** | `/memories/` (Copilot memory system) | Session notes, quick observations, in-progress context | Created during conversations, reviewed periodically |
| **Curated knowledge** | `~/.copilot/knowledge/` | Structured, topic-organized learnings | Promoted from fast capture via `carter-distill` |

### 6.2 Knowledge Base Structure

Initial topic files:

| File | Content |
|---|---|
| `decisions.md` | Architecture Decision Records, trade-off analyses |
| `mistakes.md` | Mistakes and lessons learned |
| `patterns.md` | Recurring design patterns and solutions |
| `debugging.md` | Debugging techniques and fixes |
| `infrastructure.md` | Infrastructure patterns, cloud configurations |
| `project-history.md` | Project timelines, milestones, outcomes |

### 6.3 Knowledge Entry Format

```markdown
## 2026-05-09 | Terraform state lock timeout
- **Context:** aws-infra repo, `terraform apply` on production
- **Mistake:** Forgot to release state lock after interrupted apply
- **Fix:** `terraform force-unlock <lock-id>`
- **Lesson:** Always check `terraform state list` before force operations
- **Tags:** terraform, aws, state
```

Each entry has: date, title, context, details, and tags for searchability.

### 6.4 Distill Workflow

The `carter-distill` skill (invoked via `@carter-maestro distill` or directly):

1. Reads all `/memories/` notes from recent sessions
2. Classifies each note into a knowledge topic
3. Checks for duplicates against existing knowledge entries
4. Appends new entries in the structured format
5. Suggests deleting processed `/memories/` notes
6. Runs **on-demand only** — the user controls what gets promoted

---

## 7. Global Instructions

File: `~/.copilot/instructions/copilot-instructions.md` (~25 lines)

Contents:
1. **Identity** — "You are Carter, an expert AI assistant."
2. **Communication style** — Concise, clear, cite sources, explain for junior-level understanding
3. **Ask-before-act** — At any doubt, ask for clarification before proceeding
4. **Memory protocol** — Record mistakes to `/memories/`, consult `~/.copilot/knowledge/` before solutions
5. **Token efficiency** — Be concise; accuracy over verbosity
6. **Security baseline** — OWASP Top 10, never hardcode secrets, flag insecure patterns
7. **Test-first default** — Propose tests before implementation unless told otherwise
8. **Technology preferences** — Python/Go for code, bash for scripts, Terraform for IaC, GitHub Actions for CI/CD, uv for Python project management

Per-agent personality and MCP-specific instructions live in each `.agent.md`, **not** here.

---

## 8. Distribution & CLI

Carter ships as a single installable Python package exposing one `carter`
command. There is **no PyPI release** — distribution is direct from Git. All
static assets (agents, skills, instructions, knowledge, mcp, templates) are
bundled into the wheel so the command is fully self-contained once installed.

### 8.1 Installing the CLI

```bash
# Recommended: install the carter CLI as a global tool (no clone)
uv tool install git+https://github.com/mauriciomem/carter-ai.git

# Upgrade in place
uv tool upgrade carter-ai

# pipx works too
pipx install git+https://github.com/mauriciomem/carter-ai.git
```

For development, an editable install from a checkout:

```bash
git clone https://github.com/mauriciomem/carter-ai.git ~/carter-ai
cd ~/carter-ai
uv venv && source .venv/bin/activate
uv pip install -e .
```

### 8.2 Unified `carter` Command

One entry point (`carter = "carter.cli:main"`, a Click group) covers the full
lifecycle. The two former "modes" (global system install vs per-workspace
scaffold) and the former standalone `carter-ops` executable are all
subcommands now.

| Subcommand | Purpose |
|---|---|
| `carter install` | System-level install to `~/.copilot/` and/or OpenCode |
| `carter init` | Scaffold a per-project workspace (`.carter/` + generated agents) |
| `carter update` | Re-render workspace agents/instructions from templates |
| `carter check` | Verify workspace integrity |
| `carter ops` | Deterministic write-operation executor (formerly `carter-ops`) |

```bash
# System-level install
carter install                    # all targets
carter install --target copilot   # Copilot only
carter install --target opencode  # OpenCode only
carter install --mcp              # also configure MCP servers
carter install --bot-name my-bot  # custom git attribution (default: carter-bot)
carter install --uninstall        # clean removal via manifest
carter install --base-dir PATH    # override install root (testing)

# Verbosity: -q/--quiet (errors), default, -v/--verbose, --debug

# Workspace scaffold
carter init ~/my-workspace --name "my-project"

# Write operations
carter ops --list
carter ops git-flow --branch feature/x --message "feat: x" --dry-run
```

> `--mcp` is opt-in: no flag means no MCP servers are touched. `--bot-name`
> sets the git/GitHub/Jira attribution identity (with a short footer
> description) baked into `~/.carter/config.toml` and the `carter-ops` skill.

### 8.3 Data Bundling (wheel)

The build backend is **hatchling**. Static data directories are copied into the
wheel under `carter/_data/` via force-include:

```toml
[tool.hatch.build.targets.wheel.force-include]
"agents"       = "carter/_data/agents"
"skills"       = "carter/_data/skills"
"instructions" = "carter/_data/instructions"
"knowledge"    = "carter/_data/knowledge"
"mcp"          = "carter/_data/mcp"
"templates"    = "carter/_data/templates"
```

`carter/resources.py` resolves the data root at runtime:

- **Installed wheel** → `carter/_data/` (bundled assets)
- **Dev checkout** → repository root (the source `agents/`, `skills/`, … dirs)

Both layouts expose the same subdirectories, so `carter.installer` and
`carter.scaffold` consume them identically with no environment-specific logic.

### 8.4 Installer Steps (`carter install`)

The logic lives in `carter/installer.py` and is shared by the legacy bootstrap
shim.

1. Detect OS (macOS vs Linux)
2. Check prerequisites (VS Code, Copilot extension, `copilot` CLI, `opencode`, `gh`, `terraform`, `jq`)
3. Validate credentials (env vars for MCP servers)
4. Back up existing Carter-owned files to `~/.copilot/backup/<timestamp>/`
5. Write agent files to target locations
6. Write skill files to target locations
7. Write global instructions
8. Configure carter-ops:
   - Generate `~/.carter/config.toml` (defaults + `--bot-name`, auto-detect `signing_key` from `git config user.signingkey`)
   - **No file copy / no wrapper script** — write operations run via the bundled `carter ops` subcommand
9. Configure MCP servers (only with `--mcp`):
   - VS Code: merge `carter-*` entries into `settings.json`
   - Copilot CLI: run `copilot mcp add carter-*` commands
   - OpenCode: merge `carter-*` entries into `opencode.json`
10. Initialize knowledge base (only on first install)
11. Write manifest (`~/.copilot/.carter-manifest.json`)
12. Print summary

> **Migration:** `uninstall()` still removes any legacy
> `~/.local/bin/carter-ops` wrapper and `~/.carter/ops/` tree left by older
> installs, so upgrading from the pre-package layout cleans up automatically.

### 8.5 Manifest

`~/.copilot/.carter-manifest.json` tracks every file and config entry Carter owns:

```json
{
  "version": "1.0.0",
  "installed_at": "2026-05-09T10:30:00Z",
  "updated_at": "2026-05-09T10:30:00Z",
  "targets": ["copilot", "opencode"],
  "files": [
    "~/.copilot/agents/carter-maestro.agent.md",
    "~/.copilot/skills/carter-triage/SKILL.md",
    "..."
  ],
  "mcp_servers": ["carter-github", "carter-terraform", "carter-atlassian"],
  "file_hashes": {
    "~/.copilot/agents/carter-maestro.agent.md": "sha256:abc123..."
  }
}
```

### 8.6 Idempotent Updates

Upgrading the CLI (`uv tool upgrade carter-ai`) then re-running `carter install`:

1. Compares file hashes (repo vs installed) via manifest
2. Only updates files that changed
3. Reports per-file status: `created`, `updated`, `unchanged`, `backed up`
4. Updates manifest with new hashes and timestamp

### 8.7 Backup Strategy

Before overwriting any existing file:

1. Copy to `~/.copilot/backup/<timestamp>/` preserving relative paths
2. Log the backup in installer output
3. Manifest records both current and backup paths

### 8.8 CLI Output

Verbosity levels:

| Flag | Behavior |
|---|---|
| `--quiet` / `-q` | Errors only |
| *(default)* | Key actions, prerequisites, summary |
| `--verbose` / `-v` | Full paths, backup details, diffs |
| `--debug` | Internal decision logic, OS detection, template rendering |

Example output (default):
```
 Carter Installer v1.0

→ Detecting environment...
  OS: macOS 15.1 | Python: 3.12.3 | uv: 0.4.2

→ Checking prerequisites...
  ✓ VS Code found
  ✓ Copilot extension installed
  ✓ copilot CLI found (1.0.44)
  ✓ opencode found
  ✓ gh CLI found
  ✓ terraform found
  ⚠ jq not found (optional)

→ Checking credentials...
  ✓ GITHUB_TOKEN set
  ⚠ TF_TOKEN not set — export TF_TOKEN="your-hcp-token"
  ✓ ATLASSIAN_API_TOKEN set
  ✓ ATLASSIAN_EMAIL set
  ⚠ ATLASSIAN_URL not set (default: https://your-domain.atlassian.net)

→ Installing agents...
  ✓ ~/.copilot/agents/carter-maestro.agent.md
  ✓ ~/.copilot/agents/carter-architect.agent.md
  ✓ ~/.copilot/agents/carter-engineer.agent.md
  ✓ ~/.copilot/agents/carter-devops.agent.md
  ✓ ~/.copilot/agents/carter-learner.agent.md
  ✓ ~/.copilot/agents/carter-pm.agent.md
  ✓ ~/.copilot/agents/carter-narrator.agent.md
  ✓ ~/.config/opencode/agents/carter-maestro.md
  ✓ ~/.config/opencode/agents/carter-architect.md
  ✓ ~/.config/opencode/agents/carter-engineer.md
  ✓ ~/.config/opencode/agents/carter-devops.md
  ✓ ~/.config/opencode/agents/carter-learner.md
  ✓ ~/.config/opencode/agents/carter-pm.md
  ✓ ~/.config/opencode/agents/carter-narrator.md

→ Installing skills (20)...
  ✓ carter-triage
  ✓ carter-distill
  ...

→ Configuring MCP servers...
  ✓ carter-github → VS Code settings.json
  ✓ carter-github → copilot mcp add
  ✓ carter-github → opencode.json
  ✓ carter-terraform → VS Code settings.json
  ✓ carter-terraform → copilot mcp add
  ✓ carter-terraform → opencode.json
  ✓ carter-atlassian → VS Code settings.json
  ✓ carter-atlassian → copilot mcp add
  ✓ carter-atlassian → opencode.json

→ Configuring carter-ops...
  ✓ ~/.carter/config.toml
  (write operations run via `carter ops`)

→ Initializing knowledge base...
  ✓ ~/.copilot/knowledge/ (6 topic files)

✓ Installation complete
  Agents: 7 (copilot: 7, opencode: 7)
  Skills: 20
  MCP servers: 3 (VS Code: 3, Copilot CLI: 3, OpenCode: 3)
  Ops config: ~/.carter/config.toml (11 operations via `carter ops`)
  Manifest: ~/.copilot/.carter-manifest.json
```

Update output:
```
→ Installing agents...
  ✓ ~/.copilot/agents/carter-maestro.agent.md ···· updated
  · ~/.copilot/agents/carter-architect.agent.md ·· unchanged
  · ~/.copilot/agents/carter-engineer.agent.md ··· unchanged
  ✓ ~/.copilot/agents/carter-devops.agent.md ····· updated
  · ~/.copilot/agents/carter-learner.agent.md ···· unchanged
  · ~/.copilot/agents/carter-pm.agent.md ········· unchanged
```

### 8.9 Legacy Bootstrap Shim

The historical entry points are retained for backward compatibility. Both are
thin shims that delegate to `carter.installer.main()` (the same code as
`carter install`):

```bash
# install.sh
#!/usr/bin/env bash
set -euo pipefail
exec uv run "$(dirname "$0")/install.py" "$@"
```

```python
# install.py (PEP 723 shim)
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from carter.installer import main

if __name__ == "__main__":
    main()
```

---

## 9. OpenCode Parity

### 9.1 Agent Format Translation

Copilot `.agent.md` frontmatter fields map to OpenCode:

| Copilot | OpenCode | Notes |
|---|---|---|
| `description` | `description` | Same |
| `tools` | `permission` | Translated to allow/deny rules |
| *(none)* | `mode` | Only Maestro gets `primary`, others get `agent` |
| *(none)* | `model` | `${CARTER_MODEL}` placeholder |
| *(none)* | `temperature` | Per-agent values (see §3.1) |
| *(none)* | `color` | Optional, for terminal UI |

### 9.2 Skill Format Translation

| Copilot | OpenCode | Notes |
|---|---|---|
| `description` | `description` | Same |
| *(none)* | `name` | Skill name (matches directory name) |
| *(none)* | `argument-hint` | Usage hint string |
| *(none)* | `allowed-tools` | Tool whitelist (translated from agent scope) |

### 9.3 MCP Format Translation

Copilot VS Code:
```json
"carter-github": {
  "command": "npx",
  "args": ["-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
}
```

OpenCode:
```json
"carter-github": {
  "type": "local",
  "command": ["npx", "-y", "@modelcontextprotocol/server-github"],
  "env": { "GITHUB_TOKEN": "${GITHUB_TOKEN}" }
}
```

Key differences: OpenCode uses `type` field and `command` as an array (not split into `command`/`args`).

---

## 10. Testing

Two complementary suites ship in the repo.

### 10.1 Unit Tests (`tests/`)

Run with: `python -m pytest -q` (191 tests).

| File | Covers |
|---|---|
| `tests/test_install.py` | `carter install` logic: file placement, backup, manifest, idempotency (`created`/`updated`/`unchanged`), MCP merge, uninstall, credential checks |
| `tests/test_scaffold.py` | `carter init`/`update`: Jinja2 rendering, `.carter/` scaffolding, config loading/validation, gitignore handling |
| `tests/ops/test_operations.py` | `carter ops`: every operation's dry-run plan + execute path, attribution, config validation |
| `tests/conftest.py`, `tests/ops/conftest.py` | Shared fixtures: temp git repo, `tmp_path` install root, mock env |

**Key technique:** the installer accepts a `--base-dir`/`base_dir` argument; tests
redirect all writes to pytest's `tmp_path`, so no real `~/.copilot/` is touched.
Operations are exercised through their plugin interface (dry-run plan vs execute)
without performing real network or destructive git actions.

### 10.2 Eval Framework (`evals/`)

A separate harness evaluates agent/skill *behavior* (prompts and routing), in two modes:

| Mode | Tests | Speed | CI-safe |
|---|---|---|---|
| **Offline** | Structural correctness of prompts, routing tables, skill patterns | ~1s | Yes |
| **Live** | Actual model behavior given agent/skill prompts (uses Copilot/Anthropic/OpenAI auth) | ~30s/scenario | Periodic only |

```bash
# Offline (fast, no auth)
uv run --with pytest --with pyyaml pytest evals/ -m "not live" -v

# Live (uses existing Copilot auth)
uv run --with pytest --with pyyaml --with httpx pytest evals/ -v
```

Scenarios live in `evals/scenarios/*.yaml` (`routing.yaml`, `skills.yaml`,
`carter_ops.yaml`, `e2e.yaml`); `evals/judge.py` scores live responses.

---

## 11. Repository Structure

```
carter/
├── pyproject.toml                      # hatchling build; carter = carter.cli:main; force-include data
├── install.py                          # Legacy bootstrap shim → carter.installer.main()
├── install.sh                          # Wrapper: uv run install.py "$@"
├── README.md                           # Quick start, one-liner install
├── .env.example                        # Required/optional env vars
│
├── carter/                             # Installable Python package (the `carter` CLI)
│   ├── cli.py                          # Click group: install, init, update, check, ops
│   ├── installer.py                    # System-level install logic (shared with shim)
│   ├── resources.py                    # Resolves data root (wheel _data vs dev checkout)
│   ├── scaffold.py                     # Jinja2 rendering engine
│   ├── config.py                       # carter.yaml loading + validation
│   ├── state.py                        # .carter/ directory management
│   └── ops/                            # carter-ops executor (`carter ops`)
│       ├── carter_ops.py               # Subcommand entry point (main(argv))
│       ├── operations/                 # Operation plugins (auto-discovered)
│       │   ├── __init__.py             # Auto-discovers Operation subclasses
│       │   ├── git_branch.py
│       │   ├── git_commit.py
│       │   ├── git_push.py
│       │   ├── git_flow.py             # Composite: branch → commit → push
│       │   ├── gh_issue.py
│       │   ├── gh_issue_comment.py
│       │   ├── gh_pr.py
│       │   ├── gh_pr_comment.py
│       │   ├── jira_comment.py
│       │   ├── jira_create.py
│       │   └── jira_update.py          # Composite: comment + transition
│       ├── attribution.py              # Footer templates, git author config
│       ├── output.py                   # Structured JSON output formatting
│       └── config.py                   # Config file + env var loading
│
├── agents/                             # Agent definitions (source of truth → wheel _data)
│   ├── carter-maestro.md
│   ├── carter-architect.md
│   ├── carter-engineer.md
│   ├── carter-devops.md
│   ├── carter-learner.md
│   └── carter-pm.md                    # (carter-narrator generated from template only)
│
├── skills/                             # Skill definitions (source of truth) — 20 skills
│   ├── carter-triage/SKILL.md
│   ├── carter-distill/SKILL.md
│   ├── carter-reflect/SKILL.md
│   ├── carter-design-review/SKILL.md
│   ├── carter-diagram/SKILL.md
│   ├── carter-adr/SKILL.md
│   ├── carter-code-review/SKILL.md
│   ├── carter-test-first/SKILL.md
│   ├── carter-pipeline/SKILL.md
│   ├── carter-terraform/SKILL.md
│   ├── carter-packer/SKILL.md
│   ├── carter-explain/SKILL.md
│   ├── carter-mistakes/SKILL.md
│   ├── carter-research/SKILL.md
│   ├── carter-plan/SKILL.md
│   ├── carter-risk/SKILL.md
│   ├── carter-atlassian/SKILL.md
│   ├── carter-ops/SKILL.md
│   ├── carter-python/SKILL.md
│   └── carter-golang/SKILL.md
│
├── knowledge/                          # Initial knowledge base templates
│   ├── decisions.md
│   ├── mistakes.md
│   ├── patterns.md
│   ├── debugging.md
│   ├── infrastructure.md
│   └── project-history.md
│
├── mcp/                                # MCP server config templates
│   ├── copilot/                        # VS Code settings.json fragments
│   │   ├── github.json
│   │   ├── terraform.json
│   │   └── atlassian.json
│   └── opencode/                       # OpenCode config fragments
│       ├── github.json
│       ├── terraform.json
│       └── atlassian.json
│
├── instructions/                       # Shared instruction files
│   └── copilot-instructions.md         # Global user-level instructions
│
├── templates/                          # Jinja2 agent + instruction templates (→ wheel _data)
│   ├── base_agent.md.j2                # Base template (inheritance)
│   ├── agents/                         # Per-agent templates (7, incl carter-narrator.md.j2)
│   └── instructions/                   # Global instructions template
│
├── docs/                               # Project documentation
│   ├── interactions/
│   │   ├── plan.md                     # This file (as-built)
│   │   ├── v2-plan.md                  # Earlier draft (superseded)
│   │   ├── v3-carter-ops-enforcement.md
│   │   ├── conversation-log.md         # Design conversation log
│   │   └── conversation-log-carter-ops.md
│   ├── getting-started.md
│   ├── carter-ops.md
│   ├── memory-and-knowledge.md
│   └── testing.md
│
├── evals/                              # Agent/skill behavior eval harness
│   ├── judge.py                        # Scores live model responses
│   ├── test_routing.py                 # Maestro routing scenarios
│   ├── test_skills.py                  # Skill-invocation scenarios
│   ├── test_live.py                    # End-to-end live scenarios
│   ├── conftest.py
│   └── scenarios/                      # routing.yaml, skills.yaml, carter_ops.yaml, e2e.yaml
│
└── tests/                              # Unit tests (191)
    ├── test_install.py                 # `carter install` logic
    ├── test_scaffold.py                # `carter init`/`update` scaffolding
    ├── ops/                            # `carter ops` operation tests
    │   ├── conftest.py                 # Fixtures: temp git repo, mock env
    │   └── test_operations.py          # All 11 operations: plan + execute
    └── conftest.py                     # Shared fixtures
```

---

## 12. Implementation Phases

### Phase 1: Foundation

| # | Task | Description |
|---|---|---|
| 1.1 | Repo setup | Create `carter/` repo with directory structure, README stub, `.env.example` |
| 1.2 | Global instructions | Write `copilot-instructions.md` (~25 lines) |
| 1.3 | Maestro agent | `carter-maestro.agent.md` + `carter-triage/SKILL.md` (Copilot + OpenCode) |
| 1.4 | Installer v0 | Minimal: copies agents + instructions, basic ANSI output, no MCP/backup |

**Exit criteria:** `@carter-maestro` responds in VS Code, Copilot CLI, and OpenCode with Carter's personality.

### Phase 2: Personality Agents + Skills

| # | Task | Description |
|---|---|---|
| 2.1 | Architect agent | `carter-architect.agent.md` + `carter-design-review`, `carter-diagram`, `carter-adr` |
| 2.2 | Engineer agent | `carter-engineer.agent.md` + `carter-code-review`, `carter-test-first` |
| 2.3 | DevOps agent | `carter-devops.agent.md` + `carter-pipeline`, `carter-terraform`, `carter-packer` |
| 2.4 | Learner agent | `carter-learner.agent.md` + `carter-explain`, `carter-mistakes`, `carter-research` |
| 2.5 | PM agent | `carter-pm.agent.md` + `carter-plan`, `carter-risk`, `carter-atlassian` |
| 2.6 | Python skill | `carter-python/SKILL.md` — standards, checklist, enforcement |
| 2.7 | Go skill | `carter-golang/SKILL.md` — standards, checklist, enforcement |

**Exit criteria:** All 7 agents + 20 skills functional. Each agent responds with its personality and domain expertise. Maestro routes correctly.

### Phase 3: Infrastructure

| # | Task | Description |
|---|---|---|
| 3.1 | MCP configs | GitHub, Terraform, Atlassian templates for all 3 targets |
| 3.2 | Installer v1 | Full: backup, manifest, MCP merging, credential validation, prerequisites, `--uninstall`, `--target`, verbosity, idempotent |
| 3.3 | Knowledge base | Template files + `carter-distill/SKILL.md` |

**Exit criteria:** `carter install` (or the legacy `uv run install.py` shim) produces a complete, working Carter installation. MCP servers connected. Knowledge base initialized.

### Phase 4: Polish

| # | Task | Description |
|---|---|---|
| 4.1 | Installer tests | pytest + `tmp_path` + snapshot tests |
| 4.2 | README | Quick start, architecture overview, troubleshooting |
| 4.3 | `.env.example` | All required/optional env vars with descriptions |

**Exit criteria:** All tests pass. README covers install, usage, and troubleshooting. Project is shareable.

---

## 13. Delivered Beyond v1 & Future Ideas

### 13.1 Delivered (shipped in the current build)

| Capability | Notes |
|---|---|
| **`carter-ops`** deterministic executor | Now a first-class `carter ops` subcommand. Stateless two-phase (`--dry-run` → approve → `--execute`), plugin operations auto-discovered, attribution footers, append-only audit log. MCP for reads, `carter ops` for writes. |
| **Unified `carter` CLI** | `carter install / init / update / check / ops` packaged via hatchling. `uvx carter ...` replaces `git clone && uv run install.py`. |
| **Eval framework** (`evals/`) | Offline (structural) + live (model-behavior) scenarios for routing and skills. |
| **carter-narrator** agent | Template-generated redaction utility agent (config `redaction` block). |
| **Extra skills** | `carter-reflect`, `carter-packer`, `carter-atlassian` shipped beyond the original 17. |

### 13.2 Future Ideas (not yet built)

| Idea | Description |
|---|---|
| Rich CLI output | Progress bars/tables/panels via `rich` |
| Additional MCP servers | AWS (IAM-guarded), Vault (secrets) |
| Git-backed knowledge sync | `~/.copilot/knowledge/` as a git repo; auto-commit on distill; cross-machine sync |
| Vault credential integration | Pull MCP creds from Vault at runtime instead of env vars |
| Docker integration tests | Clean-container end-to-end install matrix in CI |

---

## 14. Technology Stack Summary

| Concern | Technology |
|---|---|
| Agent/skill framework | VS Code Copilot agents, Copilot CLI agents, OpenCode agents |
| CLI + installer | Python 3.11+, Click, Jinja2, hatchling build, distributed via `uv tool` (`uvx carter`) |
| Deterministic executor | `carter ops` — plugin operations, `httpx` for Jira/GitHub REST APIs |
| Python tooling | `uv` (run, build, publish) |
| MCP servers | GitHub, Terraform/HCP, Atlassian (reads); `carter ops` (writes) |
| Testing | pytest + `tmp_path` (unit, 191 tests); `evals/` (offline + live behavior) |
| Version control | Git, GitHub |
| CI/CD | GitHub Actions |
| Knowledge persistence | Markdown files in `~/.copilot/knowledge/` |
| Session memory | Copilot memory system (`/memories/`) |
| Audit log | Append-only JSONL at `~/.carter/audit.log` |
