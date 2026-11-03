# Safety and permissions

Carter decides what each agent may do without asking you. This page explains the
model, how to choose a safety level, and what it does **not** protect against.

## How it works

Carter doesn't run the agents, OpenCode does. So Carter writes the rules into each
agent file as an OpenCode
[`permissions` list](https://opencode.ai/v2/docs/permissions/), and OpenCode applies
them to every tool call. Each rule has one of three effects: **allow**, **ask** (you
get a prompt) or **deny**.

Three ideas decide the effect for any action:

1. **Everything asks by default.** Only what is explicitly allowed runs silently.
2. **Actions fall into four risk categories.**
3. **Each agent is granted only the categories its job needs.** Risky commands in a
   category the agent doesn't hold are denied. Agents without local-write still
   can edit files, run shell commands and fetch web pages, but OpenCode asks first.

## The four risk categories

| Category | Examples | `guarded` (default) | `strict` |
|----------|----------|---------------------|----------|
| **read** | read and search files, `git status`, `git diff` | allow | allow |
| **local-write** | edit files, run commands and tests, `git commit` | allow | allow |
| **remote-write** | Jira and Slack writes, `vault read` (the `git push` and `gh` write commands are denied to every agent) | ask | ask |
| **dangerous** | `terraform apply`, `kubectl apply`, `helm upgrade`, `rm -rf`, `git push --force` | ask | **deny** |

The exact command patterns are in the
[permissions reference](../reference/permissions.md).

## Who can do what

| Agent | Categories it holds |
|-------|---------------------|
| Maestro, Architect, Learner | read |
| Engineer, PM, Narrator, Security | read, local-write |
| DevOps | read, local-write, remote-write, dangerous |

What that means in practice:

- **Nobody pushes.** `git push` and the `gh` write commands are denied to every agent,
  DevOps included; you push with `carter push` and open the pull request with
  `carter pr`, in your own terminal ([Write operations](write-operations.md#pushing-and-pull-requests-the-handoff)).
  A finished branch is handed over as a file.
- **Only DevOps can change infrastructure** and send Jira and Slack text.
- **Read-only agents still can, but must ask.** Maestro, Architect and Learner get a
  prompt before they edit a file or run a shell command, including `git commit`.
- **Remote and dangerous commands are denied** to every agent except DevOps.
- **Reading `.env` files asks** for every agent. `.env.example` is allowed.
- **Only Maestro launches subagents**, and only Carter ones (`carter-*`).

## Choose a level

In a workspace, set the level in `.carter/carter.yaml` and regenerate:

```yaml
policy:
  level: guarded   # guarded | strict
```

```bash
carter update
```

| Level | Use it for |
|-------|-----------|
| `guarded` | Day-to-day work. Remote and destructive actions wait for you |
| `strict` | Regulated or production-critical repositories. Destructive and infrastructure-changing commands are blocked outright |

A missing or unknown level counts as `guarded`. The global agents from
`carter install` always use `guarded`.

## Know the limits

> [!WARNING]
> **"Allow always" removes the prompt for good.** When OpenCode asks and you choose
> "Allow always", it saves a project-wide allow rule, and that action won't ask
> again, even for risky commands. Choose "Allow once" for anything remote or
> destructive.

- **The command lists are examples, not a sandbox.** A command that isn't listed
  (say, `curl -X POST` to an API) follows the agent's general shell rule, which is
  "allow" for agents with local-write.
- **MCP tools, web search and similar tools always ask.** They have no specific
  rule, so they fall back to the "ask" default.
- **Narrator review is guidance, not enforcement.** Carter tells DevOps to have the
  Narrator remove secrets and internal details from PR bodies, release notes and Jira
  comments before posting. Nothing in OpenCode forces that step, so read what goes
  out.
- **`deny` is a hard stop.** If an ask is not enough, use `strict` or a `deny`
  override (below).

## Customize

Both settings merge with Carter's defaults, so you only write what you change.

Make a category stricter (or looser) for every agent that holds it:

```yaml
policy:
  overrides:
    remote-write: deny   # allow | ask | gate | deny
```

Grant an extra category to one agent. Be careful: this one breaks the "only DevOps
changes things" rule. It does not allow pushing, which is denied for every agent.

```yaml
policy:
  allowlist:
    engineer:
      remote-write: true
```

Run `carter update` after each change and `carter check` to confirm OpenCode loaded
it. A typo in `overrides` or `allowlist` fails with a clear error, and so does an
`allowlist` entry for an agent that isn't in `agents:`:

```text
Error: Invalid policy.allowlist.engineer category 'remote-wirte'. Must be one of: read, local-write, remote-write, dangerous.
```

## Record an exception

When a rule blocks something you really need to do, you can run it yourself and
record the decision in Carter's audit log:

```bash
carter ops policy-override \
  --category dangerous \
  --action "terraform apply -target=module.network" \
  --tier native-deny \
  --reason "approved change CHG-1234"
```

This **records** the exception; it doesn't lift any rule. One entry covers one
action. See [Write operations](write-operations.md#audit-log) for the log format.

## Next

- [Permissions reference](../reference/permissions.md): the exact rules, in order
- [Write operations](write-operations.md)
