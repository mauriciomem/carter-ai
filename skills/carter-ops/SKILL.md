---
name: carter-ops
description: "Deterministic executor for operational tasks. Triggered by the `ops:` keyword prefix."
---

<objective>
Execute write operations (git, GitHub, Jira) with tier-based attribution, approval gate,
and post-hoc audit logging. Run commands directly in the terminal — no intermediary CLI tool.
</objective>

<routing>

## Who runs which step

- **Local steps** — `git status`, `git add`, `git commit`, branch creation, `git log`,
  `carter ops audit` — run directly in whichever agent received `ops:`.
- **Remote steps** — `git push`, PR/issue create/merge/comment/edit, releases,
  Jira writes — are performed **only by carter-devops**, the sole `remote-write`
  holder. The harness denies these commands to every other agent.
- **Outward text** (PR/issue bodies, review comments, release notes, Jira comments)
  goes through **carter-narrator**'s redaction pass before devops transmits it.

### If you are not carter-devops

Do the local steps, then stop and return a handoff to the maestro — do not attempt
the remote commands. The handoff contains:

- what to push / open / post (operation and exact commands),
- the branch name and commit SHA(s),
- any drafted outward text (PR/issue body, Jira comment) for the narrator pass.

</routing>

<config>

## Attribution: read it at runtime

Before any commit or outward text, run `carter ops config --emit` and use what it prints.
Never use remembered, typed or example values. The JSON has these keys:

| Key | What to do with it |
|-----|--------------------|
| `tier` | `t0` (nothing configured), `t1` (LLM account, no key) or `t2` (account and key) |
| `role`, `role_source` | Who the commit is attributed to, and where that setting came from |
| `coauthor_trailer` | The exact trailer line for every commit message you make |
| `commits` | `allowed` or `refused` |
| `refusal_reason` | The error code when `commits` is `refused` (see the error table below) |
| `footer` | Text appended to GitHub and Jira bodies |

When `commits` is `refused`, stop. Make no commit. Report the `refusal_reason` code and its
message from the error table to the user. Do not edit the config, retry with other flags, or
work around it.

**Interim shape (until signing arrives in slice 2b):** your commits are made with the user's
own git config, so the user is both author and committer, and they are unsigned. Credit
goes only through the trailer. Never pass `--author`, `--no-verify`, `-s` or `-S`, and never add
a `Signed-off-by` unless the user asks for it on that commit.

</config>

<guardrails>

## Forbidden commands and error codes

These two blocks are generated from Carter's data files; do not edit them by hand.

<!-- forbidden:begin -->
Never run any of these (generated from `g2_rules.json`):

- **Commit-creating verbs:** `--no-verify`, `-n`, `--no-gpg-sign`, `-S`, `--gpg-sign`, `-S<arg>`, `--gpg-sign=<arg>`, `-s`, `--signoff`, `--reset-author`, `--author`. `-n` is forbidden for `commit` only (it means `--no-verify` there; `merge -n` is `--no-stat`). Bare `-S` is not used before signing arrives (slice 2b).
- **Staging:** `git add -A`, `git add .`, `git commit -a`.
- **Env prefixes, assignments and unsets:** `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `GIT_CONFIG*`, `GIT_SSH*`, `GIT_ASKPASS`, `GIT_EXEC_PATH`, `GIT_DIR`, `HOME`, `XDG_CONFIG_HOME`, `CARTER_*`, `AGENT`, `OPENCODE*`. Forbidden as a `VAR=` prefix, with `env`/`env -u`, `unset` and `export`.
- **git config:** `git config --global`, `git config --system`, `git config --file`, `git config --worktree`, `git config <key> <value>`. Any write at any scope is forbidden; only `--get*`, `--list` and `--show-*` pass.
- **-c and --config-env=:** `hook.*`, `core.hooksPath`, `core.sshCommand`, `core.askPass`, `core.fsmonitor`, `commit.gpgsign`, `user.*`, `gpg.*`, `alias.*`, `include*`, `credential.*`, `url.*`, `remote.*`, `http.*`, `protocol.*`, `carter.*`.
- **Plumbing:** `commit-tree`, `fast-import`, `filter-branch`, `filter-repo`, `replace`, `update-ref`. `update-ref` is forbidden with a raw SHA.
<!-- forbidden:end -->

<!-- errors:begin -->
| Code | Where | Message | What to do |
|---|---|---|---|
| `E-COMMIT-T1` | `carter commit`, T1 | No LLM signing key (T1): committed unsigned with `Co-authored-by: LLM`. | — |
| `E-CONFIG` | any identity command | config.toml is invalid; agent commits are disabled until fixed. | Never falls back to defaults. |
| `E-ROLE-B-TIER` | role b without T2 | Role `author` needs a signing key; refusing (no downgrade). | — |
| `E-TIER-REQUIRED` | plugin (agent commit blocked) / `carter commit`, below the pinned `require_tier` | This workspace requires tier `<t>`; configure the LLM identity. | — |
<!-- errors:end -->

</guardrails>

<workflow>

## Required Workflow

1. **ASSESS** — Run read commands to understand current state (`git status`, `git diff`, `git log --oneline -5`, etc.)
2. **PLAN** — Run `carter ops config --emit`, then show the user a structured plan with the exact commands you will run, including the `coauthor_trailer`
3. **APPROVE** — Wait for user confirmation before executing any write command
4. **EXECUTE** — Run commands in terminal (the `coauthor_trailer` on every commit)
5. **AUDIT** — Run: `carter ops audit --operation <name> --params '<json>' --result <success|failure> --identifiers '<json>'`
6. **REPORT** — Tell the user what happened (branch name, commit SHA, PR URL, etc.)

**NEVER execute write commands without showing the plan and getting approval first.**

</workflow>

<git-operations>

## Git Operations

### Create branch

```bash
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
```

### Stage and commit

```bash
git add <file1> <file2> ...
git commit -m "<subject>" -m "<body>" --trailer "<coauthor_trailer>"
git log -1 --format='%an|%cn|%G?'
```

Replace `<coauthor_trailer>` with the value from `carter ops config --emit`. Stage named
files only. Verify the commit with the last command: `%an` and `%cn` must both equal
`git config user.name`, and `%G?` must be `N` (unsigned). If not, stop and report; never fix
it with `--author`, `--reset-author` or a signing flag.

Commit messages, branch names and PR text are always in English, whatever language the user
chats in. If `--trailer` is unavailable (git < 2.32), put the `coauthor_trailer` line as the
last paragraph of the message.

### Push (carter-devops only)

```bash
git push -u origin <branch-name>
```

### Complete flow (branch + commit + push — push by carter-devops only)

```bash
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
git add <file1> <file2> ...
git commit -m "<subject>" -m "<body>" --trailer "<coauthor_trailer>"
git push -u origin <branch-name>
```

### Commit message conventions

- Conventional format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Present tense: "add feature" not "added feature"
- Reference issues: `Closes #70` or ticket ID in body

</git-operations>

<github-operations>

## GitHub Operations (via gh CLI — carter-devops only)

Append the `footer` from `carter ops config --emit` to ALL `--body` values, after a
`---` separator.

When the body is a code review, write it in the `carter-code-review` register
(default Standard) — conversational, scoped to the diff, no full severity table
unless a deep review was requested. For non-review PR/issue bodies, use the
**Brief register** (defined in `carter-docs`): lead with the ask, concise, scoped.

### Commands

```bash
# Create issue
gh issue create --repo <owner/repo> --title "<title>" --body "<body>" [--label "<labels>"]

# Comment on issue
gh issue comment <number> --repo <owner/repo> --body "<body>"

# Create PR
gh pr create --repo <owner/repo> --title "<title>" --head <branch> --base <base> --body "<body>" [--draft]

# Comment on PR
gh pr comment <number> --repo <owner/repo> --body "<body>"
```

</github-operations>

<jira-operations>

## Jira Operations (via carter-atlassian MCP)

All Jira reads and writes go through the `carter-atlassian` MCP server (remote,
OAuth — no API tokens). Load the `carter-atlassian` skill for ticket conventions.
Jira writes are remote steps: carter-devops performs them, after the narrator's
redaction pass on the body.

Append the `footer` from `carter ops config --emit` to ALL body text.

</jira-operations>

<error-recovery>

## Error Recovery

| Error | Recovery |
|-------|----------|
| Push rejected (non-fast-forward) | `git pull origin <branch> --rebase` then retry push |
| Branch already exists | Ask user: switch to existing branch or pick a new name? |
| A commit fails or `commits` is `refused` | Stop. Report `refusal_reason` (see the error table); do not retry with other flags |
| Jira auth error | Re-authenticate the `carter-atlassian` MCP server (OAuth) in your client |
| `gh` not found | Suggest installing the GitHub CLI (`gh`) |
| Remote command denied | You are not carter-devops — return the handoff (see Routing) |
| `coauthor_trailer` missing or wrong | Re-run `carter ops config --emit` and use its value |

</error-recovery>

<boundaries>

## What is NOT ops:

Read operations run directly without the `ops:` prefix — no approval needed:

`git log`, `git status`, `git diff`, `git blame`, `git branch --list`,
`gh issue list`, `gh pr list`, `gh pr view`, JQL queries via MCP.

</boundaries>

<plan-format>

## Plan Display Format

When showing the plan to the user, use this structure:

```
**Operation:** <type> (e.g., git-flow, gh-issue, jira-comment)
**Branch:** <name> (if applicable)
**Files:** <list> (if applicable)
**Message:** <commit message or body text>
**Attribution:** authored by you (your git config), unsigned; trailer: `<coauthor_trailer>`

Commands:
1. <exact command 1>
2. <exact command 2>
3. ...

Approve?
```

</plan-format>
