# Getting Started

This walkthrough covers two real-world scenarios using Carter through the **Copilot CLI**. The same flows work in VS Code (`@carter-maestro`) and OpenCode.

## Prerequisites

- Carter installed (`uv run install.py` — see [README](../README.md))
- `carter-ops` on your PATH (`carter-ops --list` should output JSON)
- Environment variables set (GitHub token, optionally Jira credentials)
- Copilot CLI installed (`copilot --version`)

## Example 1: Non-Operational Task — Design an API

Non-operational tasks involve thinking, analyzing, and producing artifacts — no external state is modified. Maestro routes these to the right specialist agent.

### Start the conversation

```bash
copilot --agent carter-maestro -i \
  "I need to design a REST API for a task management app. \
   It should support users, projects, and tasks with role-based access."
```

### What happens

1. **Maestro receives the request** and recognizes it as a system design task
2. **Maestro routes to `carter-architect`**, which has the `design-review` and `diagram` skills
3. **Architect produces the deliverable** — in this case, an API design with resource models, endpoint table, and an architecture diagram

### Example conversation

```
You: I need to design a REST API for a task management app. It should support
     users, projects, and tasks with role-based access.

Carter (Maestro → Architect):

I'll design this API for you. Here's the resource model and endpoint structure.

## Resource Model

| Resource | Key Fields | Relationships |
|----------|-----------|---------------|
| User     | id, email, name, role | has many Projects (as member) |
| Project  | id, name, owner_id | has many Tasks, has many Members |
| Task     | id, title, status, assignee_id | belongs to Project |

## Core Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST   | /api/v1/auth/login | Public | Authenticate, return JWT |
| GET    | /api/v1/projects | User | List projects for current user |
| POST   | /api/v1/projects | Admin | Create project |
| GET    | /api/v1/projects/:id/tasks | Member | List tasks in project |
| POST   | /api/v1/projects/:id/tasks | Member | Create task |
| PATCH  | /api/v1/tasks/:id | Assignee/Admin | Update task status |

## Role-Based Access

- **Admin**: Full access to all resources
- **Member**: Read/write within assigned projects
- **Viewer**: Read-only access to assigned projects

Roles are enforced via middleware that checks JWT claims against project
membership. I'd recommend storing roles per-project (not globally) to support
users who are admins on one project but viewers on another.

Want me to generate an architecture diagram or dive deeper into any endpoint?
```

### Key takeaway

No commands were run. No files were modified. Maestro identified this as a design question, routed to Architect, and the specialist used its domain knowledge to produce the answer. This is the read-only path — MCP servers and skills provide context, the agent provides expertise.

---

## Example 2: Operational Task — Commit and Push Code

Operational tasks modify external state — git commits, branch creation, Jira updates. These go through **carter-ops** with a mandatory dry-run approval step.

### Start the conversation

```bash
copilot --agent carter-maestro -i \
  "I've finished the auth module in src/auth.py. Create a feature branch, \
   commit this file, and push it. Use PROJ-42 as the ticket reference."
```

### What happens

1. **Maestro receives the request** and recognizes it as a git write operation
2. **Maestro runs `carter-ops git-flow ... --dry-run` in the terminal** — the plan MUST come from actual carter-ops output, never fabricated
3. **You see the JSON plan** (actual terminal output) and approve or reject
4. **Maestro runs `carter-ops git-flow ... --execute` in the terminal** and reports the result

The same flow works across all surfaces — VS Code, Copilot CLI, and OpenCode. The agent never runs raw `git commit`, `git push`, or `git checkout -b` directly.

### Example conversation

```
You: I've finished the auth module in src/auth.py. Create a feature branch,
     commit this file, and push it. Use PROJ-42 as the ticket reference.

Carter (Maestro → DevOps):

I'll use git-flow to create the branch, commit, and push in one operation.
Let me generate the plan first.

> Running: carter-ops git-flow \
>   --branch feature/PROJ-42-auth-module \
>   --message "feat(auth): add authentication module" \
>   --files src/auth.py \
>   --from main \
>   --dry-run
```

Carter-ops returns the plan as JSON:

```json
{
  "phase": "dry-run",
  "operation": "git-flow",
  "steps": [
    "git checkout main",
    "git pull origin main",
    "git checkout -b feature/PROJ-42-auth-module",
    "git add src/auth.py",
    "git commit --author='carter-bot <carter-bot@users.noreply.github.com>' -S -m 'feat(auth): add authentication module'",
    "git push origin feature/PROJ-42-auth-module"
  ],
  "attribution": "Author: carter-bot, Signed-by: user (~/.ssh/id_ed25519)",
  "side_effects": [
    "New branch 'feature/PROJ-42-auth-module' from 'main'",
    "1 new commit as carter-bot",
    "Branch pushed to origin"
  ]
}
```

```
Carter: Here's the plan:

- Create branch `feature/PROJ-42-auth-module` from `main`
- Commit `src/auth.py` as carter-bot (signed with your SSH key)
- Push to origin

Shall I proceed?

You: yes

Carter:

> Running: carter-ops git-flow \
>   --branch feature/PROJ-42-auth-module \
>   --message "feat(auth): add authentication module" \
>   --files src/auth.py \
>   --from main \
>   --execute
```

Carter-ops executes and returns:

```json
{
  "phase": "execute",
  "operation": "git-flow",
  "success": true,
  "result": {
    "branch": "feature/PROJ-42-auth-module",
    "from": "main",
    "commit_sha": "a7f3c2d",
    "pushed": true
  },
  "attribution": "Author: carter-bot, Signed-by: user (~/.ssh/id_ed25519)"
}
```

```
Carter: Done. Branch `feature/PROJ-42-auth-module` created, committed as
        carter-bot (a7f3c2d), and pushed to origin.

        Would you like me to add a comment on PROJ-42 with the progress update?

You: yes, mention the branch name and that auth is ready for review

Carter:

> Running: carter-ops jira-comment \
>   --ticket PROJ-42 \
>   --body "Auth module implementation complete. Branch: feature/PROJ-42-auth-module — ready for review." \
>   --dry-run
```

```json
{
  "phase": "dry-run",
  "operation": "jira-comment",
  "steps": [
    "POST /rest/api/3/issue/PROJ-42/comment",
    "Body: Auth module implementation complete. Branch: feature/PROJ-42-auth-module — ready for review.\n\n_This comment was generated by carter-bot._"
  ],
  "attribution": "Footer: _This comment was generated by carter-bot._",
  "side_effects": ["New comment on PROJ-42"]
}
```

```
Carter: I'll post this comment on PROJ-42:

  "Auth module implementation complete. Branch:
   feature/PROJ-42-auth-module — ready for review."

  (with the carter-bot footer)

  Proceed?

You: go ahead

Carter:

> Running: carter-ops jira-comment \
>   --ticket PROJ-42 \
>   --body "Auth module implementation complete. Branch: feature/PROJ-42-auth-module — ready for review." \
>   --execute
```

```json
{
  "phase": "execute",
  "operation": "jira-comment",
  "success": true,
  "result": {
    "ticket": "PROJ-42",
    "comment_id": "10234",
    "comment_url": "https://your-domain.atlassian.net/rest/api/3/issue/PROJ-42/comment/10234"
  },
  "attribution": "Footer: _This comment was generated by carter-bot._"
}
```

```
Carter: Comment posted on PROJ-42. The auth module is branched, committed,
        pushed, and tracked in Jira.
```

### Key takeaway

Every write operation went through carter-ops with explicit approval. The agent prepared the parameters using its domain knowledge (branch naming conventions, commit message format), but the execution was deterministic — the same JSON plan, the same commands, regardless of which LLM model was running. The user saw exactly what would happen before it happened.

---

## What to Try Next

| Task | How |
|------|-----|
| Design review | `copilot --agent carter-architect -i "Review this system design: [paste]"` |
| Code review | `copilot --agent carter-engineer -i "Review src/auth.py for security"` |
| Create a Jira ticket | `copilot --agent carter-pm -i "Create a story for adding OAuth2 support"` |
| Explain a concept | `copilot --agent carter-learner -i "Explain Terraform state locking"` |
| Build a pipeline | `copilot --agent carter-devops -i "Create a GitHub Actions workflow for Go"` |
| Multi-domain task | `copilot --agent carter-maestro -i "Plan, implement, and deploy a new feature"` |

For the full carter-ops reference (all operations, params, output formats), see [carter-ops.md](carter-ops.md).
