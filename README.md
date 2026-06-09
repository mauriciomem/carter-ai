# Carter

[![CI](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml)

A multi-agent AI assistant for software architecture, engineering, DevOps,
learning, and project management. Instead of one generic assistant, you get
specialized agents with focused expertise and strict boundaries; a central
orchestrator (**Maestro**) routes each request to the right specialist.

Runs on **VS Code**, **Copilot CLI**, and **OpenCode** — same agents, skills, and
MCP integrations across all three.

## Install

**Prerequisites:** [uv](https://docs.astral.sh/uv/) and Python 3.11+.

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git
uv tool update-shell        # put ~/.local/bin on your PATH (once)
exec $SHELL                 # reload, then: carter --version
```

> **`carter: command not found`?** The executable lives in `~/.local/bin`, which
> may not be on your `PATH`. Run `uv tool update-shell` and reload your shell, or
> `export PATH="$HOME/.local/bin:$PATH"`. `pipx install git+…` works too.

Then choose how to use Carter:

| Command | What it does |
|---------|--------------|
| `carter install` | System-level: copies agents/skills to `~/.copilot/` (and/or OpenCode) for use in every workspace |
| `carter init <dir>` | Per-project: scaffolds a `.carter/` workspace with agents generated from templates |

```bash
carter install                  # all targets
carter install --target copilot # Copilot only (or: opencode, all)
carter install --mcp            # also configure MCP servers (needs tokens)
carter install --uninstall      # remove

carter init ~/my-project --name "my-project"   # scaffold a workspace
```

For MCP servers and write operations, set the relevant tokens first
(`GITHUB_TOKEN`, `TF_TOKEN`, `ATLASSIAN_*`). See [.env.example](.env.example).

→ Full walkthrough: **[docs/getting-started.md](docs/getting-started.md)**

## Usage

```
@carter-maestro design a REST API for a task-management app
@carter-engineer review src/auth.py for security issues
@carter-maestro review my changes before I push
```

Maestro routes single-domain requests to one specialist and chains specialists
for cross-domain work. The **quality gate** dispatches reviewers (engineer for
code, architect for design) that report findings by severity — 🚨 Blocking,
⚠️ Suggestion, 💡 Nitpick — and is configurable in `carter.yaml`.

**Copilot CLI:** launch Maestro, reach specialists by `@`-mention:

```bash
copilot --agent carter-maestro -p "@carter-devops write a Terraform module for S3" --allow-all
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

Maestro is the **primary** agent; the six specialists are **subagents**. Talk to
Maestro and let it route, or `@`-mention any specialist directly.

| Agent | Domain | Key capabilities |
|-------|--------|------------------|
| **Maestro** | Orchestration, routing, quality gates | Routes requests, triggers reviews, captures knowledge |
| **Architect** | System design, cloud, trade-offs | ADRs, diagrams, API contracts, design review |
| **Engineer** | Code quality, testing, patterns | TDD, code review, refactoring, security checks |
| **DevOps** | CI/CD, IaC, containers, git | Pipelines, Terraform, Packer, deployment |
| **Learner** | Explanation, research, memory | Documentation, mistake capture, topic research |
| **PM** | Planning, risk, agile | WBS, roadmaps, sprint planning, risk assessment |
| **Narrator** | External-facing content | Reframes + redacts PRs, Jira, docs, announcements ([ADR-0001](docs/adr/0001-narrator-content-suite.md)) |

## Carter-Ops — write operations

Write operations (git, GitHub, Jira) run through an approval gate: **plan →
approve → execute → audit**. Trigger with the `ops:` prefix.

```
@carter-maestro ops: create a feature branch, commit my changes, and push
```

Carter shows the exact commands (with bot attribution), waits for your approval,
executes, and logs the operation — using the `carter ops` subcommand under the
hood (`carter ops --list`).

→ Reference: **[docs/carter-ops.md](docs/carter-ops.md)**

## Configuration & templates

Workspace agents are generated from Jinja2 templates (base + per-agent
inheritance) driven by `.carter/carter.yaml`. Edit config, then `carter update .`
to regenerate (knowledge files are never touched); `carter check .` validates the
workspace.

| Config key | Effect |
|------------|--------|
| `personality.skepticism` | How much Carter challenges your decisions |
| `quality_gate.enabled` | Multi-agent review before push |
| `tdd.strict` | Force test-first workflow |
| `redaction.enabled` | Sanitize external-facing content |
| `agents` | Which agents to generate |
| `target` | Where to write: `copilot` / `opencode` / `all` |
| `agent_suffix` | Distinguish workspace agents from global (default `local`) |

→ Config reference and walkthrough: **[docs/getting-started.md](docs/getting-started.md)**

## Memory & knowledge

Carter learns from experience across layers: **workspace** (`.carter/knowledge/`),
**system** (`~/.copilot/knowledge/`), and raw **memory** (`~/.carter/memories/`)
promoted into knowledge. Lifecycle skills: `carter-mistakes` (capture) →
`carter-distill` (promote) → `carter-reflect` (improve agents from patterns).

→ Reference: **[docs/memory-and-knowledge.md](docs/memory-and-knowledge.md)**

## Plans & state

Plans are directories under `.carter/state/plans/` with machine-readable
frontmatter and verifiable `must_haves`; a session `checkpoint.md` cursor enables
"where were we?" recovery. `carter check` validates the frontmatter contract;
`carter save` commits a recovery snapshot of `.carter/`. Architecture decisions
live as ADRs in `docs/adr/`.

→ Reference: **[docs/plans-and-state.md](docs/plans-and-state.md)**

## MCP servers

Configured by `carter install --mcp` into VS Code, Copilot CLI, and OpenCode:

| Server | Purpose |
|--------|---------|
| `carter-github` | Repos, PRs, issues, Actions |
| `carter-terraform` | Terraform configs, state, plans |
| `carter-atlassian` | Jira issues, Confluence pages |

## Development

```bash
git clone https://github.com/mauriciomem/carter-ai.git && cd carter-ai
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
python -m pytest tests/ -q          # 239 tests
```

The suite (installer, scaffold, parity, carter-ops) runs on every push and PR via
[GitHub Actions](.github/workflows/ci.yml). → **[docs/testing.md](docs/testing.md)**

```
carter/        CLI package (cli, installer, scaffold, config, state, ops/)
templates/     Jinja2 agent + instruction templates
agents/        Source-of-truth agent definitions (copied by `carter install`)
skills/        Skill definitions (hand-maintained)
knowledge/     Knowledge-base templates
mcp/           MCP server config templates
docs/          Documentation
tests/         Test suites (install, scaffold, parity, ops)
```

> `carter` bundles its data inside the package, so `uv tool install` works
> without a checkout. The legacy `./install.sh` / `uv run install.py` shims still
> delegate to `carter install`. The installer is idempotent (SHA-256 hashing) and
> writes a manifest for clean updates and uninstall.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `carter: command not found` | `~/.local/bin` not on `PATH` — run `uv tool update-shell` and reload your shell (see [Install](#install)) |
| `uv tool upgrade` says "Nothing to upgrade" | Version is unchanged across commits; force it: `uv tool install --force git+https://github.com/mauriciomem/carter-ai.git` |
| Agents not appearing in VS Code | Restart VS Code; agents load from `~/.copilot/agents/` (system) or `.github/agents/` (workspace) on startup |
| MCP server conflicts | Carter installs alongside existing servers as `carter-*`; remove the original to avoid duplicate tools |
| Missing tokens for `--mcp` | Run `carter install --mcp -v` to see which env vars are unset |

## License

GPL-3.0
