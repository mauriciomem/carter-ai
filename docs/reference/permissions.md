# Permissions reference

The exact permission rules Carter writes into every agent file. For the concepts
and how to change them, read [Safety and permissions](../guides/safety-and-permissions.md).

## Agent file format

Each agent is a Markdown file whose frontmatter has exactly four keys
([OpenCode agents](https://opencode.ai/v2/docs/agents/)):

| Key | Value |
|-----|-------|
| `description` | One-line summary of the role |
| `mode` | `primary` for Maestro, `subagent` for the other seven |
| `model` | One `provider/model[#variant]` string |
| `permissions` | Ordered list of `{action, resource, effect}` rules |

OpenCode applies the **last matching rule**, so later rules refine earlier ones
([OpenCode permissions](https://opencode.ai/v2/docs/permissions/)).

## Rule order

| # | Action / resource | Effect |
|---|-------------------|--------|
| 1 | `*` / `*` | ask (the baseline) |
| 2 | `read`, `glob`, `grep`, `skill`, `question` / `*` | allow |
| 3 | `read` / `*.env` and `*.env.*` | ask |
| 3 | `read` / `*.env.example` | allow |
| 4 | `external_directory` and `read` / `~/.carter/*` | allow |
| 4 | `edit` / `~/.carter/memories/*` (agents with local-write only) | allow |
| 5 | `subagent` / `*` | deny |
| 5 | `subagent` / `carter-*` (Maestro only) | allow |
| 6 | `edit`, `shell`, `webfetch` / `*` | allow with local-write, otherwise ask |
| 7 | `shell` / each risky command below | the category's effect if the agent holds it, otherwise deny |

Anything not listed (MCP tools, `websearch`, other tools) falls back to rule 1 and
asks.

## Risky commands

| Category | Commands |
|----------|----------|
| remote-write | `git push *`, `gh pr create *`, `gh pr merge *`, `gh pr comment *`, `gh pr review *`, `gh pr edit *`, `gh issue create *`, `gh issue comment *`, `gh issue edit *`, `gh release *`, `gh api *`, `vault read *`, `vault write *` |
| dangerous | `terraform apply *`, `terraform destroy *`, `kubectl apply *`, `helm upgrade *`, `rm -rf *`, `git reset --hard *`, `git push --force *` |

A pattern ending in ` *` also matches the bare command (`git push *` matches
`git push`). This is a list of common risky commands, not a sandbox: anything else
falls to rule 6.

`gh api *` is denied to every agent except DevOps, read-only calls included.

## Effects per level

| Category | `guarded` | `strict` |
|----------|-----------|----------|
| read | allow | allow |
| local-write | allow | allow |
| remote-write | ask | gate |
| dangerous | gate | deny |

`gate` is Carter's "ask, and hand over to the agent that owns this". OpenCode only
knows allow, ask and deny, so `gate` is written as `ask`; the handover is guidance
in the agent's instructions.

## Categories per agent

| Agent | read | local-write | remote-write | dangerous |
|-------|:----:|:-----------:|:------------:|:---------:|
| maestro | ✓ | | | |
| architect | ✓ | | | |
| learner | ✓ | | | |
| pm | ✓ | ✓ | | |
| narrator | ✓ | ✓ | | |
| engineer | ✓ | ✓ | | |
| security | ✓ | ✓ | | |
| devops | ✓ | ✓ | ✓ | ✓ |

Change these with `policy.allowlist` and `policy.overrides` in
[`carter.yaml`](configuration.md#policy).

## Example

The start of the Architect's rules, as written by `carter init` (read-only agent,
`guarded`):

```yaml
---
description: "Solution Architect — system design, cloud architecture, trade-off analysis, and architecture decisions."
mode: subagent
model: anthropic/claude-opus-5-5
permissions:
- action: '*'
  resource: '*'
  effect: ask
- action: read
  resource: '*'
  effect: allow
# … glob, grep, skill, question, .env and ~/.carter rules …
- action: subagent
  resource: '*'
  effect: deny
- action: edit
  resource: '*'
  effect: ask
- action: shell
  resource: '*'
  effect: ask
- action: webfetch
  resource: '*'
  effect: ask
- action: shell
  resource: git push *
  effect: deny
# … every other risky command: deny …
---
```

For DevOps, rule 6 is `allow`, and the risky commands get `ask` instead of `deny`.

## What `carter check` verifies

- Each agent's `permissions` and `model` equal what `carter.yaml` generates, in the
  same order. A hand edit shows up as drift.
- No agent file carries old-style keys (`permission`, `tools`, `bash`, `task`,
  `name`, `temperature`), which OpenCode ignores next to `permissions`.
- OpenCode loads every agent with the same description, model and rules
  (`opencode debug agents`).

It can't tell whether someone chose "Allow always" at a prompt, because OpenCode
stores that separately.
