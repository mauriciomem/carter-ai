---
name: carter-git-strategy
description: Advise on Git branching strategies and resolve merge conflicts
argument-hint: "[question about git workflow or conflict to resolve]"
---

<objective>
Advise on Git branching strategies, workflow design, and conflict resolution based on team size, release cadence, and project complexity.
</objective>

<strategies>

## Branching Strategies

### GitHub Flow (Recommended for most projects)
- **When:** Small teams, continuous deployment, single production version
- **Branches:** `main` + short-lived feature branches
- **Flow:** branch from `main` → commit → PR → review → merge → deploy
- **Rules:** `main` is always deployable, PRs require review, CI must pass

### Git Flow
- **When:** Scheduled releases, multiple versions in production, larger teams
- **Branches:** `main`, `develop`, `feature/*`, `release/*`, `hotfix/*`
- **Flow:** feature → develop → release → main
- **Rules:** More ceremony, better for complex release management

### Trunk-Based Development
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

## Commit Message Format
```
<type>(<scope>): <subject>

<body>

<footer>
```
Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

Reference: Conventional Commits (https://www.conventionalcommits.org/)

</strategies>

<conflict-resolution>

## Merge Conflict Resolution

1. **Understand both sides** — Read the full context of both changes before resolving.
2. **Communicate** — If the conflict involves another developer's work, discuss before resolving.
3. **Test after resolving** — Always run tests after conflict resolution.
4. **Prefer rebase for local work** — `git rebase main` before PR to keep history clean.
5. **Never force-push shared branches** — Only force-push personal feature branches.

</conflict-resolution>
