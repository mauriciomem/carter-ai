# Carter

[![CI](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/mauriciomem/carter-ai/actions/workflows/ci.yml)

A multi-agent AI assistant for software architecture, engineering, DevOps,
learning, and project management. Instead of one generic assistant, you get
specialized agents with focused expertise and strict boundaries; a central
orchestrator (**Maestro**) routes each request to the right specialist.

Carter runs on **[OpenCode](https://opencode.ai/v2/docs/) 2.1 or newer** — the only
supported harness (the program that runs the agents and talks to the model).

## Install

**Prerequisites:** [uv](https://docs.astral.sh/uv/), Python 3.11+, and
[OpenCode](https://opencode.ai/v2/docs/) >= 2.1 on your `PATH` (`carter install`
stops with an error if `opencode` is missing or older).

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
| `carter install` | System-level: writes agents, skills and global rules to `~/.config/opencode/`, state to `~/.carter/` |
| `carter init <dir>` | Per-project: scaffolds `.carter/`, `.opencode/agents/` and `AGENTS.md` from templates |

```bash
carter install                  # agents, skills, rules, knowledge seeds
carter install --mcp            # also configure MCP servers (needs tokens)
carter uninstall                # remove (same as: carter install --uninstall)

mkdir -p ~/my-project                          # the directory must exist
carter init ~/my-project --name "my-project"   # scaffold a workspace
```

For MCP servers, set the relevant tokens first (`GITHUB_TOKEN`, `TFE_TOKEN`);
the Atlassian server authenticates via OAuth in your client. See [.env.example](.env.example).

→ Full walkthrough: **[docs/getting-started.md](docs/getting-started.md)**

### Uninstalling

`carter uninstall` (equivalent to `carter install --uninstall`) removes only what
Carter installed and you have not changed:

- **Removed:** `carter-*` agents and skills, the global `~/.config/opencode/AGENTS.md`
  Carter wrote, untouched knowledge seed files, `carter-*` MCP entries in
  `opencode.json`, and `~/.carter/manifest.json`.
- **Kept:** `~/.carter/memories/`, `~/.carter/config.toml`, `~/.carter/audit.log`,
  backups, and any file you edited or wrote yourself — knowledge files, an
  `AGENTS.md` Carter skipped as user-modified, and edited agents/skills. Each
  edited file that is kept is reported with a `⚠ Kept …` warning.

Manifests from older versions may lack content hashes; then knowledge files and
`AGENTS.md` are kept, and only `carter-*` agents/skills are removed.

### Upgrading from a Copilot-era install

Earlier Carter versions also targeted GitHub Copilot and VS Code. That support is gone.

- **State migrates automatically.** The first `carter install` copies knowledge, the
  manifest and backups from `~/.copilot/` to `~/.carter/` (nothing is deleted).
- **Old Copilot/VS Code files stay put.** `carter uninstall --legacy` removes the ones
  the old manifest lists, skipping anything you edited.
- **Edit `carter.yaml`:** delete the `target:` key (it is now an error), and collapse
  each per-target `models:` entry to one OpenCode string, e.g.
  `thinkers: anthropic/claude-opus-5-5`. Then run `carter update .`.

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
| **Narrator** | External-facing content | The external-content specialist (the way Architect is the design specialist) — drafts + **redacts** outward content (PRs, Jira, docs, announcements); substantive outward content should go through the narrator's redaction pass before DevOps transmits it (prompt-level guidance, ADR-0001) |
| **Security** | Defensive review, threat modeling, authorized methodology | any agent can flag a risk; carter-security specializes in defensive review and *authorized* security methodology. Advisory only (it threat-models, reviews, and triages — it does not run attacks); offensive methodology is authorized-context-gated; it never pushes — remediation is a handoff to devops. |

> Maestro is emitted with `mode: primary` and the specialists with `mode: subagent`
> ([OpenCode agents](https://opencode.ai/v2/docs/agents/)). Only Maestro may launch
> subagents, and only `carter-*` ones.

## Carter-Ops — write operations

Write operations (git, GitHub, Jira) run through an approval gate: **plan →
approve → execute → audit**. Trigger with the `ops:` prefix.

```
@carter-maestro ops: create a feature branch, commit my changes, and push
```

Carter shows the exact commands (you stay the commit author; the bot is credited with a
`Co-authored-by:` trailer), waits for your approval,
executes the commands directly, and records the result with `carter ops audit`.

→ Reference: **[docs/carter-ops.md](docs/carter-ops.md)**

## Configuration & templates

Workspace agents are generated from Jinja2 templates (base + per-agent
inheritance) driven by `.carter/carter.yaml`. Edit config, then `carter update .`
to regenerate (knowledge files are never touched); `carter check .` validates the
workspace and runs `opencode debug agents` to confirm OpenCode loads every Carter
agent with its emitted permissions (skipped with a warning if `opencode` is not on
PATH; `--no-harness` skips it explicitly).

| Config key | Effect |
|------------|--------|
| `policy.level` | Risk-based strictness: `guarded` / `strict` (pre-action gates) |
| `models` | Per-agent model by tier, each a single `provider/model[#variant]` string (thinkers = Opus; implementers = Sonnet, incl. pm + narrator; `overrides > profile > tier > default`) |
| `profile` | Cost profile: `quality` (all Opus) or `budget` (Sonnet where safe). See [docs/reference/cost-and-models.md](docs/reference/cost-and-models.md) |
| `personality.skepticism` | How much Carter challenges your decisions |
| `quality_gate.enabled` | Multi-agent review before push |
| `tdd.strict` | Force test-first workflow |
| `redaction.categories` | What the narrator redacts from external-facing content |
| `agents` | Which agents to generate |
| `agent_suffix` | Distinguish workspace agents from global (default `local`) |
| `docs_language` | Language of Carter's internal docs — ADRs, RFCs, `.carter/` plans and knowledge, memories (default `en`). Everything in the repository or sent outward is always English |

→ Config reference and walkthrough: **[docs/getting-started.md](docs/getting-started.md)**

## Strictness policy

Each agent gets an ordered OpenCode
[`permissions:`](https://opencode.ai/v2/docs/permissions/) list (last match wins)
generated from a **risk-based strictness policy** (ADR-0014; categories from
ADR-0010). Everything starts at `ask`; reading and searching are allowed; four risk
categories — **read → local-write → remote-write → dangerous** — are granted per
agent. One `policy.level` knob sets how strict:

| Level | Behaviour |
|-------|-----------|
| `guarded` | The floor and the default — remote-write asks, dangerous asks |
| `strict` | Regulated / prod-critical — remote-write asks, dangerous is denied |

`devops` is the **sole pusher** — the only agent holding `remote-write`/`dangerous`;
risky shell commands are denied for everyone else.

**Limits, stated plainly.** OpenCode has only `allow`/`ask`/`deny`, so Carter's
`gate` tier is emitted as `ask`. Choosing **"Allow always"** at a prompt saves a
project-scoped allow that bypasses that ask from then on. The narrator redaction
handoff is prompt-level guidance, not something OpenCode enforces.

→ Tutorial: **[docs/strictness-policy.md](docs/strictness-policy.md)** · schema: **[docs/reference/frontmatter.md](docs/reference/frontmatter.md)**

## Memory & knowledge

Carter learns from experience across layers: **workspace** (`.carter/knowledge/`),
**system** (`~/.carter/knowledge/`), and raw **memory** (`~/.carter/memories/`)
promoted into knowledge. Lifecycle skills: `carter-mistakes` (capture) →
`carter-distill` (promote) → `carter-reflect` (improve agents from patterns).

→ Reference: **[docs/memory-and-knowledge.md](docs/memory-and-knowledge.md)**

## Plans & state

Plans are directories under `.carter/state/plans/` with machine-readable
frontmatter and verifiable `must_haves`; a session `checkpoint.md` cursor enables
"where were we?" recovery. `carter check` validates the frontmatter contract;
`carter save` commits a recovery snapshot of `.carter/`. carter-ai's own
architecture decisions are ADRs kept maintainer-local under `docs/adr/` (not versioned in this repository).

→ Reference: **[docs/plans-and-state.md](docs/plans-and-state.md)**

## MCP servers

Configured by `carter install --mcp` under `mcp.servers.<name>` in
`~/.config/opencode/opencode.json` ([OpenCode MCP servers](https://opencode.ai/v2/docs/mcp-servers/)).
Their tools have no explicit permission rule, so each call falls to the `ask` baseline.

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
transport, not wired by default). Set
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
templates/     Jinja2 agent + AGENTS.md templates (install, init, update)
skills/        Skill definitions (hand-maintained)
knowledge/     Knowledge-base seed templates
mcp/opencode/  MCP server config templates
docs/          Documentation
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
| `carter install` fails: opencode not found / too old | Install or upgrade [OpenCode](https://opencode.ai/v2/docs/) to 2.1+ and make sure `opencode --version` works |
| Agents not appearing in OpenCode | Run `carter check .` — it runs `opencode debug agents` and names any agent OpenCode dropped. Agents load from `~/.config/opencode/agents/` (system) or `.opencode/agents/` (workspace) |
| `Unknown key 'target'` | Delete `target:` from `.carter/carter.yaml` (see [Upgrading](#upgrading-from-a-copilot-era-install)) |
| `carter uninstall` left files behind | By design: files you edited (or that existed before install) are kept and listed as `⚠ Kept …`. Delete them by hand if you don't need them (see [Uninstalling](#uninstalling)) |
| MCP server conflicts | Carter installs alongside existing servers as `carter-*`; remove the original to avoid duplicate tools |
| Missing tokens for `--mcp` | Run `carter install --mcp -v` to see which env vars are unset |

## License

GPL-3.0
