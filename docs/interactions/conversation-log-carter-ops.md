# Carter-Ops Design Session — Conversation Log

> Date: May 10, 2026
> Topic: Deterministic operational tasks for Carter (Git + Jira)
> Format: Grill-me interview — question by question design resolution

---

## Context

The user performs daily operational tasks that are fully deterministic and visible to others:

**Git:**
- Create feature branches, add files, commit them, and push to the feature branch

**Jira:**
- Create a comment in a Jira ticket regarding the status or progress of the ticket
- Create a Jira ticket (bug, task, story) with all important data best practices suggest

**Attribution requirements:**
- Jira: A brief disclaimer that the comment was made by `carter-bot`
- Git: A simulated `carter-bot` account with verified commits in GitHub (sign commits with SSH key)

**Constraints:**
- Must support multiple LLMs
- Must be deterministic

**Two patterns found online:**

1. User Request → Intent Extractor (LLM) → Typed Plan → Approval / Validation → Deterministic Executors → Verification → Structured Result

2. Orchestrator agent → Intent classifier (LLM) → Router + param validator → Deterministic zone (executor): functions, commands, etc → Verification → Structured Result

---

## Question 1: Where does the deterministic executor live?

**Options presented:**

1. **Embed in existing agents** — `carter-devops` already has GitHub MCP access; `carter-pm` has Jira MCP. Add a "deterministic mode" to those agents where they emit a structured plan, get approval, then execute via MCP. No new architectural layer.

2. **New cross-cutting executor layer** — A dedicated `carter-ops` agent (or skill) that sits below the specialist agents. The specialist produces a typed intent, `carter-ops` validates params and executes deterministically. This is closer to both patterns found online.

3. **Skills-only approach** — No new agent. Instead, `carter-pipeline` and `carter-atlassian` skills are enhanced with structured plan → approve → execute workflows baked into the skill instructions.

**Recommendation:** Option 3 (skills-only). The existing skills with MCP access already handle the domain. Adding a protocol to skill instructions keeps the architecture flat.

**Decision:** User agreed initially, but subsequent questions revealed limitations.

---

## Question 2: Does the skills-only approach scale?

**Problem identified:** With 5+ operational skills (GitHub, Jira, Terraform, AWS, Vault), each independently implementing plan → approve → execute leads to:
- Duplicated plan/approve/execute logic
- Inconsistent attribution
- No single audit trail

**Options presented:**

**A. Shared instructions file** — A `carter-ops-protocol.md` that all operational skills reference. Centralizes the protocol; execution stays in each skill.

**B. Dedicated ops skill** — A single `carter-ops` *skill* (not agent) that any agent can invoke. Owns the deterministic protocol.

**Recommendation:** Option A (shared instructions file). Lightest-weight, just DRYing up a protocol definition.

**Decision:** User pushed back — raised concerns about multi-LLM compatibility and extensibility.

---

## Question 3: Instructions vs. code for determinism

**Core problem:** A shared instructions file relies on the LLM following natural-language instructions consistently. Across Claude, GPT-4, Gemini — each interprets differently. Not deterministic.

**Key insight from both online patterns:** The deterministic zone must be code, not instructions.

**Options presented:**

**A. A `carter-ops` MCP server** — Python MCP server wrapping deterministic operations. LLM calls tools with structured params. Works across all surfaces via MCP.

**B. A CLI tool (`carter-exec`)** — Python script invoked via `run_in_terminal`. Same logic, less structured output.

**C. Wrapper around existing MCP servers** — Thin Python layer for attribution injection and verification.

**Recommendation:** Option A (MCP server).

**Decision:** User rejected the MCP server approach. Chose **Option 2 from Question 1** — a cross-cutting executor as a Python CLI tool. Not a Carter MCP server.

---

## Question 4: Python or Go for `carter-ops`?

| Factor | Python | Go |
|--------|--------|----|
| Distribution | Single file or `uv run` — no compile step | Static binary — no runtime dep |
| Dependencies | `requests`/`httpx` for Jira, `subprocess` for git | Same, compiled in |
| Extensibility | Add module/function, quick iteration | Recompile, more friction |
| Installer | Already Python ecosystem | Separate build artifact |
| Cross-platform | Works with Python 3.11+ (already required) | Zero deps, but build step |

**Recommendation:** Python. Entire Carter toolchain is Python. `uv run` gives dependency isolation. The executor is a thin coordination layer — doesn't need Go's performance.

**Decision:** Python. Agreed.

---

## Question 5: Invocation contract — how does the LLM call `carter-ops`?

**Options presented:**

**A. Stateful two-phase** — `carter-ops execute --operation X --params '{...}'` returns an execution ID. Then `carter-ops confirm --execution-id abc123` on approval.

**B. Stateless two-phase** — `carter-ops <operation> --dry-run` shows the plan. On approval, `carter-ops <operation> --execute` with the same params replayed.

**Recommendation:** Option B (stateless). Reasons:
1. No state management — pure function, params in → result out
2. Simpler debugging — run `--dry-run` yourself to see what the LLM saw
3. LLM-friendly — every LLM can replay params; not all reliably track execution IDs
4. Subcommand pattern is natural CLI design

**Decision:** Stateless two-phase. Agreed.

---

## Question 6: Carter-bot attribution mechanics

### Git Attribution

**Options:**
- A/C. Sign with existing SSH key, override `--author` to `carter-bot`. GitHub shows "Verified" (signed by you) with `carter-bot` as author. Honest attribution.
- B. Separate SSH key for carter-bot. More separation, more key management.

**Recommendation:** A/C — use existing SSH key, override author. GitHub shows: *Signed by mmitolo, authored by carter-bot*.

**Decision:** Use existing key with carter-bot author. Agreed.

### Jira Attribution

Comments are always posted as the authenticated user (your account). Attribution must be in content, not metadata.

**Options:**
- Header: `🤖 Posted by carter-bot on behalf of [name]` at top
- Footer: `_This comment was generated by carter-bot._` at bottom

**Decision:** Footer. Less intrusive.

---

## Question 7: Operation scope at launch + extension mechanism

### Launch Operations

| Subcommand | Params | What `--dry-run` shows | What `--execute` does |
|---|---|---|---|
| `git-branch` | `--name`, `--from` (default: `main`) | "Will create branch `feature/X` from `main`" | `git checkout <from> && git pull && git checkout -b <name>` |
| `git-commit` | `--message`, `--files` (list or `.`) | "Will commit N files as carter-bot" | `git add <files> && git commit --author="carter-bot" -S -m "..."` |
| `git-push` | `--branch` (default: current) | "Will push branch to origin" | `git push origin <branch>` |
| `jira-comment` | `--ticket`, `--body` | "Will add comment to PROJ-123 with carter-bot footer" | Calls Jira REST API, appends footer |
| `jira-create` | `--project`, `--type`, `--summary`, `--description`, `--priority`, `--labels` | "Will create type in project" | Calls Jira REST API, appends footer |

### Jira API Access

Direct Jira REST API calls from `carter-ops` using `httpx` + same env vars as MCP server (`ATLASSIAN_TOKEN`, `ATLASSIAN_EMAIL`, `ATLASSIAN_URL`). No dependency on a Jira CLI.

### Extension Mechanism

Plugin pattern with a registry. Each operation implements a two-method interface:

```python
class GitCommit(Operation):
    name = "git-commit"
    
    def dry_run(self, params) -> Plan:
        """Return what would happen."""
    
    def execute(self, params) -> Result:
        """Do it and return structured result."""
```

Directory structure:

```
carter-ops/
├── carter_ops.py       # CLI entry point
├── operations/
│   ├── __init__.py     # auto-discovers Operation subclasses
│   ├── git_branch.py
│   ├── git_commit.py
│   ├── git_push.py
│   ├── jira_comment.py
│   └── jira_create.py
├── attribution.py      # Shared: footer templates, git author config
├── output.py           # Structured JSON output formatting
└── config.py           # Env var loading, validation
```

**Decision:** Agreed on all — operation set, direct API for Jira, plugin pattern.

---

## Question 8: How do skills know to use `carter-ops`?

**Options:**

**A. Split by read vs. write** — Skills use `carter-ops` for any write operation. Read operations use MCP or direct commands as today.

**B. Split by explicit operation list** — Each SKILL.md lists which actions go through `carter-ops`. More granular, more maintenance.

**Recommendation:** Option A (read vs. write). Simple rule the LLM can follow consistently.

Skills would add a `<deterministic-operations>` section:

```markdown
<deterministic-operations>
For any operation that modifies state (commits, pushes, branch creation, 
ticket creation, comments), use `carter-ops` via the terminal:

1. Run with `--dry-run` to generate the plan
2. Show the plan to the user
3. On approval, run with `--execute`

Do NOT run git write commands or Jira write operations directly.
Read operations (git log, git status, JQL queries, reading tickets) 
use normal tools.
</deterministic-operations>
```

**Decision:** Read/write boundary. Agreed.

---

## Question 9: Where does `carter-ops` live?

**Options:**

**A. Directory structure in repo, installed to `~/.carter/ops/`**

```
ai-assistant/
├── ops/                    # Source
│   ├── carter_ops.py
│   ├── operations/
│   ├── attribution.py
│   ├── output.py
│   └── config.py
```

Installer copies to `~/.carter/ops/` and creates `~/.local/bin/carter-ops` wrapper:

```bash
#!/bin/bash
exec uv run ~/.carter/ops/carter_ops.py "$@"
```

**B. Single-file script** — simpler to install, but unwieldy as operations grow.

**Recommendation:** Option A (directory structure). 5+ operations at launch, extensibility is the point. Installer already copies directory trees.

**Future iteration:** Promote to proper Python project with `src/` layout, `pyproject.toml`, proper packaging.

**Decision:** `~/.carter/ops/` with directory structure. Agreed. Future iteration noted for proper project structure.

---

## Question 10: Error handling and output contract

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (dry-run plan or execution completed) |
| `1` | Validation error (missing params, bad ticket key, branch already exists) |
| `2` | Execution error (git push rejected, Jira API 403, network failure) |
| `3` | Configuration error (missing env vars, signing key not found) |

### Output Format

Always JSON to stdout. Stderr for human-readable errors.

**Dry-run output:**
```json
{
  "phase": "dry-run",
  "operation": "git-commit",
  "steps": ["git add src/auth.py", "git commit --author='carter-bot <...>' -S -m '...'"],
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
  "result": {"commit_sha": "a1b2c3d", "branch": "...", "files_committed": 1},
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

Key detail: `suggestion` field tells the LLM what to do next on failure — keeps recovery deterministic.

**Decision:** Agreed on exit codes, JSON output, and error structure.

---

## Question 11: Testing strategy

### Three layers

**Unit tests (per-operation):**
- `dry_run()` always safe to test
- `execute()` mocked (`subprocess` for git, `httpx` for Jira)

**Integration tests (real git, fake Jira):**
- Git: Temp repo in `/tmp`, real `carter-ops` calls, verify commit author/signature
- Jira: Mock HTTP server (`respx` or `pytest-httpserver`), verify request body has footer

**End-to-end (Docker, from v2 plan):**
- Existing Docker integration infrastructure adds a scenario for `carter-ops`

### Test directory structure

```
tests/
├── conftest.py
├── test_install.py
└── ops/
    ├── conftest.py          # Shared fixtures (temp git repo, mock Jira)
    ├── test_git_branch.py
    ├── test_git_commit.py
    ├── test_git_push.py
    ├── test_jira_comment.py
    └── test_jira_create.py
```

**Decision:** Unit + git integration tests at launch. Jira mock server in second iteration. E2E via Docker already planned. Agreed.

---

## Question 12: Configuration approach

**Options:**

**A. Environment variables only** — Same pattern as MCP servers.

**B. Config file + env vars** — `~/.carter/config.toml` for non-secret settings. Secrets stay in env vars.

**Recommendation:** Option B. Non-secrets in file (can commit to dotfiles), secrets in env vars.

```toml
# ~/.carter/config.toml
[attribution]
name = "carter-bot"
email = "carter-bot@users.noreply.github.com"
footer = "This comment was generated by carter-bot."

[git]
signing_key = "~/.ssh/id_ed25519"

[jira]
url = "https://yourcompany.atlassian.net"
email = "you@company.com"
# token comes from JIRA_TOKEN env var — never in config file
```

**`~/.carter/` directory becomes:**

```
~/.carter/
├── config.toml    # Non-secret settings
└── ops/           # The executor code
    ├── carter_ops.py
    └── operations/
```

**Decision:** Config file + env vars for secrets. Agreed.

---

## Question 13: Coexistence with MCP servers

**Question:** Do the Jira/GitHub MCP servers stay?

| Operation type | With carter-ops |
|---|---|
| Git writes (commit, push, branch) | `carter-ops` via terminal |
| Git reads (log, status, diff) | Direct git commands (unchanged) |
| Jira writes (create, comment, update) | `carter-ops` via terminal |
| Jira reads (search, view ticket) | `carter-atlassian` MCP (unchanged) |
| GitHub reads (PRs, issues, Actions) | `carter-github` MCP (unchanged) |
| GitHub writes (create PR, merge) | Future `carter-ops` operation |

**Universal rule:** MCP for reads, `carter-ops` for writes.

**Decision:** Keep MCP servers for reads. `carter-ops` for writes. Agreed.

---

## Decisions Summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Architecture | Cross-cutting executor layer (Python CLI), not embedded in skills or MCP server |
| 2 | Language | Python (with `uv run`, PEP 723 inline deps) |
| 3 | Invocation | Stateless two-phase: `--dry-run` then `--execute` (same params replayed) |
| 4 | Git attribution | `--author="carter-bot"` + signed with user's existing SSH key |
| 5 | Jira attribution | Footer: `_This comment was generated by carter-bot._` |
| 6 | Launch operations | `git-branch`, `git-commit`, `git-push`, `jira-comment`, `jira-create` |
| 7 | Jira API access | Direct REST API via `httpx` (same credentials as MCP server) |
| 8 | Extension mechanism | Plugin pattern — `Operation` base class, auto-discovery in `operations/` |
| 9 | Read/write boundary | MCP for reads, `carter-ops` for writes |
| 10 | Skill integration | `<deterministic-operations>` section in skill SKILL.md files |
| 11 | Install location | `~/.carter/ops/` with `~/.local/bin/carter-ops` wrapper |
| 12 | Configuration | `~/.carter/config.toml` for non-secrets + env vars for secrets |
| 13 | Output contract | JSON to stdout, exit codes 0-3, `suggestion` field on errors |
| 14 | Testing | Unit (mocked) + integration (real git, mock Jira) + E2E (Docker, later) |
| 15 | MCP coexistence | MCP servers stay for reads; `carter-ops` handles all writes |
| 16 | Future | Promote to proper Python project (`src/`, `pyproject.toml`) in later iteration |

---

---

## Question 14: Composite operations

**Problem:** Common workflow (branch → commit → push) requires 6 tool calls and 3 approvals with atomic operations.

**Options:**
- A. Composite subcommands (pre-built multi-step operations)
- B. Batch mode (JSON array of operations)
- C. No composites, let LLM chain with single approval

**Decision:** Option A — composite subcommands for known workflows, atomic operations still available.

Launch composites:

| Composite | Steps |
|---|---|
| `git-flow` | branch → add → commit (as carter-bot, signed) → push |
| `jira-update` | add comment (with footer) + optionally transition status |

---

## Question 15: Audit log

**Options:**
- A. No audit log — rely on Git/Jira native history
- B. Append-only JSONL file at `~/.carter/audit.log`
- C. Structured log directory with date-based folders

**Decision:** Option B — append-only JSONL.

Entry fields: `timestamp` (ISO 8601), `operation`, `params` (minus secrets), `result` (success/failure + identifiers), `dry_run` (the approved plan).

Not logged: secrets, full Jira body text, file contents.

---

## Question 16: Installer changes

### A. Always installed or opt-in?

**Decision:** Always installed. Skills reference `carter-ops` — if missing, write operations break.

**v2 note:** Add `--with-ops` flag that injects `<deterministic-operations>` blocks into skill SKILL.md files at install time. Source skills stay clean; ops-awareness becomes a deployment decision.

### B. Config generation

**Decision:** Generate `~/.carter/config.toml` with sensible defaults, user edits later. Git signing key auto-detected from `git config user.signingkey` if set. Jira values optional — validated on first use.

### C. PATH integration

**Decision:** OS-aware binary placement using installer's existing OS detection:

| OS | Binary location | Shell profile to warn about |
|---|---|---|
| macOS | `~/.local/bin/carter-ops` | `~/.zshrc` |
| Linux | `~/.local/bin/carter-ops` | `~/.bashrc` or `~/.zshrc` (detect active shell) |

Installer checks if `~/.local/bin` is on `$PATH`. If not, warns with the export command to add.

---

## Question 17: Skill SKILL.md updates

**Decision:** Keep both raw command examples (educational reference) and add `<deterministic-operations>` block (behavioral override).

- Raw commands explain what's happening under the hood — useful when Carter explains git or when working without Carter.
- `<deterministic-operations>` block overrides execution behavior for when the LLM is acting.

The `<deterministic-operations>` block template:

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

---

## Question 18: Agent awareness

**Decision:** Brief note in `carter-devops` and `carter-pm` agent definitions:

```markdown
## Deterministic Operations

Write operations (git commits, Jira ticket creation, etc.) go through `carter-ops`
as defined in each skill's <deterministic-operations> section. Read operations use
MCP servers directly.
```

Maestro does not need changes — routing chain is intact.

---

## Question 19: Trigger keyword

**Decision:** `ops:` prefix at Maestro level as a fast-path keyword. Optional — normal inference chain still works without it.

Maestro routing table addition:

```markdown
| Domain | Agent | Triggers |
|--------|-------|----------|
| Deterministic operations | @carter-devops or @carter-pm (auto-detect) | ops:, execute, commit, push, create ticket |
```

When Maestro sees `ops:`, it passes context to the agent signaling explicit operational request.

---

## Question 20: Scope boundary

**Principle:** `carter-ops` is a dumb executor. It never decides what to do — only does what it's told, safely.

| In scope | Out of scope |
|---|---|
| Git write operations | Git read operations |
| Jira write operations | Jira read operations (JQL, view) |
| Attribution injection | Content generation (commit messages, ticket descriptions) |
| Execution verification | Decision-making about what to execute |

**Validation:** Loose — validates structure (required params present, ticket key format, branch name format). Does NOT validate content quality (that's the skill's domain).

**Rollback:** Not at launch. If needed later, new operations via plugin pattern.

---

## Question 21: Auto-PR creation

**Decision:** Moved to v2. At launch, `git-flow` does branch → commit → push only.

v2 addition: `git-pr` operation via `gh pr create` with `--draft` default.

---

## Question 22: Completeness check

All open questions resolved. v2 backlog captured:

1. Promote `carter-ops` to proper Python project (`src/` layout, `pyproject.toml`)
2. Installer `--with-ops` flag that injects `<deterministic-operations>` into skills at install time
3. `git-pr` operation via `gh` CLI (draft default)
4. Rollback operations (`git-undo`, `jira-delete-comment`)
5. Jira mock server for integration tests

---

## Decisions Summary

| # | Decision | Choice |
|---|----------|--------|
| 1 | Architecture | Cross-cutting executor layer (Python CLI), not embedded in skills or MCP server |
| 2 | Language | Python (with `uv run`, PEP 723 inline deps) |
| 3 | Invocation | Stateless two-phase: `--dry-run` then `--execute` (same params replayed) |
| 4 | Git attribution | `--author="carter-bot"` + signed with user's existing SSH key |
| 5 | Jira attribution | Footer: `_This comment was generated by carter-bot._` |
| 6 | Launch operations | `git-branch`, `git-commit`, `git-push`, `git-flow` (composite), `jira-comment`, `jira-create`, `jira-update` (composite) |
| 7 | Jira API access | Direct REST API via `httpx` (same credentials as MCP server) |
| 8 | Extension mechanism | Plugin pattern — `Operation` base class, auto-discovery in `operations/` |
| 9 | Read/write boundary | MCP for reads, `carter-ops` for writes |
| 10 | Skill integration | `<deterministic-operations>` section in skill SKILL.md files |
| 11 | Install location | `~/.carter/ops/` with `~/.local/bin/carter-ops` wrapper |
| 12 | Configuration | `~/.carter/config.toml` for non-secrets + env vars for secrets |
| 13 | Output contract | JSON to stdout, exit codes 0-3, `suggestion` field on errors |
| 14 | Testing | Unit (mocked) + integration (real git, mock Jira) + E2E (Docker, later) |
| 15 | MCP coexistence | MCP servers stay for reads; `carter-ops` handles all writes |
| 16 | Audit log | Append-only JSONL at `~/.carter/audit.log` |
| 17 | Composites | `git-flow` and `jira-update` at launch; atomic ops still available |
| 18 | Installer | Always installed, defaults config, OS-aware PATH |
| 19 | Skills | Keep raw commands + add `<deterministic-operations>` override block |
| 20 | Agents | Brief ops note in `carter-devops` and `carter-pm` |
| 21 | Trigger keyword | `ops:` prefix at Maestro level for fast-path |
| 22 | Scope | Dumb executor, loose validation, no rollback at launch |
| 23 | Future | Proper Python project, install-time skill injection, `git-pr`, rollback ops |
