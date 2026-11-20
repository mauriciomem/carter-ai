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
   category the agent doesn't hold are denied. Agents without local-write can still
   edit files, run shell commands and fetch web pages, but OpenCode asks first.

On top of that, the [guards](install.md#guards) isolate Carter agents' shells from your
credentials and refuse pushes in any spelling.

## The four risk categories

| Category | Examples | `guarded` | `strict` (default) |
|----------|----------|-----------|--------------------|
| **read** | read and search files, `git status`, `git diff` | allow | allow |
| **local-write** | edit files, run commands and tests, `git commit` | allow | allow |
| **remote-write** | `vault read` | ask | **deny** |
| **dangerous** | `terraform apply`, `kubectl apply`, `helm upgrade`, `rm -rf`, `git reset --hard` | ask | **deny** |

At `strict`, opening and commenting on a pull request also ask. Pushing, merging and the `gh`
writes other than opening, editing and commenting on a pull request are denied to every agent
whatever the level. The exact command patterns are in the
[permissions reference](../reference/permissions.md).

## Who can do what

| Agent | Categories it holds |
|-------|---------------------|
| Maestro, Architect, Learner | read |
| Engineer, PM, Narrator, Security | read, local-write |
| DevOps | read, local-write, remote-write, dangerous |

What that means in practice:

- **Nobody pushes or merges.** `git push` and the `gh` writes other than opening, editing and
  commenting on a pull request are denied to every agent, DevOps included. You push with
  `carter push` (in your terminal or as `!carter push` in OpenCode). Agents open, edit and comment on pull requests with `gh pr create|edit|comment`
  ([Write operations](write-operations.md#pushing-and-pull-requests)). Merging, closing,
  reviewing and marking a pull request ready are yours. **One optional exception:** DevOps alone
  has a tool, `carter_push`, that *asks you to approve each use*
  ([Write operations](write-operations.md#letting-devops-ask-you-to-push)).
- **The guards bind Carter's agents only.** The deny rules sit in each Carter agent's own
  permissions, and the plugin and gate act for Carter agents and Carter workspaces
  ([Install: scope](install.md#scope-only-carter-agents-and-carter-workspaces)). Other OpenCode
  agents, such as `build`, are not restricted by Carter.
- **A CI review run commits nothing.** The optional [review-only CI](ci-review.md) workflow gives
  its model read tools only, has `contents: read`, and Carter refuses commits in a detected CI.
- **Only DevOps can change infrastructure** and send Jira and Slack text.
- **Agents without local-write still can, but must ask.** Maestro, Architect and Learner get a
  prompt before they edit a file or run a shell command, including `git commit`.
- **Infrastructure and remote commands are denied** to every agent except DevOps. `rm -rf` and
  `git reset --hard` follow the level for every agent that can write: they ask at `guarded`
  and are denied at `strict`.
- **Reading `.env` files asks** for every agent. `.env.example` is allowed.
- **Only Maestro launches subagents**, and only Carter ones (`carter-*`).

## Choose a level

Set the level in `~/.carter/config.toml`, which only you edit, and regenerate:

```toml
[access]
level = "guarded"   # strict | guarded | relaxed
```

```bash
carter update
```

| Level | Use it for |
|-------|-----------|
| `strict` (default) | Agents edit, run and commit locally. Opening a pull request asks; destructive and infrastructure commands and issue writes are denied |
| `guarded` | Day-to-day work. Pull requests open without asking; issues, destructive and infrastructure commands ask |
| `relaxed` | `guarded`, and agents open and comment on issues without asking |

A missing `[access]` counts as `strict`, and so does an invalid one (`carter update` names the
problem). The first `carter update` after the upgrade says so once. Global and workspace agents use
the same level. A workspace can only tighten it: `access:` in `.carter/carter.yaml` takes the same
keys, and `policy.level` there is a deprecated alias; a looser value is ignored with one line.

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
- **A workspace cannot loosen Carter's defaults, but it cannot keep your tightening either.**
  Loosening keys in `.carter/carter.yaml` are ignored (see Customize). An agent that can edit the
  file can still undo a stricter setting you wrote there, until a human-side floor
  (`[access]` in `~/.carter/config.toml`) arrives. An agent with edit or shell access can also
  change its rendered agent file directly; `carter check` reports the drift.

## What the guards cannot do

With the plugin installed, the isolation (no SSH agent, a read-only token, no `git push` in any
spelling) does the real work. The command gate is a speed bump in front of it, not a sandbox.

- **Same-user evasion.** Agents run as you. The gate parses the command line; it does not
  read a script or program the agent writes and runs by path (`python3 tool.py`,
  `bash run.sh`, a sourced file), and it cannot see through every way of building a command at
  run time. What an evaded gate still cannot do is reach your SSH keys or write to GitHub.
  Until Carter runs agents in a sandbox, a determined process running as you is not contained.
- **Outside Carter there are no guards.** Other agents (`build`, `plan`, your own) and sessions
  outside a Carter workspace are not gated, not isolated and not read- or edit-denied. With the
  plugin not loaded, nothing stops their `git push` but the credentials they have.
- **`carter_push` can be forged by a same-user agent.** An agent running as you, with the OpenCode
  server password, can answer its approval prompt through the server API after any delay. The
  prompt and the dwell rule stop a careless agent and an auto-accepting client, not a hostile one
  ([Write operations](write-operations.md#what-this-does-not-stop)).
- **`git push --no-verify` skips the `pre-push` hook.** The hook is the backstop for pushes
  the gate never saw; the gate itself rejects every `git push`.
- **Shell writes outside Carter's own files are not gated:** the global OpenCode config,
  `~/.gitconfig`, `~/.config/git/`, a repository's `.opencode/`, `opencode.json[c]`, `.git/hooks/`
  and `.git/config`. The edit tool is denied there; a shell command can still write them. A plugin
  planted in a project's `.opencode/` would load into the OpenCode server, and a planted
  `.git/hooks/pre-commit` runs in your terminal with your credentials. `carter check --host` lists
  project config that can run code and plugin files Carter did not write; review them.
- **The read-only token is visible to the model.** It is in the environment of the agent's shell
  (`GH_TOKEN`), so it is only as safe as a fine-grained token without **Contents** write is: give it
  the fewest repositories you can.
- **Agent commits are unsigned unless LLM signing is on.** Author and committer are you, and the trailer credits
  Carter. With LLM signing on the LLM identity signs; if it cannot, the commit fails and stays staged. Set
  `max_tier = "t1"` in a workspace's table of `~/.carter/config.toml` to allow unsigned agent
  commits there. A squash merge drops the signature from `main`. The limits of signing itself are in
  [Identity and signing](identity-and-signing.md#what-signing-does-not-protect).
- **A false failure of the plugin's own check is conservative.** If another plugin rejects a command after
  Carter's, the check can end `failed`; then every shell, yours in the `!` prompt
  included, is treated as an agent shell until you restart OpenCode.
- **Fail closed.** If the gate, the plugin or `isolation.json` breaks, agent shells are
  refused; your terminal and the `!` prompt keep working, and
  `carter guard remove --only plugin` is yours to run.

## Customize

A workspace can only tighten permissions. `.carter/carter.yaml` is a file agents can edit, so
a key that loosens a control is ignored: `carter update` and `carter check` print one line
(`carter update -v` names the keys) and render Carter's defaults. Loosening is human-only: it
is set with `[access]` in `~/.carter/config.toml`.

Make a category stricter for every agent that holds it:

```yaml
policy:
  overrides:
    remote-write: deny   # a gate at least as strict as the level's: ask < gate < deny
```

Take a category away from one agent:

```yaml
policy:
  allowlist:
    devops:
      dangerous: false
```

An `allowlist` entry set to `true` that Carter does not already grant (for example
`engineer: remote-write: true`) is ignored, and so is an override to a looser gate.

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
action, and a GitHub write cannot be recorded this way. See
[Write operations](write-operations.md#audit-log) for the log format.

## Next

- [Permissions reference](../reference/permissions.md): the exact rules, in order
- [Write operations](write-operations.md)
