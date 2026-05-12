---
name: carter-ops
description: "Deterministic executor for operational tasks. Triggered by the `ops:` keyword prefix. Runs carter-ops CLI with dry-run → approve → execute workflow."
argument-hint: "[operation and parameters, e.g. git-flow --branch feature/x --message 'feat: ...' --files main.tf]"
---

<objective>
Run the `carter-ops` CLI in the terminal for deterministic operational tasks. Every operation follows: dry-run → user approval → execute.
</objective>

<workflow>

## Required Workflow

1. Run `carter-ops <operation> [params] --dry-run` **in the terminal** — capture the JSON output
2. Show the **actual terminal output** to the user — do NOT fabricate or reformat it
3. Ask the user to approve the plan
4. On approval, run `carter-ops <operation> [params] --execute` **in the terminal**
5. Report the **actual terminal output** to the user

</workflow>

<commands>

## Command Reference

| Operation | Params | Purpose |
|-----------|--------|---------|
| `git-branch` | `--name`, `--from` (default: main) | Create a branch |
| `git-commit` | `--message`, `--files` | Stage and commit |
| `git-push` | `--branch` | Push to remote |
| `git-flow` | `--branch`, `--message`, `--files`, `--from` | Branch + commit + push |
| `jira-comment` | `--ticket`, `--body` | Comment on a ticket |
| `jira-create` | `--project`, `--type`, `--summary`, `--description`, `--priority`, `--labels` | Create a ticket |
| `jira-update` | `--ticket`, `--comment`, `--transition` | Comment + transition |

Run `carter-ops --list` to discover all available operations.

</commands>

<boundaries>

## What is NOT carter-ops

Read operations are run directly — no carter-ops needed:

`git log`, `git status`, `git diff`, `git blame`, `git branch --list`, JQL queries, viewing Jira tickets.

</boundaries>

<rules>

## Rules

- The dry-run plan MUST be **actual terminal output** from running `carter-ops`. Never fabricate JSON.
- Never run raw `git add`, `git commit`, `git push`, `git checkout -b`, or Jira API calls when `ops:` is active.
- Never skip the `--dry-run` phase.
- If unsure which operation to use, run `carter-ops --list` first.

</rules>
