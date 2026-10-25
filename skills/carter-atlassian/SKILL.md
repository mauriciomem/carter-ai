---
name: carter-atlassian
description: Manage Jira tickets and follow best practices for writing stories, bugs, tasks, and epics. Use when creating, updating, commenting on, or querying Jira issues.
---

<objective>
Perform Jira operations and write high-quality tickets using the carter-atlassian MCP server.

**Language:** Jira tickets, comments and descriptions are always written in English, whatever language the user chats in.
</objective>

<tools>
Use the **carter-atlassian** MCP server for all Jira operations. Available tools include searching issues, creating issues, updating issues, adding comments, and reading issue details. Always prefer MCP tools over suggesting the user do things manually in the Jira UI.
</tools>

<guidelines>

## Operations

### Search Issues (JQL)

Use JQL queries through the MCP server to find issues:

```
# My open issues
assignee = currentUser() AND status != Done

# Recent bugs in a project
project = PROJ AND type = Bug AND created >= -7d

# Sprint backlog
project = PROJ AND sprint in openSprints()

# Unestimated issues
project = PROJ AND "Story Points" is EMPTY AND type = Story

# High-priority items
project = PROJ AND priority in (Highest, High) AND status != Done

# Issues updated this week
project = PROJ AND updated >= startOfWeek()

# Epics without children
project = PROJ AND type = Epic AND issueFunction not in hasLinks("is parent of")
```

### Add Comments

When adding a comment to a Jira ticket, use **Atlassian Document Format (ADF)** — not Markdown. Structure comments with clear sections:

**Comment template:**

```
Heading: [Context — what was done or decided]

Status update or finding, written in plain paragraphs.

If listing items:
- Bullet points for observations, actions, or blockers

If referencing code or commands:
  Code block with the relevant snippet

Next steps or open questions at the end.
```

**Good comment examples:**

> **Investigation: API latency spike on 2026-05-10**
>
> Root cause: the `/users` endpoint performs N+1 queries when loading team memberships. Each request triggers 15-30 additional DB calls.
>
> - Confirmed via query logs in Datadog (dashboard link)
> - Reproduced locally with 50+ team members
> - Workaround: eager-load memberships in the initial query
>
> Fix PR in progress — targeting next sprint.

> **Decision: Use S3 for artifact storage**
>
> After evaluating GCS and S3, we're going with S3:
> - Existing IAM roles already configured
> - Cost parity for our volume
> - Team familiarity
>
> @john.doe to update the Terraform module by Friday.

**Avoid:** one-word comments ("done", "fixed"), pasting raw logs without context, comments that duplicate the issue description.

> Comment and description bodies follow the **Brief register** (canonical
> definition in `carter-docs`): lead with the answer/ask, one screen not a page,
> concrete and plain, scoped to the ticket.

### Update Issues

When updating tickets, change only the fields requested. Common operations:

- **Transition status**: move through the workflow (To Do → In Progress → Done)
- **Assign**: set or change the assignee
- **Priority**: update if severity changes
- **Labels/Components**: add for categorization
- **Link issues**: relate, block, or duplicate

## Writing Good Tickets

### Story

**Summary format:** `As a [persona], [action] so that [outcome]`

**Required fields:**
- **Summary**: one sentence, starts with the persona or action
- **Description**: context, acceptance criteria, and scope
- **Story Points**: estimated complexity
- **Labels/Components**: team or feature area

**Description template:**

```
## Context
[Why this story exists — link to epic, user feedback, or business goal]

## Acceptance Criteria
- [ ] [Specific, testable criterion]
- [ ] [Another criterion]
- [ ] [Edge case or error handling]

## Scope
**In scope:** [what this story covers]
**Out of scope:** [what it explicitly does not cover]

## Technical Notes
[Optional — architecture hints, dependencies, or constraints]
```

**Good example:**
> **Summary:** As a platform engineer, automate VPC peering setup so that new environments connect without manual steps
>
> **Context:** Currently takes 2 hours of manual work per environment. Blocks the self-service provisioning epic (PROJ-100).
>
> **Acceptance Criteria:**
> - [ ] Running `terraform apply` creates VPC peering between hub and spoke
> - [ ] Route tables updated automatically in both VPCs
> - [ ] Peering works across accounts (hub: shared-services, spoke: target)
> - [ ] Fails gracefully if peering already exists
>
> **Out of scope:** Transit Gateway migration (separate story)

### Bug

**Summary format:** `[Component] — [what's broken] when [trigger]`

**Required fields:**
- **Summary**: component, symptom, and trigger
- **Description**: steps to reproduce, expected vs actual, environment
- **Priority**: severity-based (Highest = production down, High = major feature broken, Medium = degraded, Low = cosmetic)
- **Labels**: `bug`

**Description template:**

```
## Steps to Reproduce
1. [First step]
2. [Second step]
3. [Trigger action]

## Expected Behavior
[What should happen]

## Actual Behavior
[What actually happens — include error messages, screenshots, or logs]

## Environment
- Version/Release: [x.y.z]
- OS/Browser: [if relevant]
- Account/Region: [if relevant]

## Impact
[Who is affected, how many, workaround available?]
```

**Good example:**
> **Summary:** Auth — login fails with 500 when email contains `+` character
>
> **Steps to Reproduce:**
> 1. Navigate to /login
> 2. Enter email `user+test@example.com`
> 3. Submit valid password
>
> **Expected:** Successful login
> **Actual:** 500 Internal Server Error — `InvalidEmailFormat` in server logs
>
> **Environment:** Production, v3.2.1
> **Impact:** Affects ~200 users with plus-addressed emails. Workaround: use alias without `+`.

### Task

**Summary format:** `[Verb] [object] [context]`

Tasks are concrete, actionable work items — not user-facing features.

**Description template:**

```
## Objective
[What needs to be done and why]

## Steps
1. [Concrete action]
2. [Next action]
3. [Verification step]

## Done When
- [ ] [Measurable completion criterion]
```

**Good example:**
> **Summary:** Upgrade Terraform AWS provider from 5.x to 6.0
>
> **Objective:** AWS provider 5.x reaches end of support in June. Upgrade to 6.0 to maintain security patches and access new resources.
>
> **Steps:**
> 1. Update version constraint in `terraform.tf`
> 2. Run `terraform init -upgrade`
> 3. Run `terraform plan` — address breaking changes
> 4. Test in dev workspace first
>
> **Done When:**
> - [ ] All workspaces updated to provider 6.0
> - [ ] CI pipeline passes with new provider
> - [ ] No unexpected resource replacements in plan

### Epic

**Summary format:** `[Initiative or capability]`

Epics are containers — keep the description high-level and link child stories.

**Description template:**

```
## Goal
[Business or technical outcome this epic achieves]

## Background
[Context, motivation, or problem statement]

## Success Criteria
- [Measurable outcome]
- [Another outcome]

## Stories
[List planned stories or link them as children]
```

## General Ticket Quality Rules

1. **One concern per ticket** — don't combine unrelated work
2. **Actionable summary** — someone should understand the work from the title alone
3. **Link related issues** — use "blocks", "is blocked by", "relates to"
4. **Keep descriptions updated** — if scope changes, update the ticket, don't just add comments
5. **Close the loop** — add a resolution comment before transitioning to Done
6. **No orphan tickets** — every story should belong to an epic; every task should have context

</guidelines>
