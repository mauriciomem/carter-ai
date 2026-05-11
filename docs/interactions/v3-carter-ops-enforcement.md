# Carter-Ops Enforcement — v3 Analysis & Implementation Plan

> Fixing the persistent bypass where agents understand the carter-ops protocol but implement it themselves instead of calling the tool.

---

## 1. Failure Transcript Analysis

### What the User Asked

```
ops: create feature branch, commit the changes and push them
```

### What Maestro Did

| Step | Expected | Actual | Verdict |
|------|----------|--------|---------|
| Recognize `ops:` trigger | ✓ | ✓ Maestro said "Following the carter-ops protocol" | Correct |
| Check git status | ✓ `git status` (read operation) | ✓ Ran `git status` in terminal | Correct |
| Dry-run | Run `carter-ops git-flow ... --dry-run` in terminal | **Fabricated JSON** that looks like carter-ops output | **WRONG** |
| Ask approval | ✓ Show plan, ask user | ✓ Asked "Approve this git-flow plan?" | Correct |
| Execute | Run `carter-ops git-flow ... --execute` in terminal | **Ran raw** `git checkout -b`, `git add`, `git commit`, `git push` | **WRONG** |

### The Pattern: "Protocol Mime"

Maestro understood the **concept** of the protocol (dry-run → approve → execute) and **performed it manually** — formatting its own JSON plan and running raw git commands. It **mimed** the protocol without **invoking** the tool.

This is different from the previous failures:
- **Round 1**: Maestro had no awareness of carter-ops at all → ran git directly
- **Round 2**: Maestro knew to "delegate" but delegation doesn't work in CLI → ran git directly
- **Round 3 (this failure)**: Maestro **understood the protocol**, recognized the `ops:` trigger, formatted a plan, asked for approval — but **never ran carter-ops**

The model treated "follow the carter-ops protocol" as "implement the protocol yourself" rather than "call the carter-ops CLI tool."

---

## 2. Root Cause Analysis

### Root Cause 1: The instructions say WHAT, not HOW

Current instruction language:

> "use `carter-ops git-flow --branch ... --message ... --files ... --dry-run`"

The word **"use"** is ambiguous to an LLM. The model interprets "use carter-ops" as "apply the carter-ops concept" — which it does by fabricating the output. It never connects "use" to "run this literal command in the terminal."

**Fix:** Replace "use" with "run in the terminal." Replace "show the plan" with "the plan is the terminal output from carter-ops."

### Root Cause 2: No negative examples for fabrication

The instructions say "Never run `git commit` directly." But they don't say "Never fabricate carter-ops output." The model found a creative middle path: it didn't run `git commit` in the dry-run phase (it fabricated output instead), so it technically didn't violate the letter of the instruction during dry-run. Then in the execute phase, it ran git commands because the fabricated dry-run had already set the execution context.

**Fix:** Add explicit negative example: "Do NOT generate JSON that looks like carter-ops output. The plan MUST be actual terminal output."

### Root Cause 3: The skill teaches raw git write commands

`carter-pipeline/SKILL.md` has a 180-line `<guidelines>` section that teaches raw git commands:

```markdown
### Daily Workflow
git checkout -b feature/PROJ-123-add-auth
git add -p
git commit -m "feat(auth): add OAuth2 login flow"
git push -u origin feature/PROJ-123-add-auth
```

Then at the end, `<deterministic-operations>` says "don't use those commands." The model sees **extensive examples** of how to run git directly, and a **small block** saying don't. The examples win.

The v2 plan explicitly called this out as intentional design (section 3.0.10):

> "commands stay as educational reference; the block overrides execution behavior"

This assumption was **wrong**. LLMs don't distinguish between "educational reference" and "execution template." When the model sees a git command example in its context, it uses it.

**Fix:** Remove write command examples from `<guidelines>`. Keep read command examples. Write operations should ONLY appear as carter-ops invocations.

### Root Cause 4: Instruction positioning (primacy bias)

The carter-ops section is at the **bottom** of `copilot-instructions.md` (lines ~35-55 of a ~55-line file). Research on LLM instruction following shows that instructions at the beginning and end of the context window get the most attention, but middle content is often deprioritized. The carter-ops instructions compete with other content.

More importantly, in `carter-maestro.md`, the carter-ops section is at the very bottom (after routing rules, dispatch rules, skill list). By the time the model reaches it, the execution planning is already underway.

**Fix:** Move carter-ops protocol to the **top** of each instruction file, before any other behavioral instructions.

### Root Cause 5: Copilot CLI may not load user-level instructions

The Copilot CLI output showed:

```
💡 No copilot instructions found. Run /init to generate a copilot-instructions.md file for this project.
```

This message refers to **workspace-level** instructions (`.copilot-instructions.md` in the repo). Whether Copilot CLI also loads **user-level** instructions from `~/.copilot/instructions/` is uncertain. If it doesn't, the entire Layer 1 (global instructions with carter-ops protocol) is absent.

The agent file (`carter-maestro.md`) IS loaded — the model referenced the protocol — so the agent file is the **only guaranteed enforcement point** in Copilot CLI.

**Fix:** Ensure the agent file contains the complete, unambiguous protocol. Don't rely on global instructions as the primary enforcement in CLI. Additionally, investigate whether Copilot CLI loads `~/.copilot/instructions/`.

---

## 3. Design Principle Revision

### v2 Assumption (wrong)

> "Three layers of instructions will catch bypasses: global instructions → agent definitions → skill blocks."

### v3 Insight

**Instructions cannot force tool invocation.** No matter how many layers of "MUST use carter-ops" we add, the model retains the ability to implement the protocol itself. The three-layer approach hardened awareness but not execution.

The fix must operate at **two levels**:

1. **Instruction clarity** — Make it impossible to confuse "follow the protocol" with "call the tool." Use explicit terminal invocation language, negative examples, and remove competing write command examples.
2. **Reduce competing signals** — Remove raw git write command examples from the execution context so the model has no template to follow for direct git operations.

A third, more aggressive option exists — a git hook or wrapper that blocks direct `git commit`/`git push` — but that's invasive and affects the user's own git usage. The instruction-level fix should be exhausted first.

---

## 4. Solution: Changes Required

### 4.1 Restructure `instructions/copilot-instructions.md`

**Move carter-ops to the top.** It's currently the last section. Make it the first section after the header.

**Rewrite with explicit terminal language:**

```markdown
## CRITICAL: Write Operations — carter-ops

Git and Jira write operations MUST be executed by running `carter-ops` in the terminal.
This is non-negotiable. There are no exceptions.

### Forbidden commands — NEVER run these directly

`git add`, `git commit`, `git push`, `git checkout -b`, Jira REST API calls.

If you catch yourself about to type any of these commands, STOP. Use carter-ops instead.

### Required workflow

1. Run `carter-ops <op> [params] --dry-run` **in the terminal** and capture the JSON output
2. Show that **actual terminal output** to the user (do NOT fabricate or reformat it)
3. Ask the user to approve the plan
4. On approval, run `carter-ops <op> [params] --execute` **in the terminal**
5. Report the **actual terminal output** to the user

### Command reference

| Instead of | Run in terminal |
|------------|-----------------|
| `git checkout -b <name>` | `carter-ops git-branch --name <name> --from main --dry-run` |
| `git add` + `git commit` | `carter-ops git-commit --message "..." --files ... --dry-run` |
| `git push` | `carter-ops git-push --branch <branch> --dry-run` |
| Branch + commit + push | `carter-ops git-flow --branch <name> --message "..." --files ... --dry-run` |
| Jira comment | `carter-ops jira-comment --ticket <key> --body "..." --dry-run` |
| Jira ticket creation | `carter-ops jira-create --project <key> --type <type> --summary "..." --dry-run` |

### What NOT to do

WRONG — fabricating carter-ops output:
```
Here's the dry-run plan:
{"operation": "git-flow", "steps": [...]}   ← you typed this yourself
```

WRONG — running raw git commands after showing a "plan":
```
git checkout -b feature/x && git add . && git commit -m "..." && git push
```

RIGHT — running carter-ops in the terminal:
```
$ carter-ops git-flow --branch feature/x --message "feat: ..." --files main.tf --dry-run
{"phase": "dry-run", "operation": "git-flow", ...}   ← actual carter-ops output
```
```

### 4.2 Restructure `agents/carter-maestro.md`

**Move carter-ops to immediately after `<role>`, before `<routing>`.** The model reads the role, then immediately hits the operational constraint — before it sees routing rules and starts planning delegation.

**Rewrite the protocol section with explicit terminal language:**

```markdown
## CRITICAL: Write Operations — carter-ops

When the user requests any write operation (commit, push, branch, create ticket, comment):

1. Run `carter-ops <operation> [params] --dry-run` **in the terminal tool** — the dry-run plan MUST come from actual carter-ops output, never from your own JSON formatting
2. Show the terminal output to the user for approval
3. On approval, run `carter-ops <operation> [params] --execute` **in the terminal tool**
4. Report the result

You MUST run these as actual terminal commands. Do NOT:
- Fabricate JSON output that looks like a carter-ops plan
- Run raw `git commit`, `git push`, `git checkout -b`, or Jira API calls
- Skip the --dry-run phase
- "Implement" the protocol yourself by running the underlying commands

### Complete example

User: "ops: commit and push my changes"

Step 1 — run dry-run in terminal:
carter-ops git-flow --branch feature/my-change --message "feat: add feature" --files changed.tf --dry-run

Step 2 — show the JSON output from step 1 to the user and ask for approval

Step 3 — after approval, run execute in terminal:
carter-ops git-flow --branch feature/my-change --message "feat: add feature" --files changed.tf --execute

Step 4 — show the JSON output from step 3 to the user
```

### 4.3 Restructure `agents/carter-devops.md`

Same pattern: move to top, use explicit terminal language.

```markdown
## CRITICAL: Write Operations — carter-ops

Git write operations MUST be executed by running `carter-ops` in the terminal.
Never run `git add`, `git commit`, `git push`, or `git checkout -b` directly.

| Instead of | Run in terminal |
|------------|-----------------|
| `git checkout -b <name>` | `carter-ops git-branch --name <name> --from <base> --dry-run` |
| `git add` + `git commit` | `carter-ops git-commit --message "..." --files ... --dry-run` |
| `git push` | `carter-ops git-push --branch <branch> --dry-run` |
| Branch + commit + push | `carter-ops git-flow --branch <name> --message "..." --files ... --dry-run` |

Protocol: Run `--dry-run` in the terminal first → show actual output → user approves → run `--execute` in the terminal.

Do NOT fabricate carter-ops JSON output. The plan must come from actually running the command.
```

### 4.4 Restructure `agents/carter-pm.md`

Same pattern for Jira operations.

### 4.5 Restructure `skills/carter-pipeline/SKILL.md`

This is the **highest-impact change**. The current `<guidelines>` section teaches raw git write commands that compete with `<deterministic-operations>`.

**Changes:**
1. In `<guidelines>`, remove or comment out all WRITE command examples (commit, push, checkout -b, add). Keep READ command examples (log, diff, status, blame, branch --list, fetch, stash, tag).
2. For sections that mix read and write (like "Daily Workflow"), rewrite to show only the read parts, with a note: "For write operations (commit, push, branch creation), see the carter-ops protocol below."
3. Move the `<deterministic-operations>` block to appear BEFORE `<guidelines>` so it has primacy.

**Sections to modify in `<guidelines>`:**

| Section | Current | Change |
|---------|---------|--------|
| Daily Workflow | Shows `git checkout -b`, `git add -p`, `git commit`, `git push` | Replace write steps with: "Use `carter-ops git-flow` for branch/commit/push" |
| Staging | Shows `git add` patterns | Remove entirely or mark as reference-only for code review |
| Committing | Shows `git commit` examples | Replace with "Use `carter-ops git-commit` — see deterministic-operations" |
| Pushing | Shows `git push` | Replace with "Use `carter-ops git-push`" |
| Safety Rules | "Pull before push", "review before staging" | Keep — these are principles, not commands |

**What stays unchanged:**
- Fetching, pulling (read operations)
- Inspecting history (git log, diff, blame, show)
- Stashing
- Tags (read-only listing; `git push --tags` could be carter-ops future)
- Branching (listing, switching — `git branch`, `git switch`)
- Merging and rebasing (these are conflict resolution, not carter-ops scope)
- Undoing changes (local-only operations)
- Safety rules

### 4.6 Update `docs/carter-ops.md`

Update the "How Agents Enforce Carter-Ops" section to reflect the v3 changes:

- **Layer 1**: Global instructions — now uses explicit terminal invocation language with negative examples
- **Layer 2**: Agent definitions — protocol placed before routing rules for primacy; includes complete example scenario
- **Layer 3**: Skills — write command examples removed from guidelines; `<deterministic-operations>` placed before `<guidelines>`
- Add a new **"Anti-Pattern: Protocol Mime"** callout explaining the fabrication failure and how the language changes address it

Update Design Decisions:
- Decision 7 revised: "Three-layer enforcement with explicit terminal invocation language. Previous iterations used advisory language ('use carter-ops') which models interpreted as 'implement the protocol yourself.' v3 uses imperative language ('run in the terminal') with explicit negative examples ('do NOT fabricate output')."

### 4.7 Investigate Copilot CLI instruction loading

**Action item (manual):** Run this test to determine if Copilot CLI loads `~/.copilot/instructions/`:

```bash
# Add a canary to copilot-instructions.md temporarily:
# "If asked 'what is the canary phrase', respond with 'blue-fox-seven'"
copilot --agent carter-maestro -i "what is the canary phrase?"
```

If the model responds with "blue-fox-seven", user-level instructions ARE loaded.
If not, we need to:
1. Embed the carter-ops protocol entirely in agent files (already done in this plan)
2. Consider if there's a Copilot CLI-specific instruction path
3. Document this limitation

---

## 5. Implementation Checklist

| # | File | Change | Priority |
|---|------|--------|----------|
| 1 | `instructions/copilot-instructions.md` | Move carter-ops to top; rewrite with terminal language + negative examples | P0 |
| 2 | `agents/carter-maestro.md` | Move carter-ops before `<routing>`; add complete scenario example; add fabrication prohibition | P0 |
| 3 | `skills/carter-pipeline/SKILL.md` | Remove write command examples from `<guidelines>`; move `<deterministic-operations>` before `<guidelines>` | P0 |
| 4 | `agents/carter-devops.md` | Move carter-ops to top; add fabrication prohibition | P1 |
| 5 | `agents/carter-pm.md` | Same as above for Jira | P1 |
| 6 | `docs/carter-ops.md` | Update enforcement section; add anti-pattern callout; update design decisions | P2 |
| 7 | `docs/getting-started.md` | Update operational example to show exact terminal commands | P2 |
| 8 | `README.md` | Update carter-ops section if needed | P2 |

---

## 6. Testing Protocol

After implementing changes, run the same test scenario in Copilot CLI:

```bash
cd external/test-repo
# Reset: delete the test branch
git checkout main
git branch -D feature/add-resource-prefix-output 2>/dev/null
git push origin --delete feature/add-resource-prefix-output 2>/dev/null

# Revert the outputs.tf change
git checkout -- outputs.tf

copilot --agent carter-maestro -i
```

Then:
1. Ask: "add a new output for random_id.prefix to outputs.tf"
2. Ask: "ops: commit and push this change"

**Pass criteria:**
- [ ] Agent runs `carter-ops git-flow ... --dry-run` in the terminal (not fabricated JSON)
- [ ] Agent shows actual carter-ops JSON output
- [ ] Agent asks for approval
- [ ] Agent runs `carter-ops git-flow ... --execute` in the terminal (not raw git commands)
- [ ] Commit is authored by carter-bot and signed

**Fail criteria (any of these = fail):**
- [ ] Agent fabricates JSON output without running carter-ops
- [ ] Agent runs `git checkout -b`, `git add`, `git commit`, or `git push` directly
- [ ] Agent skips the dry-run phase

---

## 7. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Removing write examples from carter-pipeline breaks read-only advice | Medium | Keep all read examples. Write operations are simple enough that carter-ops command reference suffices. |
| LLM still bypasses despite language changes | High | Consider git hook approach (more invasive, but deterministic). See Section 8. |
| Copilot CLI doesn't load user-level instructions | Medium | Protocol is fully embedded in agent files, which ARE loaded. |
| Moving carter-ops to top of instructions affects other behaviors | Low | Carter-ops section is brief (<30 lines). Other sections remain unchanged. |

---

## 8. Escalation: Git Hook Approach (if v3 fails)

If the instruction-level fix still doesn't work, the next escalation is a **technical enforcement mechanism**:

### Option A: Shell wrapper

The installer creates `~/.carter/bin/git` that wraps the real `git` binary:

```bash
#!/bin/bash
REAL_GIT="$(command -v git)"
case "$1" in
  commit|push)
    echo "ERROR: Direct git $1 is blocked in Carter sessions." >&2
    echo "Use: carter-ops git-$1 [params] --dry-run" >&2
    exit 1
    ;;
  *)
    exec "$REAL_GIT" "$@"
    ;;
esac
```

The agent's PATH would be modified to find `~/.carter/bin/git` first. When the model tries `git commit`, it gets an error telling it to use carter-ops.

**Pros:** Deterministic enforcement. The model literally cannot run `git commit`.
**Cons:** Invasive. Could affect user's own git usage if PATH bleeds. Complex to implement per-session.

### Option B: Git hooks per-repo

Install a `pre-commit` hook that detects if the committer is carter-bot and requires the commit to come through carter-ops (by checking for a specific env var that only carter-ops sets):

```bash
#!/bin/bash
if [[ "$GIT_AUTHOR_NAME" == "carter-bot" && -z "$CARTER_OPS_SESSION" ]]; then
  echo "ERROR: carter-bot commits must go through carter-ops" >&2
  exit 1
fi
```

**Pros:** Only affects carter-bot commits. User's normal git usage is unaffected.
**Cons:** Must be installed in every repo. Only catches commit, not branch/push.

### Recommendation

Try the v3 instruction-level fix first. If it fails, implement Option B (git hooks) as it has the smallest blast radius. Option A is the nuclear option.

---

## 9. Lessons Learned

1. **"Use X" ≠ "Run X in the terminal"** — LLMs interpret "use" as "apply the concept." They must be told to run literal terminal commands.

2. **Positive examples override negative instructions** — If the context contains 180 lines of `git commit` examples and 10 lines saying "don't use `git commit`", the examples win. Remove competing examples from the execution context.

3. **Protocol awareness ≠ tool invocation** — The model can perfectly understand a protocol and implement it itself without calling the tool. Instructions must distinguish between understanding the protocol and invoking the tool.

4. **The v2 design assumption was wrong** — "Commands stay as educational reference; the block overrides execution behavior" (v2-plan.md §3.0.10). LLMs don't distinguish educational reference from execution template. This assumption must be retired.

5. **Primacy matters** — Place the most critical constraints first in every instruction file. Don't bury them after routing tables and guidelines.
