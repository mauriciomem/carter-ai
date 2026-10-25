# Using Carter

This page shows how to talk to Carter day to day: choosing the agent, asking for
work, getting a review, and keeping sessions efficient.

## Pick Maestro

OpenCode has two kinds of agents:

- **Primary agents** are the ones you talk to. You switch between them in the
  terminal UI.
- **Subagents** are launched by a primary agent to do part of the work, each in a
  fresh session.

In Carter, **Maestro is the primary agent** and the seven specialists are subagents.
To select Maestro in OpenCode:

- press `Shift+Tab` to cycle through primary agents, or
- press `Ctrl+X` then `A` (or type `/agents`) and pick **carter-maestro**.

To make Maestro the default for new sessions, set `default_agent` in your OpenCode
config ([OpenCode agents](https://opencode.ai/v2/docs/agents/)):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "default_agent": "carter-maestro"
}
```

> [!NOTE]
> In OpenCode, `@` attaches a **file** to your prompt (`Review @src/auth.py`). It does
> not select an agent.

## Ask for work

Write what you need in plain language. Maestro decides how to handle it:

| Request | What Maestro does |
|---------|-------------------|
| Simple question, or "summarize this file" | Answers itself |
| One domain ("write a GitHub Actions workflow") | Hands it to one specialist |
| Several domains ("design, implement and deploy X") | Runs specialists one after another, passing each result to the next |
| Unclear | Asks you |

To choose the specialist yourself, name it:

```text
Use carter-security to threat-model the login flow.
Ask carter-learner to explain Terraform state locking.
```

Subagents don't see your chat history. Maestro passes them the context they need,
but a complete request (files, constraints, what "done" means) still gets better
results than a vague one.

## Examples to try

| Goal | Prompt |
|------|--------|
| Design review | `Review this design for scaling problems: <paste>` |
| Code review | `Review @src/auth.py for security issues.` |
| Pipeline | `Create a GitHub Actions workflow that tests a Go module.` |
| Explanation | `Explain how Terraform state locking works, with sources.` |
| Plan | `Plan the work to add OAuth2 login, with risks.` |
| Threat model | `Use carter-security to threat-model the file upload feature.` |
| PR text | `Write a PR description for my current changes.` |
| Git | `ops: create a branch, commit my changes and open a PR.` |

The last one uses the [`ops:` approval flow](write-operations.md).

## Review before you push

Ask Maestro for a review ("review my changes", "check before push"). It runs the
**quality gate**:

1. It works out what changed.
2. The Engineer reviews code and tests. The Architect joins for larger or structural
   changes (more than five files). Code changes also get a security check.
3. Findings come back grouped by severity.
4. If anything is blocking, you fix it and Maestro reviews again. By default it stops
   after 2 rounds and lets you decide.

A typical result looks like this:

<details>
<summary>Sample review output</summary>

```text
Review: auth module (3 files)

🚨 Blocking (1)
- src/auth/token.py:42 compares tokens with ==; use hmac.compare_digest
  to avoid timing attacks.

⚠️ Suggestions (2)
- No test covers an expired refresh token.
- refresh() and rotate() duplicate the expiry check.

💡 Nitpicks (1)
- TOKEN_TTL could live in settings with the other timeouts.
```

</details>

In a workspace you can turn the gate off or change the number of rounds with
`quality_gate` in [`carter.yaml`](../reference/configuration.md).

## Global and workspace agents together

If you also ran `carter init` in a project, OpenCode shows both sets there: the global
`carter-maestro` and the workspace `carter-maestro-local`. Pick the `-local` one to
use the project's settings and memory. See
[Your first workspace](first-workspace.md#global-and-workspace-agents).

## Keep sessions efficient

Every handoff to a specialist sends context to the model again, and you pay for it.

- **Name the specialist** when you already know who should do the work.
- **Give complete context up front** so the agent doesn't have to ask and redo.
- **Ask for files to be read in one batch** rather than one at a time.
- **Install only the MCP servers you use.** Their tool lists are sent with every
  request.

[Cost and models](cost-and-models.md) has the rest.

## Language

Talk to Carter in any language. Anything that lands in a repository or leaves your
machine (commits, code comments, PRs, Jira, Slack) is written in English. Carter's
own notes in `.carter/` follow the workspace `docs_language` setting.

## Next

- [Safety and permissions](safety-and-permissions.md)
- [Write operations](write-operations.md)
- [Memory and plans](memory-and-plans.md)
