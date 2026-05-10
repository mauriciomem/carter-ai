# Git Branching Strategies

Choose a branching strategy based on team size, release cadence, and project complexity.

## GitHub Flow 

- **When:** Small teams, continuous deployment, single production version
- **Branches:** `main` + short-lived feature branches
- **Flow:** branch from `main` → commit → PR → review → merge → deploy
- **Rules:** `main` is always deployable, PRs require review, CI must pass

```
main ──●──●──●──●──●──●──●──
        \       /   \     /
feature  ●──●──●     ●──●
```

## Git Flow

- **When:** Scheduled releases, multiple versions in production, larger teams
- **Branches:** `main`, `develop`, `feature/*`, `release/*`, `hotfix/*`
- **Flow:** feature → develop → release → main
- **Rules:** More ceremony, better for complex release management

```
main    ──●────────────●──────●──
           \          / \    /
release     \    ●──●    ●──
             \  /
develop  ●──●──●──●──●──●──
          \   /
feature    ●──●
```

## Trunk-Based Development

- **When:** Experienced teams, strong CI, feature flags available
- **Branches:** `main` only, very short-lived branches (< 1 day)
- **Flow:** branch → small commit → merge (multiple times per day)
- **Rules:** Requires excellent CI, feature flags, and team discipline

## Branch Naming Conventions

```
feature/<ticket-id>-short-description
bugfix/<ticket-id>-short-description
hotfix/<ticket-id>-short-description
release/v1.2.0
chore/update-dependencies
```

- Use lowercase with hyphens
- Include ticket ID when applicable
- Keep descriptions short (3-5 words)

## Commit Message Format

Follow Conventional Commits (https://www.conventionalcommits.org/):

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Types:** `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

**Examples:**

```
feat(auth): add OAuth2 login with Google
fix(api): handle timeout on /users endpoint
docs(readme): add deployment instructions
ci(actions): add Terraform plan to PR checks
refactor(db): extract connection pool to module
```

**Rules:**
- Subject line ≤ 72 characters, imperative mood, no period
- Body wraps at 72 characters, explains *why* not *what*
- Footer for breaking changes (`BREAKING CHANGE:`) and ticket references (`Refs: PROJ-123`)

## Merge Conflict Resolution

1. **Understand both sides** — read the full context of both changes before resolving
2. **Communicate** — if the conflict involves another developer's work, discuss first
3. **Test after resolving** — always run tests after conflict resolution
4. **Prefer rebase for local work** — `git rebase main` before PR to keep history clean
5. **Never force-push shared branches** — only force-push personal feature branches

```bash
# Resolving during rebase
git rebase origin/main
# ... resolve conflicts in editor ...
git add <resolved-files>
git rebase --continue

# Resolving during merge
git merge main
# ... resolve conflicts in editor ...
git add <resolved-files>
git commit

# Abort if things go wrong
git rebase --abort
git merge --abort
```

## PR Best Practices

- **Small PRs** — aim for < 400 lines changed; split large work into stacked PRs
- **Descriptive titles** — use conventional commit format for PR titles
- **Link issues** — reference tickets in PR description (`Closes #123`)
- **Self-review first** — review your own diff before requesting reviews
- **Respond to all comments** — resolve or acknowledge every review comment
