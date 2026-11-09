# GitHub CLI (`gh`)

Use `gh` for GitHub operations instead of the web UI. Prefer structured output with `--json` and `--jq` for reliable parsing.

> **Agents read, and handle pull requests.** An agent may open (`gh pr create`), edit
> (`gh pr edit`) and comment on (`gh pr comment`) a PR once the branch is pushed. Merging,
> closing, reviewing, marking ready, issues, releases and `gh api` are human-only: the
> commands marked *human-only* below are for the person at the keyboard. An agent that
> finishes a branch tells the user to run `carter push` in their own terminal, then opens
> the PR.
> `gh repo view` and `gh search repos` take the repository or query positionally (no `-R`);
> the other read verbs take `-R OWNER/REPO` after the subcommand.

## Prerequisites

```bash
command -v gh       # verify installed
gh auth status      # verify authenticated
```

If missing or unauthenticated: https://cli.github.com/

## Pull Requests

```bash
# Inspect
gh pr view 123
gh pr view 123 --json number,title,state,author,files,reviews
gh pr list
gh pr list --state merged
gh pr status                   # PRs relevant to you
gh pr checks 123               # CI status
gh pr diff 123

# Create, edit, comment (agents may, once the branch is pushed)
gh pr create --fill            # from commit messages
gh pr create --title "Fix login redirect" --body "## Summary\n- Fix redirect loop" --head fix/login
gh pr edit 123 --add-label bug
gh pr comment 123 -b "CI is green now."

# Actions (checkout is a local read; the rest is human-only)
gh pr checkout 123             # fetch and switch to PR branch
gh pr review 123 --approve
gh pr review 123 --comment -b "One small question on the error handling."
gh pr ready 123                # mark ready for review
gh pr merge 123
gh pr close 123
```

### Summarize a PR

```bash
gh pr view 123 --json number,title,state,author,reviewDecision,files
gh pr checks 123
```

### Check why CI failed

```bash
gh run list --workflow ci.yml
gh run view 789 --log          # read logs for failing jobs
```

## Issues

```bash
# Inspect
gh issue view 456
gh issue view 456 --json number,title,state,labels,assignees
gh issue list
gh issue list --label bug
gh issue status

# Create and update (human-only)
gh issue create --title "Add retry logic" --body "Retry transient failures."
gh issue edit 456
gh issue comment 456 -b "I can take this."
gh issue close 456
gh issue reopen 456
```

## Repositories

```bash
gh repo view OWNER/REPO
gh repo view --web
gh repo list OWNER
gh repo clone OWNER/REPO
gh repo create                 # human-only
gh repo fork OWNER/REPO        # human-only
```

## Actions and Workflows

```bash
gh run list
gh run list --workflow ci.yml
gh run view 789
gh run view 789 --log
gh run watch 789               # live output
gh run rerun 789              # human-only
gh run cancel 789             # human-only
gh run download 789            # download artifacts

gh workflow list
gh workflow view ci.yml
gh workflow run ci.yml         # manual dispatch (human-only)
gh workflow enable ci.yml      # human-only
gh workflow disable ci.yml     # human-only
```

## Releases

Creating or deleting a release is human-only. Reads (`list`, `view`, `download`) are fine.

```bash
gh release list
gh release view v1.2.3
gh release create v1.2.3
gh release create v1.2.3 --generate-notes    # auto-generate changelog
gh release delete v1.2.3
gh release download v1.2.3
```

## Search

```bash
gh search repos QUERY
gh search issues QUERY
gh search prs QUERY
```

## API Access

`gh api` is denied for agents (it can write); it is for the person at the keyboard.

Use `gh api` when no first-class subcommand exists:

```bash
gh api /user
gh api repos/OWNER/REPO/pulls/123/comments
gh api graphql -f query='query { viewer { login } }'
```

## Structured Output

Prefer `--json` with `--jq` for precise, machine-readable results:

```bash
gh pr view 123 --json title,state,author
gh pr list --json number,title --jq '.[] | select(.title | contains("bug"))'
gh issue list --json number,title,labels --template '{{range .}}{{.number}}: {{.title}}{{"\n"}}{{end}}'
```

## Safety Checklist

1. Confirm auth: `gh auth status`
2. Confirm target repo (use `-R OWNER/REPO` when ambiguous)
3. **Read before write** — inspect the object before editing or deleting
4. Confirm checks and review state before merging PRs
5. For destructive actions, verify the target first
