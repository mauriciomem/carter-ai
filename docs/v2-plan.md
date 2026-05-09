# Carter v2 — Implementation Plan

> Builds on the v1 foundation with enhanced CLI output, additional skills/MCP servers, Docker testing, packaging, and advanced memory features.

---

## 1. Overview

v2 extends Carter with six workstreams that can be implemented independently. Each has its own prerequisites, implementation steps, and acceptance criteria. They are ordered by value/effort ratio.

---

## 2. Workstreams

### 2.1 Rich CLI Output

**Goal:** Upgrade installer output from ANSI/stdlib to `rich` for progress bars, tables, tree views, panels, and spinners.

**Prerequisites:** v1 installer working.

**Implementation:**

1. **Update PEP 723 metadata** in `install.py`:
   ```python
   # /// script
   # requires-python = ">=3.11"
   # dependencies = ["rich>=13.0"]
   # ///
   ```
   `uv run install.py` will automatically install `rich` into an ephemeral environment.

2. **Create `_output.py` module** (or keep inline in `install.py`):
   - Abstract the output layer behind a simple interface so both ANSI and Rich backends can coexist
   - Detect if Rich is available; fall back to ANSI if not
   - Components to implement:
     | Component | Rich API | Purpose |
     |-----------|----------|---------|
     | Header panel | `rich.panel.Panel` | Bordered box with title and version |
     | Environment table | `rich.table.Table` | OS, Python, uv info |
     | Prerequisites list | `rich.console.Console.print` | Checkmarks with dot leaders |
     | Progress bar | `rich.progress.Progress` | Agent/skill installation progress |
     | File tree | `rich.tree.Tree` | Hierarchical file listing |
     | MCP matrix | `rich.table.Table` | Server × target status grid |
     | Summary panel | `rich.panel.Panel` | Final stats with "Next steps" |
     | Spinner | `rich.status.Status` | Per-step spinner while working |

3. **Add `--no-rich` flag** for users who want plain ANSI output even when Rich is available.

4. **Update tests** — Add snapshot tests for Rich output using `rich.console.Console(file=StringIO())` for capture.

**Estimated scope:** ~200 lines of output code changes, 5-8 new test cases.

**Acceptance criteria:**
- `uv run install.py` shows Rich output automatically
- `uv run install.py --no-rich` falls back to ANSI
- All existing tests still pass
- New snapshot tests validate Rich output format

---

### 2.2 Additional Skills

**Goal:** Add the skills deferred from v1.

| Skill | Agent | Description | Implementation Notes |
|-------|-------|-------------|---------------------|
| `carter-refactor` | Engineer | Identify and apply refactoring patterns | Detect code smells (long methods, duplicated code, god objects), suggest specific refactoring patterns (Extract Method, Replace Conditional with Polymorphism, etc.), provide before/after examples |
| `carter-container` | DevOps | Dockerfile and Kubernetes manifests | Dockerfile best practices (multi-stage, non-root, minimal images), K8s manifests (Deployments, Services, ConfigMaps), Helm chart review, security scanning (Trivy) |
| `carter-roadmap` | PM | Milestone-based roadmaps | Visual timeline generation (Mermaid Gantt), milestone dependency mapping, resource allocation across milestones, integration with Jira epics via MCP |
| `carter-standup` | PM | Standup summaries from Git/Jira | Pull recent git commits, open/closed Jira issues, PR activity; summarize into "Yesterday / Today / Blockers" format; supports team-level rollups |

**Implementation per skill:**
1. Create `skills/carter-<name>/SKILL.md` with standard frontmatter
2. Update the relevant agent's `.md` file to list the new skill
3. Update the installer to include the new skill (automatic — installer copies all `skills/carter-*/`)
4. Add golden file for snapshot tests
5. Update README skill table

**Acceptance criteria:** Each skill responds correctly when invoked, follows Carter's global instructions, and integrates with relevant MCP servers.

---

### 2.3 Additional MCP Servers

**Goal:** Add AWS and Vault MCP servers with appropriate guardrails.

#### 2.3.1 AWS MCP Server (`carter-aws`)

**Security considerations:**
- Use OIDC/assume-role where possible (no long-lived access keys)
- Restrict to read-only by default; write operations require explicit opt-in via `--allow-aws-write` install flag
- Environment variables: `AWS_PROFILE`, `AWS_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (or OIDC config)

**Agent access:**
- DevOps: Full access (with write opt-in)
- Architect: Read-only (describe resources, read CloudFormation, read cost data)

**Implementation:**
1. Add `mcp/copilot/aws.json` and `mcp/opencode/aws.json`
2. Add `AWS_PROFILE` and `AWS_REGION` to `.env.example` and credential validation
3. Update installer to conditionally install (`--with-aws` flag or configure in manifest)
4. Add `carter-aws` to relevant agent tool lists
5. Update Copilot CLI MCP setup

#### 2.3.2 Vault MCP Server (`carter-vault`)

**Security considerations:**
- Requires Vault token or auth method configuration
- MCP server should only expose read operations (list secrets, read policies) — never write/delete secrets via AI
- Environment variables: `VAULT_ADDR`, `VAULT_TOKEN` (or `VAULT_AUTH_METHOD`)

**Agent access:**
- DevOps: Read-only (policy review, secret path listing)
- No agent gets write access to secrets

**Implementation:**
1. Add `mcp/copilot/vault.json` and `mcp/opencode/vault.json`
2. Add Vault env vars to `.env.example`
3. Update installer with `--with-vault` flag
4. Add `carter-vault` to DevOps agent tool list
5. Create a `carter-vault-review` skill for policy/config review

**Acceptance criteria:** Both servers install cleanly, connect successfully, and agents can only perform their scoped operations.

---

### 2.4 Docker Integration Tests

**Goal:** End-to-end testing of the installer in clean environments.

**Directory structure:**
```
tests/
├── integration/
│   ├── Dockerfile.clean          # Clean Ubuntu + Python + uv
│   ├── Dockerfile.upgrade        # Pre-populated v1 + new installer
│   ├── Dockerfile.partial        # Partial tool availability
│   ├── docker-compose.test.yml   # Orchestrates all test scenarios
│   ├── test_integration.py       # Integration test runner
│   └── scripts/
│       ├── mock-copilot.sh       # Mock copilot CLI for MCP tests
│       └── verify-install.sh     # Post-install verification script
```

**Test scenarios:**

| Scenario | Container | What It Validates |
|----------|-----------|-------------------|
| Clean install | `Dockerfile.clean` | Full install from scratch, all files placed correctly |
| No optional tools | `Dockerfile.partial` | Graceful degradation, correct warnings for missing tools |
| Upgrade v1→v2 | `Dockerfile.upgrade` | Idempotent update, correct `updated`/`unchanged` reporting |
| Uninstall | Post-install | Complete cleanup, no orphaned files, non-Carter files preserved |
| MCP merge conflicts | Pre-existing servers | Merge preserves existing, warns on conflicts |
| OpenCode parity | With OpenCode config | Agent/skill/MCP files match expected format |
| Credential validation | Partial env vars | Correct warnings, no secrets leaked in output |
| Target-specific | copilot-only, opencode-only | Only target files are written, other target untouched |

**CI integration:**
```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]

jobs:
  unit:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv run --with pytest pytest tests/test_install.py -v

  integration:
    runs-on: ubuntu-latest
    needs: unit
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f tests/integration/docker-compose.test.yml up --build --abort-on-container-exit
```

**Implementation steps:**
1. Create Dockerfiles for each scenario
2. Create `docker-compose.test.yml` with service definitions
3. Create mock scripts for tools not available in containers (copilot CLI)
4. Write `test_integration.py` that runs inside containers and validates outcomes
5. Create `.github/workflows/test.yml` for CI
6. Document how to run integration tests locally: `docker compose -f tests/integration/docker-compose.test.yml up --build`

**Acceptance criteria:** All scenarios pass in CI. Local developer can run integration tests with a single `docker compose` command.

---

### 2.5 Git-Backed Knowledge Sync

**Goal:** Enable syncing Carter's knowledge base across machines via a Git repository.

**Design:**

```
~/.copilot/knowledge/   ← Git repo (initialized by installer or manually)
├── .git/
├── decisions.md
├── mistakes.md
├── patterns.md
├── debugging.md
├── infrastructure.md
└── project-history.md
```

**Implementation:**

1. **New installer flag: `--knowledge-repo <url>`**
   - If provided, clones the repo to `~/.copilot/knowledge/` instead of creating template files
   - If `~/.copilot/knowledge/` already exists and is a git repo, pulls latest

2. **Update `carter-distill` skill:**
   - After appending new entries, auto-commit with a structured message:
     ```
     knowledge: add 3 entries (2 mistakes, 1 pattern)

     - mistakes: Terraform state lock timeout
     - mistakes: Python circular import
     - patterns: Retry with exponential backoff
     ```
   - Push only on explicit user request (`@carter-maestro distill --push`)

3. **New `carter-knowledge-sync` skill:**
   - Pull latest knowledge from remote
   - Resolve merge conflicts (prefer keeping both entries, dedup later)
   - Push local changes
   - Show sync summary

4. **Installer changes:**
   - Add `--knowledge-repo` flag to `install.py`
   - Store repo URL in manifest
   - Update operation checks for git repo and pulls

**Security considerations:**
- Knowledge files may contain project-specific information — use a private repo
- SSH key or token-based auth for push (use existing `GITHUB_TOKEN`)
- `.gitignore` in knowledge repo to exclude any accidental sensitive data

**Acceptance criteria:**
- `uv run install.py --knowledge-repo git@github.com:user/carter-knowledge.git` clones successfully
- `carter-distill` auto-commits entries
- `carter-knowledge-sync` pulls/pushes without data loss
- Merge conflicts are handled gracefully

---

### 2.6 Packaging

**Goal:** Distribute Carter as an installable Python tool via `uvx`.

**Target UX:**
```bash
# Install Carter globally
uvx carter install

# Update
uvx carter update

# Uninstall
uvx carter uninstall

# Specific target
uvx carter install --target copilot
```

**Implementation:**

1. **Restructure project for packaging:**
   ```
   carter/
   ├── pyproject.toml              # Package metadata
   ├── src/
   │   └── carter/
   │       ├── __init__.py
   │       ├── __main__.py         # Entry point: python -m carter
   │       ├── cli.py              # CLI argument parsing
   │       ├── installer.py        # Core install logic (from install.py)
   │       ├── output.py           # Output formatting (ANSI + Rich)
   │       └── data/               # Package data (agents, skills, etc.)
   │           ├── agents/
   │           ├── skills/
   │           ├── knowledge/
   │           ├── mcp/
   │           └── instructions/
   ├── install.py                  # Keep for backward compat (thin wrapper)
   └── tests/
   ```

2. **`pyproject.toml`:**
   ```toml
   [project]
   name = "carter-ai"
   version = "2.0.0"
   description = "AI assistant with expert personalities"
   requires-python = ">=3.11"
   dependencies = []  # stdlib only for core

   [project.optional-dependencies]
   rich = ["rich>=13.0"]

   [project.scripts]
   carter = "carter.cli:main"

   [build-system]
   requires = ["hatchling"]
   build-backend = "hatchling.build"

   [tool.hatch.build.targets.wheel]
   packages = ["src/carter"]
   ```

3. **Include data files** via `importlib.resources` (Python 3.11+):
   ```python
   from importlib.resources import files
   data = files("carter.data")
   ```

4. **Publish to PyPI:**
   - `uv build` to create wheel and sdist
   - `uv publish` to upload to PyPI (or TestPyPI first)
   - GitHub Actions workflow for automated publishing on tag

5. **Keep `install.py` backward-compatible:**
   ```python
   # install.py — backward compatibility wrapper
   from carter.cli import main
   main()
   ```

6. **CI/CD for publishing:**
   ```yaml
   # .github/workflows/publish.yml
   name: Publish
   on:
     push:
       tags: ["v*"]
   jobs:
     publish:
       runs-on: ubuntu-latest
       permissions:
         id-token: write  # For trusted publishing
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v4
         - run: uv build
         - run: uv publish
   ```

**Acceptance criteria:**
- `uvx carter install` works from any machine with `uv`
- `uvx carter --help` shows all commands
- `pip install carter-ai` also works as fallback
- `install.py` still works for users who cloned the repo
- GitHub Actions publishes on tag push

---

## 3. Implementation Order

Recommended sequence based on dependencies and value:

| Phase | Workstream | Depends On | Estimated Complexity |
|-------|-----------|------------|---------------------|
| v2.1 | Rich CLI Output | v1 complete | Low — output layer only |
| v2.2 | Additional Skills | v1 complete | Low — follows established pattern |
| v2.3 | Docker Integration Tests | v1 complete | Medium — Docker + CI setup |
| v2.4 | Additional MCP Servers | v1 complete, v2.3 (for testing) | Medium — security review needed |
| v2.5 | Git-Backed Knowledge Sync | v1 complete | Medium — Git operations + conflict handling |
| v2.6 | Packaging | v2.1 (for Rich), v2.2 (all skills) | High — restructure + publish pipeline |

**Recommended approach:** Implement v2.1 and v2.2 first (quick wins), then v2.3 (testing foundation for the rest), then v2.4/v2.5 in parallel, and v2.6 last since it benefits from having all other features stabilized.

---

## 4. Migration Notes

### v1 → v2 Upgrade Path

- **No breaking changes** — v2 is additive. All v1 installations continue to work.
- **Rich output** — Automatic when `rich` is available via PEP 723. Falls back to ANSI.
- **New skills** — Added by re-running `uv run install.py` after `git pull`.
- **New MCP servers** — Opt-in via `--with-aws` / `--with-vault` flags.
- **Packaging** — `uvx carter install` is equivalent to `uv run install.py`. Both work.
- **Knowledge sync** — Opt-in. Existing knowledge files are preserved. User runs `--knowledge-repo` when ready.
