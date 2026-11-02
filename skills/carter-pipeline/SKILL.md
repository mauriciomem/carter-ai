---
name: carter-pipeline
description: Git commands, GitHub CLI, branching strategies, and GitHub Actions CI/CD pipelines. Use for any git operation, gh CLI usage, workflow design, branching advice, or pipeline creation.
---

<objective>
Execute git and GitHub operations following best practices. Design branching strategies and CI/CD pipelines with GitHub Actions.

**Language & attribution:** commit messages, branch names, tags and PR text are always English. The user is the commit author and committer; never pass `--author`, `-S`, `-s` or `--no-verify`. Credit comes from the `coauthor_trailer` that `carter ops config --emit` prints (see `carter-ops`).
</objective>

<routing>

## Specialized References

This file covers core Git command best practices. For specialized topics, use `read_file` to load the appropriate reference from the **same directory** as this SKILL.md before proceeding.

| File | Load when the request involves |
|------|-------------------------------|
| `github-cli.md` | `gh` CLI, pull requests, issues, releases, Actions run inspection, `gh api`, GitHub search |
| `strategies.md` | branching strategies, GitHub Flow, Git Flow, trunk-based, branch naming, commit messages, merge conflicts |
| `actions.md` | GitHub Actions workflows, CI/CD pipelines, workflow YAML, jobs, caching, secrets, deployment |

**How to load:** derive the directory path from this SKILL.md's location and read the sibling file. For example, if this file is at `~/.config/opencode/skills/carter-pipeline/SKILL.md`, read `~/.config/opencode/skills/carter-pipeline/github-cli.md`.

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

# Create branch, make changes and commit — use the carter-ops skill (`ops:` prefix):
# ops: create branch feature/PROJ-123-add-auth, commit src/auth.py with "feat: ..."
# Pushing and opening the pull request are human-only: write the handoff file
# (`carter-ops` skill) and tell the user: Run `carter push` and then `carter pr` in your own terminal, not through an agent.

# Stay current with main (read operation — run directly)
git fetch origin
git rebase origin/main        # rebase feature branch onto latest main
```

### Reviewing Changes Before Writing

Use these read commands to inspect changes before running carter-ops:

```bash
git diff                       # unstaged changes
git diff --staged              # staged changes
git status                     # working tree status
```

### Commit Message Conventions

When preparing the `--message` parameter for carter-ops:

- **Atomic commits** — each commit is one logical change that compiles and passes tests
- **Present tense** — "add feature" not "added feature"
- **Conventional format** — `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- **Reference tickets** — include ticket IDs in commit body or branch name
- **No WIP commits on shared branches** — squash before pushing to PR

### Branching

```bash
# Read operations — run directly
git branch                     # list local branches
git branch -a                  # list all branches (including remote)
git switch <name>              # switch to existing branch
git branch -d <name>           # delete merged branch
git branch -D <name>           # force-delete unmerged branch
```

- Keep branches **short-lived** — merge within days, not weeks
- Delete branches after merging
- Never commit directly to `main`

**Creating branches** — use the `carter-ops` skill (`ops:` prefix).

### Fetching and Pulling

```bash
# Fetch — download remote changes without merging
git fetch origin
git fetch --all --prune        # all remotes, clean stale branches

# Pull — fetch + integrate
git pull                       # fetch + rebase (if configured)
git pull --rebase              # explicit rebase
```

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
git diff main...HEAD --name-only  # files changed by a PR (review scope)
git grep -n "pattern"          # search tracked files only (not .venv, build output)
git check-ignore <path>        # is this path ignored? (review boundary)
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
```

Pushing a tag is a push: it is human-only (the user does it in their own terminal). An agent
creates the tag locally and says so in the handoff.

## Safety Rules

1. **Agents never push or force-push** — pushing is human-only; `carter push` has no force option, and a human who must force-push uses `--force-with-lease` on their own feature branch only
2. **Always review before committing** — use `git diff` to check changes before committing via the `carter-ops` skill
3. **Pull before the human pushes** — stay current (`git fetch`, then rebase) to avoid conflicts
4. **Don't commit secrets** — use `.gitignore` and secret managers
5. **Don't rewrite public history** — use `git revert` for published commits

</guidelines>
