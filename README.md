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

mkdir -p ~/my-project                          # the directory must exist
carter init ~/my-project --name "my-project"   # scaffold a workspace
```

For MCP servers, set the relevant tokens first (`GITHUB_TOKEN`, `TFE_TOKEN`);
the Atlassian server authenticates via OAuth in your client. See [.env.example](.env.example).

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

**Spend fewer tokens per task.** Each maestro hand-off re-sends context, so when you
already know the domain, **`@`-mention the specialist directly** (e.g. `@carter-engineer`)
to skip the routing hop. Give complete context up front — Carter's spec/TDD-first posture
exists to avoid ambiguous → wrong → redo loops — and ask an agent to **read the files it
needs in one batch** rather than one-at-a-time round-trips. See
[docs/reference/cost-and-models.md](docs/reference/cost-and-models.md).

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
  │     ├─→ @carter-narrator    (external content, redaction)
  │     └─→ @carter-security    (defensive review, threat model, authorized methodology)
  │
  └── @-mention any specialist directly
```

### Agents

Maestro is the **primary** agent; the seven specialists are **subagents** — a **flat,
one-level** chain (Maestro routes; specialists don't re-delegate). Talk to Maestro
and let it route, or `@`-mention any specialist directly. Every specialist is a
first-class citizen, each the authority in its domain.

| Agent | Domain | Key capabilities |
|-------|--------|------------------|
| **Maestro** | Orchestration, routing, quality gates | Routes requests, triggers reviews, captures knowledge |
| **Architect** | System design, cloud, trade-offs | ADRs, diagrams, API contracts, design review |
| **Engineer** | Code quality, testing, patterns | TDD, code review, refactoring, security checks |
| **DevOps** | CI/CD, IaC, containers, git | Pipelines, Terraform, Packer, deployment — the **only** agent that pushes/mutates infra |
| **Learner** | Explanation, research, memory | Documentation, mistake capture, topic research |
| **PM** | Planning, risk, agile | WBS, roadmaps, sprint planning, risk assessment |
| **Narrator** | External-facing content | The external-content specialist (the way Architect is the design specialist) — drafts + **redacts** outward content (PRs, Jira, docs, announcements); on `guarded`/`strict` substantive outward content routes through the narrator's redaction pass before DevOps transmits it ([ADR-0001](docs/adr/0001-narrator-content-suite.md)) |
| **Security** | Defensive review, threat modeling, authorized methodology | any agent can flag a risk; carter-security specializes in defensive review and *authorized* security methodology. Advisory only (it threat-models, reviews, and triages — it does not run attacks); offensive methodology is authorized-context-gated; it never pushes — remediation is a handoff to devops. |

> Across targets, the per-agent `mode:` (`primary`/`subagent`) is **OpenCode-scoped**:
> OpenCode reads it; VS Code ignores it (there the primary/subagent split comes from
> the `agents:` allowlist).

## Carter-Ops — write operations

Write operations (git, GitHub, Jira) run through an approval gate: **plan →
approve → execute → audit**. Trigger with the `ops:` prefix.

```
@carter-maestro ops: create a feature branch, commit my changes, and push
```

Carter shows the exact commands (with bot attribution), waits for your approval,
executes the commands directly, and records the result with `carter ops audit`.

→ Reference: **[docs/carter-ops.md](docs/carter-ops.md)**

## Configuration & templates

Workspace agents are generated from Jinja2 templates (base + per-agent
inheritance) driven by `.carter/carter.yaml`. Edit config, then `carter update .`
to regenerate (knowledge files are never touched); `carter check .` validates the
workspace.

| Config key | Effect |
|------------|--------|
| `policy.level` | Risk-based strictness: `guarded` / `strict` (pre-action gates) |
| `models` | Per-agent model by tier (thinkers = Opus; implementers = Sonnet, incl. pm + narrator; `overrides > profile > tier > default`) |
| `profile` | Cost profile: `quality` (all Opus) or `budget` (Sonnet where safe). See [docs/reference/cost-and-models.md](docs/reference/cost-and-models.md) |
| `personality.skepticism` | How much Carter challenges your decisions |
| `quality_gate.enabled` | Multi-agent review before push |
| `tdd.strict` | Force test-first workflow |
| `redaction.categories` | What the narrator redacts from external-facing content |
| `agents` | Which agents to generate |
| `target` | Where to write: `copilot` / `opencode` / `all` |
| `agent_suffix` | Distinguish workspace agents from global (default `local`) |

→ Config reference and walkthrough: **[docs/getting-started.md](docs/getting-started.md)**

## Strictness policy

Carter's safety posture is **enforced**, not just described. A **risk-based
strictness policy** ([ADR-0010](docs/adr/0010-agent-platform-refresh.md),
superseding [ADR-0005](docs/adr/0005-risk-based-strictness-policy.md)) gives each
agent a deny-by-default tool allowlist and gates actions across four risk
categories — **read → local-write → remote-write → dangerous** (secret reads fold
into `remote-write`; outward content is an enforced redaction handoff, not a
category). One `policy.level` knob sets how strict:

| Level | Behaviour |
|-------|-----------|
| `guarded` | The floor and the default — remote-write is `ask`, dangerous is `gate` |
| `strict` | Regulated / prod-critical — remote-write is `gate`, dangerous is `deny` |

Where the target runtime supports it (OpenCode `permission`), Carter **emits native
enforcement**; elsewhere (the `copilot` target) it degrades to honestly-labelled
prose and `carter check` flags the gap. `devops` is the **sole pusher** — the only
agent holding `remote-write`/`dangerous`. Substantive outward content is forced
through `narrator` for redaction (a `gate`-tier handoff), then handed to `devops`
to transmit.

→ Tutorial: **[docs/strictness-policy.md](docs/strictness-policy.md)** · schema: **[docs/reference/frontmatter.md](docs/reference/frontmatter.md)**

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
`carter save` commits a recovery snapshot of `.carter/`. carter-ai's own
architecture decisions live as ADRs in [`docs/adr/`](docs/adr/).

→ Reference: **[docs/plans-and-state.md](docs/plans-and-state.md)**

## MCP servers

Configured by `carter install --mcp` into VS Code, Copilot CLI, and OpenCode:

| Server | Purpose |
|--------|---------|
| `carter-github` | Repos, PRs, issues (read-only) |
| `carter-terraform` | Terraform Registry, HCP Terraform / TFE workspaces (Docker, `TFE_TOKEN`) |
| `carter-atlassian` | Jira issues, Confluence pages (official remote server, OAuth) |

**Install only what you use.** MCP tool schemas are the largest per-request token
surface, so a workspace should wire only the servers it needs:

```bash
carter install --mcp --mcp-servers github          # just GitHub
carter install --mcp --mcp-servers github,terraform # GitHub + Terraform
carter install --mcp                                 # all three (default)
```

An unused server adds **zero** tool-schema tokens.

**GitHub server — official, Docker, read-only.** `carter-github` runs the official
[`github/github-mcp-server`](https://github.com/github/github-mcp-server) via Docker
(digest-pinned), in **read-only** mode with a surgical tool allowlist. This needs a
running **Docker daemon** (the no-Docker alternative is the server's remote-HTTP
transport at `https://api.githubcopilot.com/mcp/`, not wired by default). Set
`GITHUB_TOKEN` before use.

> **"Read-only" is MCP-surface only.** It removes GitHub *write tools* from the model's
> MCP surface — it does **not** mean Carter can't write to GitHub. Shell `gh`/`git`
> writes use the same token and remain governed by the risk-based strictness policy
> ([docs/strictness-policy.md](docs/strictness-policy.md)): devops is the sole
> pusher, gated per its allowlist. "Read-only" ≠ "cannot write."

## Development

```bash
git clone https://github.com/mauriciomem/carter-ai.git && cd carter-ai
uv sync --extra dev
uv run pytest -q                     # unit tests (offline)
uv run pytest evals -m "not live" -q # offline evals
```

The suite (installer, scaffold, parity, carter-ops) runs on every push and PR via
[GitHub Actions](.github/workflows/ci.yml). → **[docs/testing.md](docs/testing.md)**

```
carter/        CLI package (cli, installer, install/, scaffold, config, plans, state, ops/)
templates/     Jinja2 agent + instruction templates (`carter init` / `update`)
agents/        Static agent definitions (copied by `carter install`)
instructions/  Global instructions (copied by `carter install`)
skills/        Skill definitions (hand-maintained)
knowledge/     Knowledge-base seed templates
mcp/           MCP server config templates
docs/          Documentation (incl. ADRs)
tests/         Unit tests (offline)
evals/         Prompt/skill evals (offline + live)
```

> `carter` bundles its data inside the package, so `uv tool install` works
> without a checkout. The installer is idempotent (SHA-256 hashing) and
> writes a manifest for clean updates and uninstall.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `carter: command not found` | `~/.local/bin` not on `PATH` — run `uv tool update-shell` and reload your shell (see [Install](#install)) |
| `uv tool upgrade` says "Nothing to upgrade" | Force a reinstall from the latest commit: `uv tool install --force git+https://github.com/mauriciomem/carter-ai.git` |
| Agents not appearing in VS Code | Restart VS Code; agents load from `~/.copilot/agents/` (system) or `.github/agents/` (workspace) on startup |
| MCP server conflicts | Carter installs alongside existing servers as `carter-*`; remove the original to avoid duplicate tools |
| Missing tokens for `--mcp` | Run `carter install --mcp -v` to see which env vars are unset |

## License

GPL-3.0
