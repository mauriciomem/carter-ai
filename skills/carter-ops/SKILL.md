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
- **Pushing and every other GitHub write** — `git push`, PR/issue create/merge/comment/edit,
  releases, `gh api` — are **human-only**. No agent runs them, carter-devops included, and the
  harness denies them to all of them. You finish the local work and write a **handoff file**
  (see "Push and PR"); the human pushes and opens the PR from their own terminal.
- **Jira and Slack writes** are remote steps performed **only by carter-devops** (they ask first).
- **Outward text** (PR bodies, review comments, release notes, Jira comments) goes through
  **carter-narrator**'s redaction pass before it is written into a handoff or posted.

### If you are not carter-devops

Do the local steps, then stop and return a handoff to the maestro. For a Jira or Slack write
the handoff names the operation and the exact text for the narrator pass. A push or PR is not
yours to hand to carter-devops either: use the handoff file below.

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

**Interim shape of the guards:** the policies that deny `git push` and GitHub writes are
literal command matches; the plugin and shell isolation that would make them a boundary are not
installed yet (`carter guard status` says so). Do not test them, and do not look for another
way to push: there is none to use, and trying is a violation, not a workaround.

</config>

<guardrails>

## Forbidden commands and error codes

These two blocks are generated from Carter's data files; do not edit them by hand.

<!-- forbidden:begin -->
Never run any of these (generated from `g2_rules.json`):

- **Commit-creating verbs:** `--no-verify`, `-n`, `--no-gpg-sign`, `-S`, `--gpg-sign`, `-S<arg>`, `--gpg-sign=<arg>`, `-s`, `--signoff`, `--reset-author`, `--author`. `-n` is forbidden for `commit` only (it means `--no-verify` there; `merge -n` is `--no-stat`). Bare `-S` is not used before signing arrives (slice 2b).
- **Staging:** `git add -A`, `git add .`, `git commit -a`.
- **Push verbs:** `git push`, `git send-pack`.
- **Env prefixes, assignments and unsets:** `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `GIT_CONFIG*`, `GIT_SSH*`, `GIT_ASKPASS`, `GIT_EXEC_PATH`, `GIT_DIR`, `HOME`, `XDG_CONFIG_HOME`, `CARTER_*`, `AGENT`, `OPENCODE*`. Forbidden as a `VAR=` prefix, with `env`/`env -u`, `unset` and `export`.
- **git config:** `git config --global`, `git config --system`, `git config --file`, `git config --worktree`, `git config <key> <value>`. Any write at any scope is forbidden; only `--get*`, `--list` and `--show-*` pass.
- **-c and --config-env=:** `hook.*`, `core.hooksPath`, `core.sshCommand`, `core.askPass`, `core.fsmonitor`, `commit.gpgsign`, `user.*`, `gpg.*`, `alias.*`, `include*`, `credential.*`, `url.*`, `remote.*`, `http.*`, `protocol.*`, `carter.*`.
- **Plumbing:** `commit-tree`, `fast-import`, `filter-branch`, `filter-repo`, `replace`, `update-ref`. `update-ref` is forbidden with a raw SHA.
- **Human-only Carter verbs:** `carter push`, `carter pr`, `carter identity add/remove/unlock/lock`, `carter guard *`, `carter github-token set`, `carter broker *`.
<!-- forbidden:end -->

<!-- errors:begin -->
| Code | Where | Message | What to do |
|---|---|---|---|
| `E-COMMIT-T1` | `carter commit`, T1 | No LLM signing key (T1): committed unsigned with `Co-authored-by: LLM`. | — |
| `E-POLICY` | OpenCode policy | permission.rejected: Blocked by configuration policy | Same; for gh, use an allowlisted read verb with `-R` after the subcommand. |
| `E-GH-READONLY` | gh write with read-only PAT | 401/403 at GitHub (exact text unverified) | Writes are human-only. |
| `E-PAT-TYPE` | `github-token set` / plugin / check | Only fine-grained `github_pat_` tokens are accepted (this looks like `<4-char prefix>`). | — |
| `E-PAT-PERM` | `github-token set` / plugin / check | Token file must be 0600, yours, not a symlink, outside any repo. | — |
| `E-B-REPOCFG` | B, A+ | Config, hooks or SSH config at scope `<scope>` (`<key>`) could run code with your credentials; use `carter push` and review. | — |
| `E-B-UNSIGNED` | B, A+ | Commits `<shas>` have the LLM as committer but no valid LLM signature; refused. | — |
| `E-SECRET-SCAN` | `carter pr`, `carter_pr` | PR text matches a secret pattern (`<rule>`); refused. | — |
| `E-HANDOFF` | `carter pr` | No valid handoff at `.carter/state/handoff/<branch>.md`, or `head_sha` is not an ancestor of HEAD. | — |
| `E-CONFIG` | any identity command | config.toml is invalid; agent commits are disabled until fixed. | Never falls back to defaults. |
| `E-ROLE-B-TIER` | role b without T2 | Role `author` needs a signing key; refusing (no downgrade). | — |
| `E-TIER-REQUIRED` | plugin (agent commit blocked) / `carter commit`, below the pinned `require_tier` | This workspace requires tier `<t>`; configure the LLM identity. | — |
| `E-POLICIES-MISSING` | `carter check --host`, `carter guard install` (verify and rollback) | Policy `<statement>` not loaded — a broken OpenCode config drops all of them and your providers. | — |
| `E-APLUS-ARGS` | `carter push` (added beyond Appendix B, plan 003 step 6 F10) | `carter push` pushes only the current branch to `origin`: no detached HEAD, no other remote. | Check out the branch you want to push; there are no flags for force, tags or other remotes. |
| `E-HUMAN-TERMINAL` | `carter guard install\|remove`, `github-token set\|check`, `push`, `pr` (added beyond Appendix B, plan 003 step 6 F10) | This command runs only in your own terminal: this shell looks like an agent's, or it has no TTY. If you are not an agent, this shell inherited agent variables; restart the app from a clean terminal. | Open a terminal that OpenCode did not start and run the command there. |
| `E-STATE-INVALID` | `carter guard *` (added beyond Appendix B, plan 003 step 6 F10) | ~/.carter/guard-state.json is unreadable or from a newer Carter; nothing was changed. | Run `carter guard status` to see the problem; fix or move the file yourself. Carter never rebuilds it. |
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

### Finish the branch locally

```bash
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
git add <file1> <file2> ...
git commit -m "<subject>" -m "<body>" --trailer "<coauthor_trailer>"
git log -1 --format='%an|%cn|%G?'
```

Then stop at the commit: pushing is the human's step (next section).

### Commit message conventions

- Conventional format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Present tense: "add feature" not "added feature"
- Reference issues: `Closes #70` or ticket ID in body

</git-operations>

<push-and-pr>

## Push and PR (the human does it)

You never push and never open or edit anything on GitHub. When a branch is ready, write the
handoff file `.carter/state/handoff/<encoded-branch>.md` with your file tools, where
`<encoded-branch>` is the branch name with `%` written as `%25` and `/` as `%2F`
(`feat/x` → `feat%2Fx.md`). Front matter has exactly these keys, nothing else; quote the
`title` (it often contains a colon):

```markdown
---
title: "feat: one line, Conventional Commits style"
base: main
draft: false
head_sha: <40 lowercase hex characters: git rev-parse HEAD>
repo: <owner/name>
---

PR description in Markdown. Append the `footer` from `carter ops config --emit` after a `---`.
```

Write the description in the `carter-code-review` register when it is a code review (default
Standard); otherwise use the **Brief register** (defined in `carter-docs`): lead with the ask,
concise, scoped.

The file is untrusted input to the human's `carter pr`: it reads only these keys, scans the
title, branch and body for secrets, shows everything and asks. Put no tokens, keys, internal
URLs or credentials paths in it (the narrator's redaction pass comes first).

Then tell the user, in these words:

Run `carter push` and then `carter pr` in your own terminal, not through an agent.

Rules: never prefix the commands with `!` and never ask the user to paste them into the TUI;
never pass `--force` or any flag to a push; never write the handoff for a branch you did not
finish or whose commits you did not verify with `git log -1 --format='%an|%cn|%G?'`. For an
issue, a PR comment, a review or a release there is no agent path in this version: give the
user the drafted text (with the footer) to post themselves.

</push-and-pr>

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
| Local branch is behind its remote | `git pull origin <branch> --rebase`, then update the handoff `head_sha`; the human pushes |
| Branch already exists | Ask user: switch to existing branch or pick a new name? |
| A commit fails or `commits` is `refused` | Stop. Report `refusal_reason` (see the error table); do not retry with other flags |
| Jira auth error | Re-authenticate the `carter-atlassian` MCP server (OAuth) in your client |
| `gh` not found | Reads only: suggest installing the GitHub CLI (`gh`) |
| A push or `gh` write is denied (`E-POLICY`, "Blocked by configuration policy") | Expected: write the handoff file; never retry another way |
| `coauthor_trailer` missing or wrong | Re-run `carter ops config --emit` and use its value |

</error-recovery>

<boundaries>

## What is NOT ops:

Read operations run directly without the `ops:` prefix — no approval needed:

`git log`, `git status`, `git diff`, `git blame`, `git branch --list`,
`gh issue list`, `gh pr list`, `gh pr view`, `gh pr diff`, `gh pr checks`, JQL queries via MCP.

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
