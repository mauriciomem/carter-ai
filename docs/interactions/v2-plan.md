# Carter v2 — Implementation Plan

> Builds on the v1 foundation with enhanced CLI output, additional skills/MCP servers, Docker testing, packaging, and advanced memory features.

---

## 1. Overview

v2 extends Carter with seven workstreams that can be implemented independently. Each has its own prerequisites, implementation steps, and acceptance criteria. They are ordered by value/effort ratio.

---

## 2. Skill Architecture

This section defines how Carter skills are structured, organized, and extended.

### 2.1 Skill Types

| Type | Pattern | When to use |
|------|---------|-------------|
| **Tool skill** | Router SKILL.md + sub-files | Technology-specific skills (terraform, packer, python, etc.) |
| **Process skill** | Single SKILL.md | Methodology/workflow skills (adr, code-review, plan, etc.) |

### 2.2 Router Pattern (Tool Skills)

Tool skills use SKILL.md as an entry point that routes to specialized sub-files:

```
skills/carter-<tool>/
├── SKILL.md        # Entry point: core conventions + routing table
├── <topic-a>.md    # Specialized reference (loaded on demand)
├── <topic-b>.md    # Another specialized reference
└── <topic-c>.md    # ...
```

**SKILL.md structure:**
1. Standard frontmatter (`name`, `description`, `argument-hint`)
2. `<routing>` section with a keyword → file mapping table
3. `<guidelines>` section with core conventions (always loaded)

**Routing mechanism:** The routing table instructs the agent to use `read_file` to load the sibling file before answering. The agent matches request keywords against the table and loads only the relevant sub-file. If no specialized topic matches, the core guidelines in SKILL.md are sufficient.

**Example routing table:**
```markdown
| File | Load when the request involves |
|------|-------------------------------|
| testing.md  | .tftest.hcl, assertions, run blocks |
| modules.md  | module extraction, moved blocks, state migration |
```

### 2.3 Split Threshold

A tool skill should be split into sub-files when:
- The main SKILL.md exceeds **~300 lines**, OR
- The skill covers a **clearly distinct subtopic** that can stand alone

Until then, keep everything in SKILL.md. The skill is "router-ready" — new subtopics go into sub-files rather than bloating the main file.

### 2.4 Naming Conventions

**Skill directories:** `carter-<tool-name>` (lowercase, hyphens)

**Sub-files:**
- Lowercase with hyphens (`github-cli.md`, not `GitHubCLI.md`)
- Short, descriptive **topic nouns** (`testing.md`, not `how-to-test.md`)
- No prefix repetition (`aws.md`, not `packer-aws.md` — it's already inside `carter-packer/`)
- `SKILL.md` is always the entry point — never rename it

### 2.5 Installer Behavior

The installer copies **all files** in a skill directory, not just SKILL.md. This means sub-files are automatically installed alongside SKILL.md without any changes to the installer.

### 2.6 Current Skill Inventory

**Router skills (tool, with sub-files):**

| Skill | Sub-files |
|-------|-----------|
| `carter-terraform` | `testing.md`, `modules.md`, `import.md`, `stacks.md` |
| `carter-packer` | `aws.md`, `azure.md`, `windows.md`, `hcp.md` |
| `carter-pipeline` | `github-cli.md`, `strategies.md`, `actions.md` |

**Router-ready skills (tool, single file for now):**

| Skill | Lines | Expand when |
|-------|-------|-------------|
| `carter-python` | ~216 | pytest deep-dive, packaging/uv, async patterns |
| `carter-golang` | ~254 | go test, concurrency, modules |
| `carter-atlassian` | ~259 | Confluence operations, automation rules |

**Process skills (single SKILL.md, no sub-files expected):**

`carter-adr`, `carter-code-review`, `carter-design-review`, `carter-diagram`, `carter-distill`, `carter-explain`, `carter-mistakes`, `carter-plan`, `carter-research`, `carter-risk`, `carter-test-first`, `carter-triage`

---

## 3. Workstreams

### 3.1 Rich CLI Output

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

### 3.2 Additional Skills

**Goal:** Add new skills and restructure existing ones following the Skill Architecture (Section 2).

#### Completed

| Change | Type | Details |
|--------|------|---------|
| `carter-terraform` restructured | Tool (router) | Trimmed to ~255-line entry point + 4 sub-files: `testing.md`, `modules.md`, `import.md`, `stacks.md` |
| `carter-packer` created | Tool (router) | New skill from external reference. Entry point + 4 sub-files: `aws.md`, `azure.md`, `windows.md`, `hcp.md` |
| `carter-pipeline` merged | Tool (router) | Absorbed `carter-git-strategy`. Entry point covers core git; sub-files: `github-cli.md`, `strategies.md`, `actions.md` |
| `carter-git-strategy` deleted | — | Content merged into `carter-pipeline/strategies.md` |
| `carter-atlassian` created | Tool (single) | Jira operations + ticket writing best practices via Atlassian MCP server |
| Installer updated | Infrastructure | Now copies all files in a skill directory, not just SKILL.md |

#### Remaining

| Skill | Type | Agent | Description |
|-------|------|-------|-------------|
| `carter-refactor` | Process (single) | Engineer | Detect code smells, suggest refactoring patterns (Extract Method, Replace Conditional with Polymorphism, etc.), provide before/after examples |
| `carter-container` | Tool (router) | DevOps | Dockerfile best practices, K8s manifests, Helm chart review. Anticipated sub-files: `dockerfile.md`, `kubernetes.md`, `helm.md` |
| `carter-roadmap` | Process (single) | PM | Visual timeline generation (Mermaid Gantt), milestone dependency mapping, Jira epic integration via MCP |
| `carter-standup` | Process (single) | PM | Pull recent git commits, Jira issues, PR activity; summarize into "Yesterday / Today / Blockers" format |

**Implementation per skill:**
1. Create `skills/carter-<name>/SKILL.md` with standard frontmatter
2. For tool skills: add `<routing>` section if starting with sub-files, or mark as router-ready
3. Update the relevant agent's `.md` file to list the new skill
4. Installer picks up new skills automatically (copies all `skills/carter-*/` contents)
5. Update README skill table

**Acceptance criteria:** Each skill responds correctly when invoked, follows Carter's global instructions, follows Skill Architecture conventions (Section 2), and integrates with relevant MCP servers.

---

### 3.3 Additional MCP Servers

**Goal:** Add AWS and Vault MCP servers with appropriate guardrails. Each gets a corresponding **tool skill** (single SKILL.md, router-ready — expand to sub-files when crossing ~300 lines).

#### 3.3.1 AWS MCP Server (`carter-aws`)

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

### 3.4 Docker Integration Tests

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

### 3.5 Git-Backed Knowledge Sync

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

### 3.6 Packaging

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

## 4. Implementation Order

Recommended sequence based on dependencies and value:

| Phase | Workstream | Status | Depends On | Complexity |
|-------|-----------|--------|------------|------------|
| v2.1 | Rich CLI Output (3.1) | Not started | v1 complete | Low |
| v2.2 | Additional Skills (3.2) | **Partial** — terraform/packer/pipeline/atlassian done; refactor/container/roadmap/standup remaining | v1 complete | Low |
| v2.3 | Additional MCP Servers (3.3) | Not started | v1 complete, v2.4 (for testing) | Medium |
| v2.4 | Docker Integration Tests (3.4) | Not started | v1 complete | Medium |
| v2.5 | Git-Backed Knowledge Sync (3.5) | Not started | v1 complete | Medium |
| v2.6 | Packaging (3.6) | Not started | v2.1 (Rich), v2.2 (all skills) | High |

**Recommended approach:** Finish v2.2 remaining skills and v2.1 (quick wins), then v2.4 (testing foundation), then v2.3/v2.5 in parallel, and v2.6 last.

---

## 5. Migration Notes

### v1 → v2 Upgrade Path

- **No breaking changes** — v2 is additive. All v1 installations continue to work.
- **Skill architecture** — Existing single-file skills continue to work. Router pattern is additive.
- **Rich output** — Automatic when `rich` is available via PEP 723. Falls back to ANSI.
- **New skills** — Added by re-running `uv run install.py` after `git pull`. Installer copies all files in each skill directory.
- **New MCP servers** — Opt-in via `--with-aws` / `--with-vault` flags.
- **Packaging** — `uvx carter install` is equivalent to `uv run install.py`. Both work.
- **Knowledge sync** — Opt-in. Existing knowledge files are preserved. User runs `--knowledge-repo` when ready.
