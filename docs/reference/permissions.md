# Permissions reference

The exact permission rules Carter writes into every Carter agent file. For the concepts
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
| 5 | `carter_push` / `*` (every agent except DevOps) | deny |
| 6 | `edit`, `shell`, `webfetch` / `*` | allow with local-write, otherwise ask |
| 7 | `shell` / each risky command below | the category's effect if the agent holds it, otherwise deny |
| 8 | G2's deny set, once you installed the guards: pushes, `gh` (with the allowlist lifted again), `sudo`/`docker`, reads of credentials, edits of OpenCode, git and Carter config | deny (the `gh` allowlist and the `allow_project_opencode_edit` opt-outs: allow) |

Anything not listed (MCP tools, `websearch`, other tools) falls back to rule 1 and
asks.

## Carter's own files

The `config-edit` group (on by default; revision 2) denies the edit tool on Carter's control files:
`~/.carter/config.toml` (yours), `~/.carter/config-managed.toml` (the identity and signing key
Carter derives: it decides which key signs, so it has its own rule, `deny-edit-carter-managed`),
the hooks, the plugin, `isolation.json` and `guard-state.json`. The command gate also refuses shell
writes to every control path (`>`, `tee`, `sed -i`, `cp`, `mv`, `rm`, `ln`, `chmod`). Both lists
come from `g2_rules.json`. If you had `config-edit` at revision 1, the next `carter install` shows
one `new:` row for it.

Honest scope: a shell command that writes these files through a program the gate does not parse
stays possible until the sandbox (plan 012). Turning `config-edit` off is allowed; `carter access -v`
warns about it.

## Risky commands

| Category | Commands |
|----------|----------|
| remote-write | `vault read *`, `vault write *` (also limited by `infra_apply`) |
| github-write (denied to every agent) | `git push *` (also `--force`, `-f`, `--force-with-lease`), `gh pr merge *`, `gh pr close *`, `gh pr review *`, `gh pr ready *`, `gh issue edit *`, `gh release *`, `gh api *` |
| issue_write (follows the level, rows after the guards' rules) | `gh issue create *`, `gh issue comment *` |
| dangerous | `terraform apply *`, `terraform destroy *`, `kubectl apply *`, `helm upgrade *` (`infra_apply`); `rm -rf *`, `git reset --hard *` (`destructive`) |

A pattern ending in ` *` also matches the bare command (`git push *` matches
`git push`). This is a list of common risky commands, not a sandbox: anything else
falls to rule 6.

`git push *`, merging, closing, reviewing and readying a pull request, issue and release
writes and `gh api *` are denied to every agent, DevOps included, and `gh api` is denied even for
reads. Opening, editing and commenting on a pull request (`gh pr create|edit|comment`) is allowed
Pushing is done by you with `carter push`.

With the guards installed, the command gate also refuses environment variables that make `gh`
or `git` start another program: the pager, editor and browser variables (`GH_PAGER`, `PAGER`,
`GIT_PAGER`, `GH_EDITOR`, `GIT_EDITOR`, `GIT_SEQUENCE_EDITOR`, `VISUAL`, `EDITOR`, `GH_BROWSER`,
`BROWSER`), `GIT_EXTERNAL_DIFF`, `GIT_PROXY_COMMAND`, `SSH_ASKPASS`, `LESSOPEN` and `LESSCLOSE`.
They may be set to nothing, `cat`, `true` or `:` (`GIT_PAGER=cat git log`,
`GIT_EDITOR=true git rebase --continue`) and unset; nothing else. Every way of writing a variable
counts: a prefix, `env`, `time`, `export`/`declare`, `read`, `printf -v`, `for NAME in`,
`${NAME:=…}` and namerefs. `GH_FORCE_TTY`, `GH_HOST`, `GH_REPO`, `GH_ENTERPRISE_TOKEN` and
`GITHUB_ENTERPRISE_TOKEN` are refused with any value, and `-R`/`--repo` must be `OWNER/REPO`
(no host, no `git@host:`, no URL); a pull request or issue URL must be on github.com. The program
a command runs must be written out: `xargs env`, `xargs -I{} {}` and `source <(…)` are refused.
The list is generated into the `carter-ops` skill from `carter/identity/g2_rules.json` (the
`env-overrides` rule).

## Effects per level

The level (`[access]` in `~/.carter/config.toml`, `strict` when absent) sets one value per
capability. What an agent that can write gets:

| Commands | `strict` (default) | `guarded` | `relaxed` |
|----------|--------------------|-----------|-----------|
| `gh pr create`, `gh pr edit`, `gh pr comment` | ask | allow | allow |
| `gh issue create`, `gh issue comment` | deny | ask | allow |
| `rm -rf`, `git reset --hard` | deny | ask | ask |
| `terraform apply`, `kubectl apply`, `helm upgrade`, `vault` (DevOps only; others deny) | deny | ask | ask |

A force-push is a push: denied at every level, like `git push`.

The issue rows show the permission only. The command gate refuses `gh issue create` and
`comment` at every level until its per-verb flag allowlist lands, so today agents cannot use them.

An `allow` adds no rule: the command follows the agent's general shell rule. The pull request,
issue and `git commit` rows are written after the guards' rules, so they win over the `gh`
allows. Agents without local-write (Maestro, Architect, Learner) ask for edits and commands at
every level, and never get more than `ask` for pull requests and issues. `edit`, `shell` and
`git commit` can also be set per
capability; see [Safety and permissions](../guides/safety-and-permissions.md#choose-a-level). The
category gates `read`, `local-write`, `remote-write` and `dangerous` in `policy.overrides` still
apply on top: only an effect at least as strict as the level's counts. `gate` is written as `ask`;
the handover to the owning agent is guidance in the agent's instructions.

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
any level):

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
- OpenCode loads every agent with the same description, model and rules
  (`opencode debug agents`).

It can't tell whether someone chose "Allow always" at a prompt, because OpenCode
stores that separately.
