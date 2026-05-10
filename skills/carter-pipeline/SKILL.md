---
name: carter-pipeline
description: Git commands, GitHub CLI, branching strategies, and GitHub Actions CI/CD pipelines. Use for any git operation, gh CLI usage, workflow design, branching advice, or pipeline creation.
argument-hint: "[git operation, GitHub task, or pipeline to create/review]"
---

<objective>
Execute git and GitHub operations following best practices. Design branching strategies and CI/CD pipelines with GitHub Actions.
</objective>

<routing>

## Specialized References

This file covers core Git command best practices. For specialized topics, use `read_file` to load the appropriate reference from the **same directory** as this SKILL.md before proceeding.

| File | Load when the request involves |
|------|-------------------------------|
| `github-cli.md` | `gh` CLI, pull requests, issues, releases, Actions run inspection, `gh api`, GitHub search |
| `strategies.md` | branching strategies, GitHub Flow, Git Flow, trunk-based, branch naming, commit messages, merge conflicts |
| `actions.md` | GitHub Actions workflows, CI/CD pipelines, workflow YAML, jobs, caching, secrets, deployment |

**How to load:** derive the directory path from this SKILL.md's location and read the sibling file. For example, if this file is at `~/.copilot/skills/carter-pipeline/SKILL.md`, read `~/.copilot/skills/carter-pipeline/github-cli.md`.

If the request does not match any specialized topic, use the core guidelines below without loading additional files.

</routing>

<guidelines>

## Git Best Practices

### Configuration

```bash
# Identity (required)
git config --global user.name "Your Name"
git config --global user.email "you@example.com"

# Useful defaults
git config --global pull.rebase true        # rebase on pull instead of merge
git config --global fetch.prune true        # auto-remove stale remote branches
git config --global diff.colorMoved zebra   # highlight moved lines in diff
git config --global init.defaultBranch main
```

### Daily Workflow

```bash
# Start work — always pull latest first
git checkout main
git pull
git checkout -b feature/PROJ-123-add-auth

# Stage and commit
git add -p                    # stage interactively — review each hunk
git commit -m "feat(auth): add OAuth2 login flow"

# Stay current with main
git fetch origin
git rebase origin/main        # rebase feature branch onto latest main

# Push
git push -u origin feature/PROJ-123-add-auth
```

### Staging

| Command | Use when |
|---------|----------|
| `git add -p` | Reviewing changes hunk-by-hunk (preferred) |
| `git add <file>` | Adding specific files |
| `git add .` | Only when you've already reviewed with `git diff` |
| `git reset HEAD <file>` | Unstaging a file |

**Never use** `git add .` blindly — always review changes first.

### Committing

- **Atomic commits** — each commit is one logical change that compiles and passes tests
- **Present tense** — "add feature" not "added feature"
- **Reference tickets** — include ticket IDs in commit body or branch name
- **No WIP commits on shared branches** — squash before pushing to PR

```bash
# Good: atomic, descriptive
git commit -m "fix(api): handle timeout on /users endpoint"

# Interactive rebase to clean up before PR
git rebase -i origin/main    # squash fixups, reword messages
```

### Branching

```bash
git branch                     # list local branches
git branch -a                  # list all branches (including remote)
git checkout -b <name>         # create and switch to new branch
git switch <name>              # switch branches (modern syntax)
git branch -d <name>           # delete merged branch
git branch -D <name>           # force-delete unmerged branch
```

- Keep branches **short-lived** — merge within days, not weeks
- Delete branches after merging
- Never commit directly to `main`

### Fetching, Pulling, and Pushing

```bash
# Fetch — download remote changes without merging
git fetch origin
git fetch --all --prune        # all remotes, clean stale branches

# Pull — fetch + integrate
git pull                       # fetch + rebase (if configured)
git pull --rebase              # explicit rebase

# Push
git push -u origin <branch>   # first push, set upstream
git push                      # subsequent pushes
git push --force-with-lease   # safe force-push (rejects if remote has new commits)
```

**Never use** `git push --force` — use `--force-with-lease` instead.

### Merging and Rebasing

```bash
# Merge — creates merge commit (good for PRs)
git merge <branch>

# Rebase — replay commits on top of target (good for local cleanup)
git rebase main
git rebase -i HEAD~3           # interactive rebase last 3 commits

# Abort if things go wrong
git merge --abort
git rebase --abort
```

**When to rebase:** local feature branches before opening a PR.
**When to merge:** incorporating PRs into main (via GitHub merge button).
**Never rebase:** shared/public branches that others are working on.

### Undoing Changes

```bash
# Discard working directory changes
git checkout -- <file>         # specific file
git restore <file>             # modern syntax

# Unstage
git reset HEAD <file>
git restore --staged <file>    # modern syntax

# Undo last commit (keep changes staged)
git reset --soft HEAD~1

# Undo last commit (keep changes unstaged)
git reset HEAD~1

# Revert a pushed commit (safe — creates new commit)
git revert <sha>
```

**Prefer `git revert`** over `git reset` for commits already pushed to remote.

### Inspecting History

```bash
git log --oneline --graph -20  # compact log with branch graph
git log --author="name"        # filter by author
git log -- <file>              # history of specific file
git diff                       # unstaged changes
git diff --staged              # staged changes
git diff main..feature         # diff between branches
git blame <file>               # line-by-line authorship
git show <sha>                 # inspect a specific commit
```

### Stashing

```bash
git stash                      # save working changes
git stash pop                  # restore and remove from stash
git stash list                 # list stashes
git stash drop                 # discard top stash
git stash apply stash@{2}     # apply specific stash without removing
```

### Tags

```bash
git tag v1.0.0                         # lightweight tag
git tag -a v1.0.0 -m "Release 1.0.0"  # annotated tag (preferred)
git push origin v1.0.0                 # push specific tag
git push origin --tags                 # push all tags
```

## Safety Rules

1. **Never force-push shared branches** — only force-push personal feature branches with `--force-with-lease`
2. **Always review before staging** — `git diff` or `git add -p`
3. **Pull before push** — stay current to avoid conflicts
4. **Don't commit secrets** — use `.gitignore` and secret managers
5. **Don't rewrite public history** — use `git revert` for published commits

</guidelines>

<deterministic-operations>
## Write Operations — Use carter-ops

All state-changing git operations MUST go through `carter-ops` via the terminal.

**Protocol:**
1. Prepare the parameters using the domain knowledge in this skill
2. Run `carter-ops <operation> [params] --dry-run` to generate the plan
3. Present the plan to the user for approval
4. On approval, run `carter-ops <operation> [params] --execute`
5. Report the structured result to the user

**Available operations:**
| Operation | When to use |
|-----------|-------------|
| `git-branch` | Creating a new branch (`--name`, `--from`) |
| `git-commit` | Committing staged files (`--message`, `--files`) |
| `git-push` | Pushing to remote (`--branch`) |
| `git-flow` | Branch + commit + push in one flow (`--branch`, `--message`, `--files`, `--from`) |

Do NOT run `git add`, `git commit`, `git push`, or `git checkout -b` directly.
Read operations (`git log`, `git status`, `git diff`, `git blame`) remain direct.
</deterministic-operations>
