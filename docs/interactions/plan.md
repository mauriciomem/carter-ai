# Carter — Implementation Plan

> AI assistant with expert personalities for software architecture, engineering, DevOps, learning, and project management.

---

## 1. Overview

Carter is a multi-personality AI assistant built on top of the VS Code Copilot agent system, Copilot CLI, and OpenCode CLI. It provides six specialized agents, each with domain-specific skills, backed by MCP servers for deterministic operations and a persistent knowledge base for learning from experience.

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
  └── @carter-pm        (direct access)
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

- Model is not hardcoded — uses a `${CARTER_MODEL}` placeholder that resolves to the user's default or a configured value.
- Per-agent tool restrictions enforce least-privilege access to MCP servers.

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

### 4.1 Skill Map (v1)

| Agent | Skill | Description |
|---|---|---|
| **Maestro** | `carter-triage` | Classify request, route to specialist agent(s) |
| | `carter-distill` | Promote `/memories/` notes to curated knowledge |
| **Architect** | `carter-design-review` | Analyze architecture for patterns, anti-patterns, security |
| | `carter-diagram` | Generate Mermaid architecture diagrams |
| | `carter-adr` | Create Architecture Decision Records |
| **Engineer** | `carter-code-review` | Review code for quality, patterns, security, testability |
| | `carter-test-first` | Generate tests before implementation (TDD workflow) |
| **DevOps** | `carter-pipeline` | Create/modify GitHub Actions workflows |
| | `carter-terraform` | Write/review Terraform configurations |
| | `carter-git-strategy` | Advise on branching strategies, resolve merge conflicts |
| **Learner** | `carter-explain` | Break down complex topics into understandable parts |
| | `carter-mistakes` | Record mistakes and lessons learned to memory |
| | `carter-research` | Fetch and summarize official documentation |
| **PM** | `carter-plan` | Create project plans, WBS, task dictionaries |
| | `carter-risk` | Risk identification and mitigation planning |
| **Shared** | `carter-python` | Python coding standards and enforcement |
| | `carter-golang` | Go coding standards and enforcement |

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

### 4.3 Skills Deferred to v2

| Agent | Skill | Description |
|---|---|---|
| Engineer | `carter-refactor` | Identify and apply refactoring patterns |
| DevOps | `carter-container` | Dockerfile and Kubernetes manifest creation/review |
| PM | `carter-roadmap` | Design milestone-based roadmaps |
| PM | `carter-standup` | Summarize recent work from Git/Jira for standups |

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

| Variable | Server | Required |
|---|---|---|
| `GITHUB_TOKEN` | carter-github | Yes |
| `TF_TOKEN` | carter-terraform | Yes |
| `ATLASSIAN_API_TOKEN` | carter-atlassian | Yes |
| `ATLASSIAN_EMAIL` | carter-atlassian | Yes |
| `ATLASSIAN_URL` | carter-atlassian | Yes |

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

## 8. Installer

### 8.1 Invocation

```bash
# Install (all targets)
uv run install.py

# Install specific target
uv run install.py --target copilot
uv run install.py --target opencode
uv run install.py --target all

# Uninstall
uv run install.py --uninstall
uv run install.py --uninstall --target opencode

# Convenience wrapper
./install.sh
./install.sh --uninstall
```

### 8.2 PEP 723 Script Metadata

```python
# /// script
# requires-python = ">=3.11"
# ///
```

v2 upgrade for rich output:
```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["rich>=13.0"]
# ///
```

### 8.3 Installer Steps

1. Detect OS (macOS vs Linux)
2. Check prerequisites (VS Code, Copilot extension, `copilot` CLI, `opencode`, `gh`, `terraform`, `jq`)
3. Validate credentials (env vars for MCP servers)
4. Back up existing Carter-owned files to `~/.copilot/backup/<timestamp>/`
5. Write agent files to target locations
6. Write skill files to target locations
7. Write global instructions
8. Configure MCP servers:
   - VS Code: merge `carter-*` entries into `settings.json`
   - Copilot CLI: run `copilot mcp add carter-*` commands
   - OpenCode: merge `carter-*` entries into `opencode.json`
9. Initialize knowledge base (only on first install)
10. Write manifest (`~/.copilot/.carter-manifest.json`)
11. Print summary

### 8.4 Manifest

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

### 8.5 Idempotent Updates

Re-running the installer (`git pull && uv run install.py`):

1. Compares file hashes (repo vs installed) via manifest
2. Only updates files that changed
3. Reports per-file status: `created`, `updated`, `unchanged`, `backed up`
4. Updates manifest with new hashes and timestamp

### 8.6 Backup Strategy

Before overwriting any existing file:

1. Copy to `~/.copilot/backup/<timestamp>/` preserving relative paths
2. Log the backup in installer output
3. Manifest records both current and backup paths

### 8.7 CLI Output (v1 — ANSI/stdlib)

Verbosity levels:

| Flag | Behavior |
|---|---|
| `--quiet` / `-q` | Errors only |
| *(default)* | Key actions, prerequisites, summary |
| `--verbose` / `-v` | Full paths, backup details, diffs |
| `--debug` / `-vv` | Internal decision logic, OS detection, template rendering |

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
  ✓ ~/.config/opencode/agents/carter-maestro.md
  ✓ ~/.config/opencode/agents/carter-architect.md
  ✓ ~/.config/opencode/agents/carter-engineer.md
  ✓ ~/.config/opencode/agents/carter-devops.md
  ✓ ~/.config/opencode/agents/carter-learner.md
  ✓ ~/.config/opencode/agents/carter-pm.md

→ Installing skills (17)...
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

→ Initializing knowledge base...
  ✓ ~/.copilot/knowledge/ (6 topic files)

✓ Installation complete
  Agents: 6 (copilot: 6, opencode: 6)
  Skills: 17
  MCP servers: 3 (VS Code: 3, Copilot CLI: 3, OpenCode: 3)
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

### 8.8 CLI Output (v2 — Rich)

Upgraded via PEP 723 `dependencies = ["rich>=13.0"]`:

- Progress bars with animation during file writes
- Tables for environment info and MCP server matrix
- Tree rendering with box-drawing characters for file hierarchies
- Panels for header/summary
- Spinners per step
- Dot leaders aligning status to right edge
- "Next steps" section in summary

### 8.9 `install.sh` Wrapper

```bash
#!/usr/bin/env bash
set -euo pipefail
exec uv run "$(dirname "$0")/install.py" "$@"
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

### 10.1 v1 — Unit + Snapshot Tests

Run with: `uv run --with pytest pytest tests/`

**Test categories:**

| Category | What's Tested |
|---|---|
| File operations | Correct directory structure, file content, backup creation, manifest accuracy |
| Idempotency | Running twice produces same result, `unchanged` detection works |
| MCP merging | `carter-*` entries added/updated without touching other entries |
| Uninstall | Only removes Carter-owned files, restores backups |
| Cross-platform | Path handling on macOS and Linux |
| Prerequisites | Correctly identifies installed/missing tools |
| Credentials | Warns on missing env vars, doesn't leak values |

**Key technique:** The installer accepts a `--base-dir` argument. Tests use pytest's `tmp_path` fixture to redirect all writes to a temporary directory. No real `~/.copilot/` is touched.

**Snapshot tests:** Compare generated agent/skill file content against known-good golden files. Catches accidental content regressions.

### 10.2 v2 — Docker Integration Tests

Full end-to-end testing in clean environments:

| Test | Container Setup | Validates |
|---|---|---|
| Clean macOS-like install | Ubuntu + Python 3.11 + uv + mock tool binaries | Full install, file placement, manifest |
| Clean install (no optional tools) | Minimal container, only Python + uv | Graceful degradation, correct warnings |
| Upgrade from v1 to v2 | Pre-populated v1 files + new installer | Idempotent update, correct `updated`/`unchanged` |
| Uninstall | Post-install state | Complete cleanup, no orphaned files |
| Existing MCP servers | Pre-populated `settings.json` with non-Carter servers | Merge preserves existing, warns on conflicts |
| OpenCode parity | Container with OpenCode installed | Agent/skill/MCP files match expected format |
| Credential validation | Partial env vars set | Correct warnings, no secrets in output |

**CI integration:** GitHub Actions workflow runs Docker tests on every push to `main` and on PRs. Matrix: Python 3.11, 3.12, 3.13 × macOS paths, Linux paths.

**Docker test structure:**
```
tests/
├── test_install.py          # Unit + snapshot tests (v1)
├── golden/                  # Golden files for snapshot comparison
│   ├── carter-maestro.agent.md
│   ├── carter-maestro.opencode.md
│   └── ...
├── integration/             # Docker integration tests (v2)
│   ├── Dockerfile.clean
│   ├── Dockerfile.upgrade
│   ├── docker-compose.test.yml
│   └── test_integration.py
└── conftest.py              # Shared fixtures
```

---

## 11. Repository Structure

```
carter/
├── install.py                          # Single-file installer (PEP 723, stdlib only)
├── install.sh                          # Wrapper: uv run install.py "$@"
├── README.md                           # Quick start, one-liner install
├── .env.example                        # Required/optional env vars
│
├── agents/                             # Agent definitions (source of truth)
│   ├── carter-maestro.agent.md
│   ├── carter-architect.agent.md
│   ├── carter-engineer.agent.md
│   ├── carter-devops.agent.md
│   ├── carter-learner.agent.md
│   └── carter-pm.agent.md
│
├── skills/                             # Skill definitions (source of truth)
│   ├── carter-triage/SKILL.md
│   ├── carter-distill/SKILL.md
│   ├── carter-design-review/SKILL.md
│   ├── carter-diagram/SKILL.md
│   ├── carter-adr/SKILL.md
│   ├── carter-code-review/SKILL.md
│   ├── carter-test-first/SKILL.md
│   ├── carter-pipeline/SKILL.md
│   ├── carter-terraform/SKILL.md
│   ├── carter-git-strategy/SKILL.md
│   ├── carter-explain/SKILL.md
│   ├── carter-mistakes/SKILL.md
│   ├── carter-research/SKILL.md
│   ├── carter-plan/SKILL.md
│   ├── carter-risk/SKILL.md
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
├── docs/                               # Project documentation
│   ├── plan.md                         # This file
│   └── conversation-log.md             # Design conversation log
│
└── tests/                              # Installer tests
    ├── test_install.py                 # Unit + snapshot tests
    ├── golden/                         # Golden files for snapshots
    ├── integration/                    # Docker integration tests (v2)
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
| 2.3 | DevOps agent | `carter-devops.agent.md` + `carter-pipeline`, `carter-terraform`, `carter-git-strategy` |
| 2.4 | Learner agent | `carter-learner.agent.md` + `carter-explain`, `carter-mistakes`, `carter-research` |
| 2.5 | PM agent | `carter-pm.agent.md` + `carter-plan`, `carter-risk` |
| 2.6 | Python skill | `carter-python/SKILL.md` — standards, checklist, enforcement |
| 2.7 | Go skill | `carter-golang/SKILL.md` — standards, checklist, enforcement |

**Exit criteria:** All 6 agents + 17 skills functional. Each agent responds with its personality and domain expertise. Maestro routes correctly.

### Phase 3: Infrastructure

| # | Task | Description |
|---|---|---|
| 3.1 | MCP configs | GitHub, Terraform, Atlassian templates for all 3 targets |
| 3.2 | Installer v1 | Full: backup, manifest, MCP merging, credential validation, prerequisites, `--uninstall`, `--target`, verbosity, idempotent |
| 3.3 | Knowledge base | Template files + `carter-distill/SKILL.md` |

**Exit criteria:** `uv run install.py` produces a complete, working Carter installation. MCP servers connected. Knowledge base initialized.

### Phase 4: Polish

| # | Task | Description |
|---|---|---|
| 4.1 | Installer tests | pytest + `tmp_path` + snapshot tests |
| 4.2 | README | Quick start, architecture overview, troubleshooting |
| 4.3 | `.env.example` | All required/optional env vars with descriptions |

**Exit criteria:** All tests pass. README covers install, usage, and troubleshooting. Project is shareable.

---

## 13. v2 Roadmap

Features deferred from v1, organized by priority:

### 13.1 Rich CLI Output

- Upgrade installer to use `rich` via PEP 723 dependencies
- Progress bars, tables, tree views, panels, spinners
- Zero user friction — `uv run install.py` handles `rich` installation automatically

### 13.2 Additional Skills

| Skill | Agent | Description |
|---|---|---|
| `carter-refactor` | Engineer | Identify and apply refactoring patterns |
| `carter-container` | DevOps | Dockerfile and Kubernetes manifest creation/review |
| `carter-roadmap` | PM | Design milestone-based roadmaps |
| `carter-standup` | PM | Summarize recent work from Git/Jira for standups |

### 13.3 Additional MCP Servers

| Server | Agent Access | Notes |
|---|---|---|
| AWS | DevOps (full), Architect (read) | Needs careful IAM guardrails |
| Vault | DevOps (full) | Secrets management, security-sensitive |

### 13.4 Docker Integration Tests

- Full end-to-end tests in clean containers (see §10.2)
- GitHub Actions CI matrix: Python 3.11/3.12/3.13 × macOS/Linux paths
- Tests: clean install, upgrade, uninstall, MCP merge, credential validation

### 13.5 Git-Backed Knowledge Sync

- Initialize `~/.copilot/knowledge/` as a Git repository
- Learner commits knowledge updates with structured commit messages
- Enables syncing across machines via remote (private GitHub repo)
- `carter-distill` auto-commits after promoting learnings

### 13.6 Packaging

- Distribute Carter as a `uv` tool: `uvx carter install`
- Uses `uv build` / `uv publish` to package as a Python distributable
- Published to PyPI or a private registry
- `uvx carter install` replaces `git clone && uv run install.py`
- `uvx carter update` replaces `git pull && uv run install.py`
- `uvx carter uninstall` replaces `uv run install.py --uninstall`

### 13.7 Vault Integration for Credentials

- Pull MCP server credentials from HashiCorp Vault at runtime
- Replace env var references with Vault paths
- Requires Vault agent or auth method configuration during install

---

## 14. Technology Stack Summary

| Concern | Technology |
|---|---|
| Agent/skill framework | VS Code Copilot agents, Copilot CLI agents, OpenCode agents |
| Installer | Python 3.11+, stdlib only (v1), `rich` (v2) |
| Python tooling | `uv` (run, build, publish) |
| MCP servers | GitHub, Terraform/HCP, Atlassian |
| Testing | pytest, `tmp_path`, snapshot tests (v1); Docker (v2) |
| Version control | Git, GitHub |
| CI/CD | GitHub Actions |
| Knowledge persistence | Markdown files in `~/.copilot/knowledge/` |
| Session memory | Copilot memory system (`/memories/`) |
