# Carter-Ops — Direct Execution with Bot Attribution

> The model runs commands directly with bot attribution flags, approval gate, and post-hoc audit logging.

---

## 1. Problem Statement

### What Previous Approaches Tried

Every previous approach attempted to force the model to call the `carter-ops` CLI tool instead of running git/API commands directly:

| Version | Strategy | Failure Mode |
|---------|----------|-------------|
| v1 | "Use carter-ops" in instructions | Model had no awareness of carter-ops |
| v2 | Three-layer enforcement (instructions + agents + skills) | Model ran raw git commands |
| v3 | Explicit terminal language + negative examples + competing signal removal | Documented but never implemented |
| v4 | Single skill + `ops:` trigger (current) | Model still fabricates output or bypasses CLI |

### The Fundamental Insight

From a working cross-project example (eigenoid), the same model with the same `ops:` trigger ran:

```bash
git checkout -b mauri/issue-70-file-permission-hardening
git add eigenoid/orchestration/container.py eigenoid/orchestration/supervisor.py eigenoid/conversation/filesystem.py
git commit -m "fix(security): harden file permissions on generated artifacts ..."
git push -u origin mauri/issue-70-file-permission-hardening
```

It did NOT call `carter-ops`. It just executed the operations correctly and reported the result. This worked because:

1. The model knows how to run git commands — it's a natural behavior, not something to suppress
2. No indirection layer confused the execution chain
3. No CLI parameter translation was needed (the model already had all the information)
4. No two-phase protocol interrupted execution momentum

**The CLI was the wrong enforcement mechanism.** Instructions cannot force tool invocation across LLM providers, model versions, and integration surfaces. The model will always find a path of least resistance.

### What Actually Needs to Be Deterministic

The carter-ops CLI was designed to guarantee three things:

1. **Bot attribution** — commits authored by `mauri-droid`, signed with user's key
2. **Audit trail** — JSONL log of every write operation
3. **Approval gate** — user sees plan before execution

None of these require a CLI middleman. The model can:
- Add `--author` and `-S` flags to `git commit` directly
- A post-hoc hook or the skill itself can audit
- The model already shows plans and asks for approval (this is natural LLM behavior)

---

## 2. Design: Option C — Direct Execution with Bot Attribution

### Architecture

```
User: "ops: create branch, commit changes, push"
  │
  └─→ Model (loads carter-ops skill)
        │
        ├─ ASSESS: git status, git diff (read operations)
        │
        ├─ PLAN: Show structured plan to user
        │    "I will: create branch X, commit files A,B,C with message M, push"
        │
        ├─ APPROVAL: User confirms (or model proceeds if instructed)
        │
        ├─ EXECUTE: Run commands directly in terminal
        │    git checkout -b branch-name
        │    git add file1 file2
        │    git commit --author='mauri-droid <283785827+mauri-droid@users.noreply.github.com>' -S -m "message"
        │    git push -u origin branch-name
        │
        ├─ AUDIT: carter-ops audit --log '{"operation":"git-flow","params":{...},"result":"success"}'
        │
        └─ REPORT: Show result to user
```

### What Changes

| Concern | Previous (CLI-based) | Current (direct execution) |
|---------|--------------|---------------|
| Who runs git commands | `carter-ops` CLI (subprocess) | Model directly (terminal) |
| Attribution injection | CLI adds `--author` and `-S` internally | Model adds `--author` and `-S` flags per skill instructions |
| Plan generation | CLI `--dry-run` generates JSON plan | Model generates structured text plan |
| Approval gate | Implied by skill (show JSON → ask) | Explicit in skill (show plan → ask) |
| Audit logging | CLI writes to `~/.carter/audit.log` | `carter-ops audit` subcommand (post-hoc) |
| Error handling | CLI returns JSON with `suggestion` field | Model reads stderr, skill teaches recovery patterns |
| Jira/GitHub API | CLI wraps httpx calls | Model runs `gh` CLI or `curl`/MCP for API operations |
| Parameter translation | Model → CLI params → subprocess | Model → direct commands (no translation) |

### What Stays the Same

- `ops:` prefix triggers the skill
- Approval gate (user sees plan, confirms)
- Bot attribution on every commit
- Audit trail (JSONL at `~/.carter/audit.log`)
- `~/.carter/config.toml` as source of truth for bot name, email, signing key
- One-liner in every agent file loads the skill

---

## 3. Detailed Design

### 3.1 The `ops:` Skill — Complete Rewrite

The `carter-ops` skill is rewritten. It no longer references a CLI tool. Instead, it teaches the model HOW to execute operations directly with the correct attribution flags.

#### Skill Responsibilities

| # | Responsibility | How |
|---|---|---|
| 1 | Recognize intent | Parse what the user wants from natural language |
| 2 | Assess state | Run read commands (`git status`, `git diff`, `git log`) |
| 3 | Plan | Construct the exact commands, show to user as structured text |
| 4 | Seek approval | Ask user to confirm (mandatory gate) |
| 5 | Execute | Run commands in terminal with attribution flags |
| 6 | Audit | Call `carter-ops audit` to append JSONL entry |
| 7 | Report | Show user what happened |

#### Attribution Constants

The skill embeds these values (sourced from `~/.carter/config.toml` at install time, baked into the skill):

```
BOT_NAME:    Read from config, e.g. "mauri-droid"
BOT_EMAIL:   Read from config, e.g. "283785827+mauri-droid@users.noreply.github.com"
SIGNING_KEY: Read from config, e.g. "~/.ssh/id_rsa_github"
```

However, the skill CANNOT read a file at runtime. So the model must run:

```bash
carter-ops config --emit
```

This prints the config values as shell-exportable variables the model can use.

**Alternative (simpler):** The skill instructions simply say "use `--author` from `~/.carter/config.toml`" and trust the model to read the file once. This is fragile. Better: the install script bakes the values directly into the installed SKILL.md (template substitution).

**Decision:** Install-time template substitution. The SKILL.md installed at `~/.copilot/skills/carter-ops/SKILL.md` contains the actual bot name, email, and signing key path — not placeholders.

#### Git Operations — Command Templates

The skill teaches exact command patterns:

**Create branch:**
```bash
git checkout main && git pull origin main && git checkout -b <branch-name>
```

**Stage and commit:**
```bash
git add <file1> <file2> ...
git commit --author='{{BOT_NAME}} <{{BOT_EMAIL}}>' -S -m "<message>"
```

**Push:**
```bash
git push -u origin <branch-name>
```

**Complete flow (branch + commit + push):**
```bash
git checkout main && git pull origin main && git checkout -b <branch-name>
git add <file1> <file2> ...
git commit --author='{{BOT_NAME}} <{{BOT_EMAIL}}>' -S -m "<message>"
git push -u origin <branch-name>
```

#### GitHub Operations — via `gh` CLI

```bash
# Create issue
gh issue create --repo <owner/repo> --title "<title>" --body "<body>" --label "<labels>"

# Comment on issue
gh issue comment <number> --repo <owner/repo> --body "<body>"

# Create PR
gh pr create --repo <owner/repo> --title "<title>" --head <branch> --base <base> --body "<body>" --draft

# Comment on PR
gh pr comment <number> --repo <owner/repo> --body "<body>"
```

Footer attribution is appended to `--body`:
```
<body>\n\n---\n_This was generated by {{BOT_NAME}}._
```

#### Jira Operations — via `curl` to REST API v2

```bash
# Comment
curl -s -X POST \
  -u "${ATLASSIAN_EMAIL}:${ATLASSIAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  "${ATLASSIAN_URL}/rest/api/2/issue/<TICKET>/comment" \
  -d '{"body": "<body>\n\n_This comment was generated by {{BOT_NAME}}._"}'

# Create issue
curl -s -X POST \
  -u "${ATLASSIAN_EMAIL}:${ATLASSIAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  "${ATLASSIAN_URL}/rest/api/2/issue" \
  -d '{"fields": {"project": {"key": "<PROJECT>"}, "issuetype": {"name": "<TYPE>"}, "summary": "<SUMMARY>", "description": "<DESC>"}}'

# Transition
curl -s -X POST \
  -u "${ATLASSIAN_EMAIL}:${ATLASSIAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  "${ATLASSIAN_URL}/rest/api/2/issue/<TICKET>/transitions" \
  -d '{"transition": {"id": "<ID>"}}'
```

### 3.2 The Approval Gate

The model MUST show a plan and wait for user approval before executing any write operation. This is the **single deterministic guarantee** that remains instruction-enforced.

**Why this works when CLI invocation didn't:** Showing a plan and asking for confirmation is **natural LLM behavior** — every model does this by default for destructive operations. The previous failure was making the model use a specific tool. The approval gate doesn't require a tool; it requires the model to NOT execute yet, which is the default-safe behavior.

**Plan format:**

```markdown
## Plan

**Operation:** git-flow (branch + commit + push)
**Branch:** mauri/issue-70-file-permission-hardening
**Files:** eigenoid/orchestration/container.py, eigenoid/orchestration/supervisor.py, eigenoid/conversation/filesystem.py
**Message:** fix(security): harden file permissions on generated artifacts
**Attribution:** mauri-droid <283785827+mauri-droid@users.noreply.github.com>, signed with ~/.ssh/id_rsa_github

Commands to execute:
1. git checkout main && git pull origin main && git checkout -b mauri/issue-70-file-permission-hardening
2. git add eigenoid/orchestration/container.py eigenoid/orchestration/supervisor.py eigenoid/conversation/filesystem.py
3. git commit --author='mauri-droid <283785827+mauri-droid@users.noreply.github.com>' -S -m "fix(security): harden file permissions..."
4. git push -u origin mauri/issue-70-file-permission-hardening

Approve?
```

**Why structured text, not JSON:** The previous versions showed JSON (or fabricated it). JSON is for machine consumption. The plan is for human consumption. Structured Markdown is clearer.

### 3.3 Post-Hoc Audit Logging

The `carter-ops` CLI is not removed — it's **reduced to a utility**. Its only remaining commands:

| Command | Purpose |
|---|---|
| `carter-ops audit` | Append a JSONL entry to `~/.carter/audit.log` |
| `carter-ops config --emit` | Print config values (bot name, email, key path) |
| `carter-ops --list` | List available operation names (for validation) |

The model runs `carter-ops audit` AFTER executing commands:

```bash
carter-ops audit --operation git-flow \
  --params '{"branch":"mauri/issue-70","message":"fix: ...","files":["a.py","b.py"]}' \
  --result success \
  --identifiers '{"commit_sha":"abc1234","branch":"mauri/issue-70"}'
```

**Why post-hoc and not pre-execution:** If the model skips the audit call, the operation still succeeded — audit is best-effort. The audit doesn't gate anything. Execution and audit are decoupled by design.

**Risk:** The model may forget to audit. Mitigation: the skill's workflow template includes the audit step. Even if skipped occasionally, the git log and `gh` history provide redundant records.

### 3.4 Error Handling

The skill teaches error recovery patterns instead of relying on the CLI's `suggestion` field:

**Push rejected (non-fast-forward):**
```
If `git push` fails with "rejected" or "non-fast-forward":
→ Run: git pull origin <branch> --rebase
→ Resolve any conflicts
→ Retry: git push -u origin <branch>
```

**Branch already exists:**
```
If `git checkout -b` fails with "already exists":
→ Ask user: switch to existing branch or pick a new name?
```

**Jira API 403:**
```
If curl returns HTTP 403:
→ Check: are ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN, ATLASSIAN_URL set?
→ Report the error to user with variable names to check
```

**Signing failure:**
```
If `git commit -S` fails:
→ Check: does the signing key exist at the configured path?
→ Fallback: ask user if they want to commit without signing
```

### 3.5 Read/Write Boundary

This boundary is UNCHANGED from v4:

| Type | Handled by | Examples |
|---|---|---|
| Git reads | Direct commands (no `ops:` needed) | `git status`, `git log`, `git diff`, `git blame` |
| Git writes | `ops:` skill (direct execution with attribution) | commit, push, branch creation |
| GitHub reads | MCP server `carter-github` or `gh` CLI | view issues, PRs, Actions |
| GitHub writes | `ops:` skill (via `gh` CLI with footer) | create issue, PR, comment |
| Jira reads | MCP server `carter-atlassian` | JQL search, view tickets |
| Jira writes | `ops:` skill (via `curl` to v2 API with footer) | comment, create, transition |

---

## 4. Edge Cases & Failure Modes

### 4.1 Model Forgets Attribution Flags

**Scenario:** Model runs `git commit -m "fix: thing"` without `--author` or `-S`.

**Why this is likely:** Attribution flags are extra cognitive load. The model's natural instinct is to run the simplest command.

**Mitigation:**
1. The skill's command template section shows the FULL command with attribution every time — no "shorthand" variants
2. The plan display (approval step) includes the full command with flags visible, so both model and user can verify
3. If the commit was made without attribution, it's still a valid commit — the user can amend

**Severity:** Medium. Wrong attribution is cosmetic, not destructive. The commit still works.

### 4.2 Model Skips the Approval Gate

**Scenario:** Model sees `ops:` and just executes without showing a plan first.

**Why this is likely:** The eigenoid example proved this is the model's natural behavior — assess and execute. Adding an approval gate is an artificial stop the model may skip.

**Mitigation:**
1. The skill instruction says "ALWAYS show plan and wait for approval before any write command"
2. This is **more natural** than "use a CLI tool" — models already pause for destructive operations by default
3. The plan format is simple structured text (not JSON to fabricate)
4. If the model executes without approval and the result is correct, the user still got what they wanted

**Severity:** Low. The approval gate is a UX preference, not a safety control. The model will usually show what it intends to do anyway.

### 4.3 Signing Key Not Found

**Scenario:** `git commit -S` fails because the signing key doesn't exist at the configured path.

**Mitigation:** The skill teaches: "If `-S` fails, show the error and ask user if they want to proceed without signing." The install-time baked path means this should be correct from day one.

### 4.4 `gh` CLI Not Installed

**Scenario:** Model tries `gh issue create` but `gh` is not on PATH.

**Mitigation:** 
1. The installer can check for `gh` presence and warn
2. The skill can teach: "if `gh` is not available, fall back to `curl` with GITHUB_TOKEN"
3. Alternatively, treat `gh` as a prerequisite (it already is for most GitHub workflows)

### 4.5 Jira Auth Env Vars Not Set

**Scenario:** Model runs `curl` to Jira API but `ATLASSIAN_API_TOKEN` is empty.

**Mitigation:** The skill teaches: "Before any Jira operation, verify env vars are set. Run `echo $ATLASSIAN_URL` to check. If empty, tell user which variables to set."

### 4.6 Model Fabricates the Plan (Old Problem)

**Scenario:** Model shows a "plan" it made up without assessing actual state.

**Why this matters LESS now:** Previously, the plan was supposed to be JSON output from a CLI tool — fabricating it was indistinguishable from real output. Now, the plan is structured text the model generates itself. There's no fake/real distinction. The plan IS what the model intends to do. The user reads it and decides.

**However:** The model might show a plan that doesn't match what it actually executes (different files, different message).

**Mitigation:** The plan shows the EXACT commands that will run. The user can verify post-hoc by checking `git log --oneline -1` output.

### 4.7 Partial Execution Failure

**Scenario:** Branch creation succeeds, commit succeeds, push fails (non-fast-forward).

**Mitigation:** The skill teaches recovery patterns (see 3.4). The model reports the partial state and suggests next steps. This is identical to how v4 handled it (carter-ops git-flow could also fail mid-way).

### 4.8 Audit Log Skipped

**Scenario:** Model executes operations but forgets to call `carter-ops audit`.

**Severity:** Low. The audit log is best-effort enrichment. The git log, GitHub history, and Jira history ARE the authoritative records. The carter audit log is a convenience index.

**Mitigation:** Make audit the LAST step in the workflow template. If the model forgets, the primary data sources remain intact.

### 4.9 Multi-Repo or Remote Operations

**Scenario:** User says "ops: push this to the eigenoid repo" while in a different directory.

**Mitigation:** The model already handles this naturally — it knows to `cd` to the correct directory or use `--repo` flags. No special handling needed vs. v4.

### 4.10 Config Values Change After Install

**Scenario:** User edits `~/.carter/config.toml` (e.g., changes bot name) but the SKILL.md was baked at install time with old values.

**Mitigation:** The skill can say "read bot name from `~/.carter/config.toml` if it exists, otherwise use the defaults below." Alternatively, re-run `uv run install.py` to rebake. This is an acceptable trade-off — config changes are rare.

**Decision:** Use a hybrid: bake defaults into SKILL.md but instruct the model to check `~/.carter/config.toml` for overrides.

---

## 5. Implementation Plan

### 5.1 Files to Change

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | `skills/carter-ops/SKILL.md` | Complete rewrite — direct execution model with templates, approval gate, audit step | P0 |
| 2 | `ops/carter_ops.py` | Add `audit` subcommand, add `config --emit` subcommand, keep `--list` | P0 |
| 3 | `instructions/copilot-instructions.md` | Simplify to: "When request starts with `ops:`, load `carter-ops` skill" (remove old enforcement language) | P1 |
| 4 | `agents/carter-maestro.md` | Keep one-liner trigger, remove any old enforcement blocks | P1 |
| 5 | `agents/carter-devops.md` | Keep one-liner trigger, ensure no contradicting instructions | P1 |
| 6 | `agents/carter-pm.md` | Keep one-liner trigger | P1 |
| 7 | `install.py` | Update skill installation to bake config values into SKILL.md template | P1 |
| 8 | `docs/carter-ops.md` | Rewrite architecture section, update design decisions | P2 |
| 9 | `skills/carter-pipeline/SKILL.md` | No changes needed — write examples already reference carter-ops | P2 (verify only) |
| 10 | `ops/operations/*.py` | Keep for backward compat; can be deprecated later | P3 (no change) |

### 5.2 New SKILL.md Structure

```markdown
---
name: carter-ops
description: "Deterministic executor for operational tasks. Triggered by the `ops:` keyword prefix."
---

<objective>
Execute write operations (git, GitHub, Jira) with bot attribution, approval gate,
and post-hoc audit logging. Run commands directly — no intermediary CLI.
</objective>

<config>
## Attribution Config

Read from ~/.carter/config.toml:
- bot_name = "{{BOT_NAME}}"           ← baked at install time
- bot_email = "{{BOT_EMAIL}}"         ← baked at install time  
- signing_key = "{{SIGNING_KEY}}"     ← baked at install time

If config.toml differs from the values above, use the config.toml values.
</config>

<workflow>
## Required Workflow

1. ASSESS — Run read commands to understand current state (git status, git diff, etc.)
2. PLAN — Show the user a structured plan with exact commands and attribution
3. APPROVE — Wait for user confirmation before executing any write command
4. EXECUTE — Run commands in terminal with attribution flags
5. AUDIT — Run: carter-ops audit --operation <name> --params '<json>' --result <success|failure>
6. REPORT — Tell user what happened

NEVER execute write commands without showing the plan first.
</workflow>

<git-operations>
## Git Operations

### Create branch
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>

### Stage and commit
git add <files>
git commit --author='{{BOT_NAME}} <{{BOT_EMAIL}}>' -S -m "<message>"

### Push
git push -u origin <branch-name>

### Complete flow
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
git add <files>
git commit --author='{{BOT_NAME}} <{{BOT_EMAIL}}>' -S -m "<message>"
git push -u origin <branch-name>
</git-operations>

<github-operations>
## GitHub Operations (via gh CLI)

Append footer to all --body values: "\n\n---\n_This was generated by {{BOT_NAME}}._"

gh issue create --repo <owner/repo> --title "<title>" --body "<body>" [--label "<labels>"]
gh issue comment <number> --repo <owner/repo> --body "<body>"
gh pr create --repo <owner/repo> --title "<title>" --head <branch> --base <base> --body "<body>" [--draft]
gh pr comment <number> --repo <owner/repo> --body "<body>"
</github-operations>

<jira-operations>
## Jira Operations (via curl to REST API v2)

Requires: ATLASSIAN_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN env vars.
Append footer to all body text: "\n\n_This comment was generated by {{BOT_NAME}}._"
Use REST API v2 (wiki markup in body field), NOT v3 (ADF JSON).

### Comment
curl -s -X POST \
  -u "${ATLASSIAN_EMAIL}:${ATLASSIAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  "${ATLASSIAN_URL}/rest/api/2/issue/<TICKET>/comment" \
  -d '{"body": "<wiki-markup-body>"}'

### Create issue
curl -s -X POST \
  -u "${ATLASSIAN_EMAIL}:${ATLASSIAN_API_TOKEN}" \
  -H "Content-Type: application/json" \
  "${ATLASSIAN_URL}/rest/api/2/issue" \
  -d '{"fields":{"project":{"key":"<KEY>"},"issuetype":{"name":"<TYPE>"},"summary":"<SUMMARY>","description":"<DESC>"}}'
</jira-operations>

<error-recovery>
## Error Recovery

Push rejected: git pull origin <branch> --rebase → retry push
Branch exists: ask user — switch to existing or pick new name
Signing fails: ask user — proceed without -S?
Jira 403: check env vars (ATLASSIAN_URL, ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)
gh not found: suggest `brew install gh` or fall back to curl + GITHUB_TOKEN
</error-recovery>

<boundaries>
## What is NOT ops:

Read operations run directly — no ops: needed:
git log, git status, git diff, git blame, git branch --list, gh issue list, JQL queries
</boundaries>
```

### 5.3 New `carter-ops audit` Subcommand

Add to `ops/carter_ops.py`:

```python
def _handle_audit(params: dict) -> int:
    """Append an audit entry from model's direct execution."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": params.get("operation", "unknown"),
        "phase": "execute",
        "params": json.loads(params.get("params", "{}")),
        "result": params.get("result", "unknown"),
    }
    if params.get("identifiers"):
        entry["identifiers"] = json.loads(params["identifiers"])
    _audit(entry)
    emit({"status": "logged", "operation": entry["operation"]})
    return 0
```

CLI invocation:
```bash
carter-ops audit --operation git-flow --params '{"branch":"x","message":"y"}' --result success --identifiers '{"commit_sha":"abc"}'
```

### 5.4 New `carter-ops config --emit` Subcommand

```python
def _handle_config_emit() -> int:
    """Print config values for model consumption."""
    cfg = Config.load()
    emit({
        "bot_name": cfg.bot_name,
        "bot_email": cfg.bot_email,
        "signing_key": cfg.signing_key,
        "footer": cfg.footer,
        "jira_url": cfg.jira_url,
        "jira_email": cfg.jira_email,
        "has_jira_token": bool(cfg.jira_token),
        "has_github_token": bool(cfg.github_token),
    })
    return 0
```

### 5.5 Install-Time Template Substitution

In `install.py`, when copying `skills/carter-ops/SKILL.md`, replace template variables:

```python
def _install_ops_skill(src: Path, dst: Path, config: Config):
    content = src.read_text()
    content = content.replace("{{BOT_NAME}}", config.bot_name)
    content = content.replace("{{BOT_EMAIL}}", config.bot_email)
    content = content.replace("{{SIGNING_KEY}}", config.signing_key)
    dst.write_text(content)
```

---

## 6. What Gets Removed / Deprecated

### Immediately Removed

- The `--dry-run` / `--execute` two-phase CLI protocol (no longer the execution path)
- The requirement for models to call `carter-ops` CLI for git/GitHub/Jira operations
- All "CRITICAL: Write Operations" enforcement blocks that duplicated across agent files
- The concept of "fabrication" as a failure mode (plan IS model-generated now — that's by design)

### Kept but Reduced

| Component | Previous Role | Current Role |
|---|---|---|
| `carter-ops` CLI | Primary executor for all write ops | Utility only: `audit`, `config --emit`, `--list` |
| `ops/operations/*.py` | Git/Jira/GitHub execution logic | Unused at runtime; kept for reference/tests |
| `~/.carter/config.toml` | Config for CLI execution | Config for attribution values |
| `~/.carter/audit.log` | Written by CLI on every operation | Written by `carter-ops audit` post-hoc |
| Agent one-liner trigger | Loads skill that teaches CLI usage | Loads skill that teaches direct execution |

### Future Removal

Once proven stable:
- Remove `ops/operations/*.py` (the Operation classes)
- Remove `--dry-run` and `--execute` from `carter_ops.py`
- Slim `carter_ops.py` to just `audit` + `config` subcommands

---

## 7. Testing Protocol

### Test 1: Git Flow (VS Code)

```
1. Make a code change in external/test-repo/outputs.tf
2. Type: "ops: create a feature branch, commit only the outputs.tf change and push"
```

**Pass criteria:**
- [ ] Model shows a structured plan with exact commands including `--author` and `-S` flags
- [ ] Model waits for approval
- [ ] Model runs git commands directly in terminal (not carter-ops CLI)
- [ ] Commit has correct author (`git log --format='%an <%ae>' -1` shows bot name)
- [ ] Commit is signed (`git log --show-signature -1`)
- [ ] Model calls `carter-ops audit` after execution

**Acceptable deviations:**
- [ ] Model skips `carter-ops audit` (audit is best-effort)
- [ ] Model uses slightly different plan format (as long as commands are shown)

### Test 2: GitHub Issue (VS Code)

```
"ops: create a GitHub issue in owner/repo titled 'Bug: auth fails' with body 'Token refresh returns 401'"
```

**Pass criteria:**
- [ ] Model runs `gh issue create` with footer appended
- [ ] Issue is created with correct title, body, and footer

### Test 3: Cross-Project (Eigenoid)

```
cd ~/Documents/random/python/eigenoid
"ops: create a feature branch from issue #70, commit only code changes, push"
```

**Pass criteria:**
- [ ] Model reads issue title from GitHub
- [ ] Model creates branch with issue-derived name
- [ ] Model commits with bot attribution
- [ ] Model pushes and reports result

### Test 4: Error Recovery

```
1. Create a branch that already exists on remote
2. "ops: push this branch"
```

**Pass criteria:**
- [ ] Model encounters push rejection
- [ ] Model explains the error and suggests rebase or force-push

---

## 8. Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Model forgets `--author` flag | Medium | Low (cosmetic) | Template in skill shows full command; plan display includes flags |
| Model skips approval gate | Low | Low (UX preference) | Models naturally pause for write ops; skill reinforces |
| Model skips audit call | Medium | Low (best-effort) | Git/GitHub/Jira history is authoritative anyway |
| `gh` CLI not installed | Low | Medium (blocks GitHub ops) | Installer checks; skill teaches fallback |
| Config values change post-install | Low | Low (re-run install) | Skill reads config.toml as override |
| Model runs wrong files in git add | Medium | Medium (wrong commit) | Plan shows exact files; approval gate catches this |
| Jira v2 API deprecated | Low | High (blocks Jira ops) | Monitor Atlassian deprecation notices |

---

## 9. Why This Approach Works

### Alignment with Model Behavior

Previous approaches fought the model's natural behavior. The current design works WITH it:

| Natural model behavior | Previous approach fought it | Current design leverages it |
|---|---|---|
| Model knows git commands | "Don't run git commands" | "Run these git commands with these flags" |
| Model generates plans in text | "Only show CLI JSON output" | "Show your plan as structured text" |
| Model asks before destructive ops | "Use --dry-run phase" | "Show plan, ask approval" |
| Model reads and interprets errors | "CLI returns suggestion field" | "Follow these error recovery patterns" |

### Reduced Failure Surface

The CLI-based approach required the model to:
1. Parse user intent into CLI parameters
2. Construct exact CLI invocation string
3. Actually call the CLI (vs. implementing the protocol itself)
4. Repeat exact parameters for `--execute` phase
5. Not fabricate output between phases

The current approach only requires the model to:
1. Forget to add `--author` flag (visible in plan)
2. Skip the approval step (unnatural for write ops)

The failure surface shrunk from 5 points to 2, and both failures are visible and recoverable.

### Cross-Project Portability

The eigenoid project proved this approach works without any carter-ops-specific infrastructure. Any project with:
- `~/.copilot/instructions/copilot-instructions.md` (one-liner trigger)
- `~/.copilot/skills/carter-ops/SKILL.md` (execution templates)
- `~/.carter/config.toml` (attribution values)

Gets deterministic operations. No per-repo hooks, no PATH manipulation, no CLI discovery issues.

---

## 10. Lessons Learned

1. **Instructions cannot force tool invocation** — No amount of "MUST use X" language reliably prevents model bypass across providers and versions. Design with the grain, not against it.

2. **Work WITH model capabilities, not against them** — Models can run git commands. Let them. Add constraints to HOW they run commands (flags, approval), not WHETHER they can.

3. **The intermediary tool was solving the wrong problem** — Carter-ops CLI provided attribution, audit, and approval. None of these require a CLI middleman. They can be injected into direct commands (attribution flags), done post-hoc (audit logging), or are natural model behavior (showing plans).

4. **Simplicity wins** — The old CLI had 11 operations, plugin discovery, JSON output, two-phase protocol. The current design has command templates and an audit utility. Fewer moving parts = fewer failure modes.

5. **Positive examples beat negative instructions** — "Run this command with these flags" is more reliable than "Don't run this command without these flags."

6. **The approval gate is the only gate that matters** — It's the one control that IS natural to LLMs (pausing before destructive operations) and IS visible to the user (they can verify the plan).

7. **Audit is enrichment, not enforcement** — The git log, GitHub history, and Jira history ARE the authoritative records. A separate audit log is a convenience index, not a critical control. Design it as best-effort.
