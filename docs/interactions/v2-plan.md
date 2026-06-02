# Carter v2 — Implementation Plan

> **Superseded by** [plan.md](plan.md) (as-built). This document is an earlier
> design draft kept for historical context. Several items it lists as "v2 work"
> have since shipped — notably `carter-ops` (now the `carter ops` subcommand),
> the unified `carter` CLI distributed via `uv tool`, and the `evals/` framework.
> Where this draft and plan.md disagree, **plan.md is authoritative**.

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

### 3.0 Deterministic Operations — `carter-ops`

**Goal:** Provide a cross-cutting, LLM-agnostic, surface-agnostic deterministic executor for write operations (Git, Jira). The LLM produces structured intent; `carter-ops` validates, executes, attributes, verifies, and logs — in code, not instructions.

**Design reference:** [conversation-log-carter-ops.md](conversation-log-carter-ops.md) — full design session with 22 resolved questions.

#### 3.0.1 Architecture

```
User request
  ↓
Maestro (routes — "ops:" fast-path or normal inference)
  ↓
Specialist agent (carter-devops / carter-pm)
  ↓
Skill (carter-pipeline / carter-atlassian)
  ├── Domain knowledge: formats commit message, structures Jira ticket
  ├── Read operations: direct git commands / MCP servers (unchanged)
  └── Write operations: delegates to carter-ops
        ↓
      carter-ops CLI (Python)
        ├── --dry-run  → JSON plan to stdout → LLM shows to user
        ├── user approves
        └── --execute  → performs action → JSON result to stdout → audit log
```

**Key principles:**
- **Dumb executor** — `carter-ops` never decides *what* to do, only *how* to do it safely
- **Stateless two-phase** — `--dry-run` then `--execute` with replayed params. No execution IDs, no temp files, no sessions
- **MCP for reads, carter-ops for writes** — MCP servers stay for read operations; all write operations go through `carter-ops`
- **Loose validation** — Validates param structure (required present, format correct). Does NOT validate content quality (that's the skill's job)
- **LLM-agnostic** — Works across Claude, GPT, Gemini, any model. The contract is CLI args in → JSON out. No natural-language interpretation variance
- **Surface-agnostic** — Invoked via `run_in_terminal` / terminal on all surfaces (VS Code, Copilot CLI, OpenCode)

#### 3.0.2 File Structure (Source)

```
ai-assistant/
├── ops/                        # Source — copied to ~/.carter/ops/ by installer
│   ├── carter_ops.py           # CLI entry point (PEP 723 inline deps)
│   ├── operations/
│   │   ├── __init__.py         # Auto-discovers Operation subclasses
│   │   ├── git_branch.py
│   │   ├── git_commit.py
│   │   ├── git_push.py
│   │   ├── git_flow.py         # Composite: branch → commit → push
│   │   ├── jira_comment.py
│   │   ├── jira_create.py
│   │   └── jira_update.py      # Composite: comment + optionally transition
│   ├── attribution.py          # Footer templates, git author config
│   ├── output.py               # Structured JSON output formatting
│   └── config.py               # Config file + env var loading, validation
```

**PEP 723 inline metadata in `carter_ops.py`:**
```python
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27"]
# ///
```

**Future iteration (v3):** Promote to proper Python project with `src/` layout, `pyproject.toml`, proper packaging.

#### 3.0.3 Installation Layout

```
~/.carter/
├── config.toml                 # Non-secret settings (generated by installer)
├── audit.log                   # Append-only JSONL audit log (created on first write)
└── ops/                        # Executor code
    ├── carter_ops.py
    ├── operations/
    │   ├── __init__.py
    │   ├── git_branch.py
    │   ├── git_commit.py
    │   ├── git_push.py
    │   ├── git_flow.py
    │   ├── jira_comment.py
    │   ├── jira_create.py
    │   └── jira_update.py
    ├── attribution.py
    ├── output.py
    └── config.py

~/.local/bin/
└── carter-ops                  # Shell wrapper (created by installer)
```

> **As-built correction:** the shipped design has no `~/.local/bin/carter-ops`
> shell wrapper. The executor is invoked as the `carter ops` subcommand of the
> unified CLI; `carter ops <operation> --dry-run/--execute`. The installer's
> `--uninstall` cleans up any *legacy* `~/.local/bin/carter-ops` and `~/.carter/ops/`
> left over from this earlier design. See [plan.md §13.1](plan.md).

**Shell wrapper (`~/.local/bin/carter-ops`):**
```bash
#!/bin/bash
exec uv run ~/.carter/ops/carter_ops.py "$@"
```

#### 3.0.4 Configuration

**`~/.carter/config.toml`** — non-secrets, generated by installer with defaults:

```toml
[attribution]
name = "carter-bot"
email = "carter-bot@users.noreply.github.com"
footer = "This comment was generated by carter-bot."

[git]
signing_key = ""  # Auto-detected from git config user.signingkey if set

[jira]
url = ""          # User fills in
email = ""        # User fills in
# token comes from JIRA_TOKEN env var — never in config file
```

**Environment variables for secrets:**

| Variable | Purpose | Required |
|---|---|---|
| `JIRA_TOKEN` | Jira REST API authentication | For Jira operations |
| `GITHUB_TOKEN` | GitHub API (future `git-pr`) | Future |

#### 3.0.5 Operations

**Atomic operations:**

| Subcommand | Params | `--dry-run` output | `--execute` behavior |
|---|---|---|---|
| `git-branch` | `--name`, `--from` (default: `main`) | "Will create branch `feature/X` from `main`" | `git checkout <from> && git pull && git checkout -b <name>` |
| `git-commit` | `--message`, `--files` (list or `.`) | "Will commit N files as carter-bot: `<message>`" | `git add <files> && git commit --author="carter-bot <carter-bot@users.noreply.github.com>" -S -m "<message>"` |
| `git-push` | `--branch` (default: current) | "Will push `<branch>` to origin" | `git push origin <branch>` |
| `jira-comment` | `--ticket`, `--body` | "Will add comment to PROJ-123 with carter-bot footer" | POST to Jira REST API, appends footer to body |
| `jira-create` | `--project`, `--type`, `--summary`, `--description`, `--priority`, `--labels` | "Will create `<type>` in `<project>`: `<summary>`" | POST to Jira REST API, appends footer to description |

**Composite operations:**

| Subcommand | Steps | Single approval |
|---|---|---|
| `git-flow` | `git-branch` → `git add` → `git-commit` → `git-push` | Yes — dry-run shows all steps, one approve, one execute |
| `jira-update` | `jira-comment` + optionally transition ticket status | Yes |

**Scope boundary:**

| In scope (carter-ops) | Out of scope (stays in skills/MCP) |
|---|---|
| `git add`, `git commit`, `git push`, `git branch` | `git log`, `git status`, `git diff`, `git blame` |
| Jira: create ticket, add comment, transition status | Jira: search (JQL), read ticket details, list sprints |
| Attribution injection | Content generation (commit messages, ticket descriptions) |
| Execution verification | Decision-making about what to execute |

#### 3.0.6 Attribution

**Git:**
- `--author="carter-bot <carter-bot@users.noreply.github.com>"` on every commit
- Signed with user's existing SSH key (read from `git config user.signingkey` or `config.toml`)
- GitHub shows: "Verified" (signed by user), authored by carter-bot
- Honest attribution: user's key proves authorization, author field shows AI involvement

**Jira:**
- Footer appended to every comment and ticket description:
  ```
  ---
  _This comment was generated by carter-bot._
  ```
- Footer text configurable in `config.toml`
- Comment posted as authenticated user (Jira API token owner). Attribution is content, not metadata

#### 3.0.7 Output Contract

**Always JSON to stdout.** Stderr for human-readable errors.

**Exit codes:**

| Code | Meaning |
|------|---------|
| `0` | Success (dry-run plan or execution completed) |
| `1` | Validation error (missing params, bad ticket key, branch already exists) |
| `2` | Execution error (git push rejected, Jira API 403, network failure) |
| `3` | Configuration error (missing env vars, signing key not found) |

**Dry-run output:**
```json
{
  "phase": "dry-run",
  "operation": "git-commit",
  "steps": [
    "git add src/auth.py",
    "git commit --author='carter-bot <carter-bot@users.noreply.github.com>' -S -m 'feat(auth): add OAuth2 flow'"
  ],
  "attribution": "Author: carter-bot, Signed-by: mmitolo",
  "side_effects": ["1 new commit on feature/PROJ-123-add-auth"]
}
```

**Execute output:**
```json
{
  "phase": "execute",
  "operation": "git-commit",
  "success": true,
  "result": {
    "commit_sha": "a1b2c3d",
    "branch": "feature/PROJ-123-add-auth",
    "files_committed": 1
  },
  "attribution": "Author: carter-bot, Signed-by: mmitolo"
}
```

**Error output:**
```json
{
  "phase": "execute",
  "operation": "git-push",
  "success": false,
  "error": {
    "code": "PUSH_REJECTED",
    "message": "Remote has changes not present locally. Pull first.",
    "suggestion": "Run: carter-ops git-pull --branch feature/PROJ-123"
  }
}
```

The `suggestion` field on errors keeps recovery deterministic — the tool tells the LLM what to do next rather than letting it guess.

#### 3.0.8 Extension Mechanism

Plugin pattern with auto-discovery. Each operation is a Python module implementing a two-method interface:

```python
from dataclasses import dataclass

@dataclass
class Plan:
    operation: str
    steps: list[str]
    attribution: str
    side_effects: list[str]

@dataclass
class Result:
    success: bool
    result: dict
    attribution: str
    error: dict | None = None

class Operation:
    """Base class for all carter-ops operations."""
    name: str  # Subcommand name (e.g., "git-commit")

    def dry_run(self, **params) -> Plan:
        """Return what would happen. No side effects."""
        raise NotImplementedError

    def execute(self, **params) -> Result:
        """Do it and return structured result."""
        raise NotImplementedError

class GitCommit(Operation):
    name = "git-commit"

    def dry_run(self, message: str, files: list[str]) -> Plan:
        ...

    def execute(self, message: str, files: list[str]) -> Result:
        ...
```

**Adding a new operation:**
1. Create `operations/new_operation.py` with an `Operation` subclass
2. `operations/__init__.py` auto-discovers it (imports all modules, finds subclasses)
3. CLI entry point registers it as a subcommand

No registration boilerplate, no config changes.

#### 3.0.9 Audit Log

Append-only JSONL at `~/.carter/audit.log`. One line per `--execute` call.

```json
{"timestamp": "2026-05-10T14:32:01Z", "operation": "git-commit", "params": {"message": "feat: add auth", "files": ["src/auth.py"]}, "dry_run": {"steps": ["..."], "side_effects": ["..."]}, "result": {"success": true, "commit_sha": "a1b2c3d"}}
```

**Logged:** timestamp, operation, params (minus secrets), the dry-run plan that was approved, success/failure, key identifiers.

**Not logged:** secrets, full Jira body text (could be sensitive), file contents. Only identifiers and metadata.

**Queryable via standard tools:**
```bash
# All git commits
cat ~/.carter/audit.log | jq 'select(.operation == "git-commit")'

# Failed operations
cat ~/.carter/audit.log | jq 'select(.result.success == false)'

# Today's operations
cat ~/.carter/audit.log | jq 'select(.timestamp | startswith("2026-05-10"))'
```

#### 3.0.10 Skill Integration

Skills that have write operations add a `<deterministic-operations>` block. The block sits alongside existing raw command examples — commands stay as educational reference; the block overrides execution behavior.

**`carter-pipeline/SKILL.md` addition:**

```markdown
<deterministic-operations>
## Write Operations — Use carter-ops

All state-changing operations MUST go through `carter-ops` via the terminal.

**Protocol:**
1. Prepare the parameters using the domain knowledge in this skill
2. Run `carter-ops <operation> [params] --dry-run` to generate the plan
3. Present the plan to the user for approval
4. On approval, run `carter-ops <operation> [params] --execute`
5. Report the structured result to the user

**Available operations:**
| Operation | When to use |
|-----------|-------------|
| `git-branch` | Creating a new branch |
| `git-commit` | Committing staged files |
| `git-push` | Pushing to remote |
| `git-flow` | Branch + commit + push in one flow |

Do NOT run `git add`, `git commit`, `git push` directly.
Read operations (`git log`, `git status`, `git diff`) remain direct.
</deterministic-operations>
```

**`carter-atlassian/SKILL.md` addition:**

```markdown
<deterministic-operations>
## Write Operations — Use carter-ops

All state-changing operations MUST go through `carter-ops` via the terminal.

**Protocol:**
1. Prepare the parameters using the domain knowledge in this skill
2. Run `carter-ops <operation> [params] --dry-run` to generate the plan
3. Present the plan to the user for approval
4. On approval, run `carter-ops <operation> [params] --execute`
5. Report the structured result to the user

**Available operations:**
| Operation | When to use |
|-----------|-------------|
| `jira-comment` | Adding a comment to a ticket |
| `jira-create` | Creating a new ticket (bug, task, story, epic) |
| `jira-update` | Comment + transition status |

Do NOT use MCP write tools for Jira directly.
Read operations (JQL queries, viewing tickets) still use the carter-atlassian MCP server.
</deterministic-operations>
```

#### 3.0.11 Agent Integration

Brief note added to `carter-devops` and `carter-pm` agent definitions:

```markdown
## Deterministic Operations

Write operations (git commits, Jira ticket creation, etc.) go through `carter-ops`
as defined in each skill's <deterministic-operations> section. Read operations use
MCP servers directly.
```

#### 3.0.12 Maestro Integration

**`ops:` fast-path keyword.** When Maestro sees `ops:` prefix in user request, it short-circuits to the operational agent (auto-detects `carter-devops` for git, `carter-pm` for Jira) with context signaling explicit operational request.

Maestro routing table addition:

```markdown
| Domain | Agent | Triggers |
|--------|-------|----------|
| Deterministic operations | @carter-devops or @carter-pm (auto-detect) | ops:, execute, commit, push, create ticket |
```

The keyword is optional — without it, the normal inference chain still works.

#### 3.0.13 Installer Changes

The installer (`install.py`) adds these steps:

1. **Copy `ops/`** → `~/.carter/ops/`
2. **Generate `~/.carter/config.toml`** with defaults. Auto-detect `signing_key` from `git config user.signingkey`. Use `--bot-name` value if provided.
3. **Create `~/.local/bin/carter-ops`** wrapper script
4. **PATH check** — OS-aware detection:
   - macOS: check `~/.zshrc` for `~/.local/bin`
   - Linux: check `~/.bashrc` or `~/.zshrc` (detect active shell)
   - If not on PATH, warn: `Add export PATH="$HOME/.local/bin:$PATH" to your shell profile`
5. **Manifest update** — Track `~/.carter/` files alongside existing `~/.copilot/` files

**CLI flags:**

| Flag | Default | Description |
|------|---------|-------------|
| `--mcp` | off | Install and configure MCP servers. Without this flag, MCP servers are skipped. |
| `--bot-name NAME` | `carter-bot` | Git commit author name for carter-ops attribution. Used in `config.toml` and email derivation. |

**Installer output addition:**
```
→ Installing carter-ops...
  ✓ ~/.carter/ops/ (7 operations)
  ✓ ~/.carter/config.toml (defaults — edit Jira settings before use)
  ✓ ~/.local/bin/carter-ops
  ⚠ ~/.local/bin is not on PATH — add to ~/.zshrc:
    export PATH="$HOME/.local/bin:$PATH"
```

#### 3.0.14 Testing

**Test directory structure:**
```
tests/
├── conftest.py
├── test_install.py
└── ops/
    ├── conftest.py              # Shared fixtures (temp git repo, mock Jira server)
    ├── test_git_branch.py
    ├── test_git_commit.py
    ├── test_git_push.py
    ├── test_git_flow.py
    ├── test_jira_comment.py
    ├── test_jira_create.py
    └── test_jira_update.py
```

**Three test layers:**

| Layer | What | How |
|-------|------|-----|
| Unit | Each operation's `dry_run()` and `execute()` | Mock `subprocess.run` (git) and `httpx` (Jira). Verify correct commands/payloads |
| Integration (git) | Real git operations | Temp repo in `/tmp`, run `carter-ops` against it. Verify commit exists, author is `carter-bot`, SSH signature present |
| Integration (Jira) | Jira API calls | Mock HTTP server (`respx` or `pytest-httpserver`). Verify request body contains footer. **Deferred to second iteration** |
| E2E | Full install + operation | Docker containers (existing v2 Docker infrastructure). **Deferred to Docker workstream** |

**Launch scope:** Unit tests + git integration tests. Jira mock server and Docker E2E in subsequent iterations.

#### 3.0.15 v2 Backlog (Future `carter-ops` Enhancements)

| Enhancement | Description |
|---|---|
| Proper Python project | Promote to `src/` layout, `pyproject.toml`, proper packaging |
| Install-time skill injection | `--with-ops` flag injects `<deterministic-operations>` blocks into skills at install time |
| Rollback operations | `git-undo` (reset last commit), `jira-delete-comment` |
| Jira mock server tests | `pytest-httpserver` or `respx` for Jira integration tests |
| Confluence operations | Add `confluence-create`, `confluence-update` operations |
| Terraform operations | Add `terraform-plan`, `terraform-apply` operations |
| AWS operations | Add AWS-scoped operations with IAM guardrails |

---

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
| v2.0 | Deterministic Ops (3.0) | Not started | v1 complete | High |
| v2.1 | Rich CLI Output (3.1) | Not started | v1 complete | Low |
| v2.2 | Additional Skills (3.2) | **Partial** — terraform/packer/pipeline/atlassian done; refactor/container/roadmap/standup remaining | v1 complete | Low |
| v2.3 | Additional MCP Servers (3.3) | Not started | v1 complete, v2.4 (for testing) | Medium |
| v2.4 | Docker Integration Tests (3.4) | Not started | v1 complete | Medium |
| v2.5 | Git-Backed Knowledge Sync (3.5) | Not started | v1 complete | Medium |
| v2.6 | Packaging (3.6) | Not started | v2.1 (Rich), v2.2 (all skills) | High |

**Recommended approach:** Start with v2.0 (carter-ops — enables deterministic workflows immediately), then v2.2 remaining skills and v2.1 (quick wins), then v2.4 (testing foundation), then v2.3/v2.5 in parallel, and v2.6 last.

---

## 5. Migration Notes

### v1 → v2 Upgrade Path

- **No breaking changes** — v2 is additive. All v1 installations continue to work.
- **Skill architecture** — Existing single-file skills continue to work. Router pattern is additive.
- **Rich output** — Automatic when `rich` is available via PEP 723. Falls back to ANSI.
- **carter-ops** — Always installed. Creates `~/.carter/` directory, `~/.local/bin/carter-ops` wrapper. Skills gain `<deterministic-operations>` block but existing behavior is preserved for read operations.
- **New skills** — Added by re-running `uv run install.py` after `git pull`. Installer copies all files in each skill directory.
- **New MCP servers** — Opt-in via `--with-aws` / `--with-vault` flags.
- **Packaging** — `uvx carter install` is equivalent to `uv run install.py`. Both work.
- **Knowledge sync** — Opt-in. Existing knowledge files are preserved. User runs `--knowledge-repo` when ready.
