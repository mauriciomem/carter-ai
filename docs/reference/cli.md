# CLI reference

Every `carter` command and option. For a walkthrough, start with
[Install Carter](../guides/install.md).

```text
carter [--version] [--help] COMMAND [ARGS]
```

| Command | Purpose |
|---------|---------|
| [`install`](#carter-install) | Install the agents, skills and rules into OpenCode |
| [`uninstall`](#carter-uninstall) | Remove what `install` wrote |
| [`init`](#carter-init) | Create a workspace in a project directory |
| [`update`](#carter-update) | Regenerate a workspace's agents from `carter.yaml` |
| [`check`](#carter-check) | Validate a workspace and confirm OpenCode loads it |
| [`save`](#carter-save) | Commit the workspace state to its private history |
| [`ops`](#carter-ops) | Audit log and config helper used by the `ops:` flow |

Commands that take a `TARGET_DIR` default to the current directory, which must
exist.

## carter install

Install Carter for OpenCode 2.1 or newer. Writes to `~/.config/opencode/` and
`~/.carter/`. Stops without writing anything if OpenCode is missing or too old.

| Option | Description |
|--------|-------------|
| `--mcp` | Also configure the MCP servers |
| `--mcp-servers TEXT` | Comma-separated subset: `github`, `terraform`, `atlassian`. Default: all. Only with `--mcp` |
| `--bot-name TEXT` | Deprecated and ignored: prints a warning. The co-author now comes from the LLM identity in `~/.carter/config.toml` (see [Attribution](../guides/write-operations.md#attribution)) |
| `--base-dir DIRECTORY` | Install into another base directory (for testing) |
| `-y`, `--yes` | Also install the policy guards without asking. Without a terminal and without `--yes` the guards are skipped with a notice |
| `-q`, `--quiet` | Errors only |
| `-v`, `--verbose` | Detailed output |
| `--debug` | Debug output |

Safe to re-run. It also creates `~/.carter/config.toml` (schema 2) on a first install
and migrates an older one once, after saving `config.toml.schema1.bak`. If your global
`AGENTS.md` has your own edits, it is left alone and the new commit rule is printed and
saved to `~/.carter/upgrade-notes/<version>.md`. See [Install](../guides/install.md#upgrade)
and [MCP servers](../guides/mcp-servers.md).

## carter uninstall

Remove the Carter OpenCode install: agents, skills, global rules, unedited knowledge
files, `carter-*` MCP servers and the install manifest. Edited files, memories,
`config.toml` and the audit log are kept.

| Option | Description |
|--------|-------------|
| `--base-dir DIRECTORY` | Uninstall from another base directory (for testing) |
| `--keep-guards` | Leave the policies, per-agent denies, include line and guard state in place |
| `-y`, `--yes` | Remove the guards without asking. Without a terminal and without `--yes` they are kept |

Unless `--keep-guards` is given, uninstall first removes the policy guards it installed,
only where it is unchanged since (anything you edited is kept and reported). A guard
problem is printed and makes the exit code 1 but never stops the rest of the removal.

## carter init

```text
carter init [OPTIONS] [TARGET_DIR]
```

Create `.carter/`, `.opencode/agents/` and `AGENTS.md` in `TARGET_DIR`. Existing
files (`carter.yaml`, knowledge files, `AGENTS.md`) are not overwritten.

| Option | Description |
|--------|-------------|
| `--single` | Single-repository mode; also adds `.carter/` to `.gitignore` (default: umbrella) |
| `--no-git-state` | Don't create the private Git repository in `.carter/` |
| `--name TEXT` | Workspace name (default: directory name) |
| `--agent-suffix TEXT` | Agent name suffix (default `local`; `''` for none) |
| `--profile [budget\|quality]` | Cost profile. Default: the shipped per-agent tiers |
| `--docs-language TEXT` | Language for Carter's own notes, e.g. `es`, `pt-BR` (default `en`) |

## carter update

```text
carter update [--dry-run] [--yes] [TARGET_DIR]
```

Regenerate the `carter-*` agent files from `.carter/carter.yaml`. `AGENTS.md` is
created only if missing; if yours still has the old commit rule, `update` says so and
prints the current rule without rewriting the file. `--dry-run` lists the files without
writing them.

`update` is also the only place that applies the `identity` policy of `carter.yaml`
(`role` and `require_tier`, see [Configuration](configuration.md#identity)). It shows
each change and its source, then pins the values in `~/.carter/config.toml` under
`[workspaces."<path>"]` after you confirm. `--yes` skips the question; without a
terminal and without `--yes` the policy is not pinned and `update` says so. Editing
`carter.yaml` alone changes nothing until the next `update`.

| Option | Description |
|--------|-------------|
| `--dry-run` | List what would be rendered and pinned; write nothing |
| `--yes`, `-y` | Pin the identity policy without asking |

`update` stops without pinning when `max_tier` in `config.toml` (set by hand) is below
`require_tier`, when `config.toml` holds keys Carter doesn't manage (it prints the
difference and never overwrites the file), or when `config.toml` is invalid or still
schema 1 (run `carter install` first).

## carter check

```text
carter check [--no-harness] [TARGET_DIR]
```

Validate a workspace. Exits with status 1 and lists the problems if any check fails:

- agent files, `AGENTS.md` and knowledge files exist;
- each agent's `permissions` and `model` match what `carter.yaml` generates;
- plans and the session checkpoint follow their [schemas](frontmatter.md);
- OpenCode loads every agent with the same description, model and rules.

The last step runs `opencode debug agents`, which starts OpenCode's background
service if it isn't running and leaves it running. It first waits until the newest
agent file is 1.5 s old. A stale or failed result is retried, up to 5 attempts with
0.5, 1, 2 and 4 s pauses. A single call that takes longer than 30 s fails the check
at once, without retrying. It is
skipped with a warning when `opencode` isn't on `PATH`; `--no-harness` skips it on
purpose.

On success, `carter check` also prints each agent's model, because Carter can't
verify that your provider offers it.

## carter save

```text
carter save [-m MESSAGE] [TARGET_DIR]
```

Commit everything in `.carter/` to its private repository (`.carter/.git`), so a
deleted plan or checkpoint can be recovered. Your Git identity is the author. Prints
`Nothing to save (no changes or git state disabled)` when there is nothing to do.

| Option | Description |
|--------|-------------|
| `-m`, `--message TEXT` | Commit message (default: `chore: checkpoint state (<timestamp>)`) |

## carter ops

```text
carter ops {audit|policy-override|config --emit} [--key value ...]
```

A small helper for the [`ops:` flow](../guides/write-operations.md). It doesn't run
Git or GitHub commands itself. Output is JSON on stdout; errors go to stderr. Exit
code 0 means success, 1 a usage or validation error. `carter ops --help` prints
the usage.

### carter ops config --emit

Print, as JSON, the attribution the agents must use right now. The values are resolved
when you run it, from `~/.carter/config.toml` and the environment:

| Key | Meaning |
|-----|---------|
| `tier` | `t0` (nothing configured), `t1` (LLM account, no key) or `t2` (account and key) |
| `role`, `role_source` | `co-author` or `author`, and where it came from (`workspace`, `env`, `config`, `default`) |
| `coauthor_trailer` | The trailer line for commit messages: `Assisted-by: Carter` at T0, `Co-authored-by: <login> <noreply address>` above |
| `commits` | `allowed` or `refused` |
| `refusal_reason` | The error code when `commits` is `refused` (for example `E-CONFIG` or `E-ROLE-B-TIER`) |
| `footer` | Text appended to GitHub and Jira bodies |
| `has_github_token` | Whether `GITHUB_TOKEN` is set |

An invalid `config.toml` gives `commits: refused` with `E-CONFIG`: agent commits stay off
until it is fixed. Carter never reads your signing key.

### carter ops audit

Append one entry to `~/.carter/audit.log` after an operation.

| Option | Required | Description |
|--------|----------|-------------|
| `--operation NAME` | yes | Operation name, e.g. `git-flow` |
| `--result success\|failure` | yes | Outcome |
| `--params JSON` | no | Inputs, e.g. `'{"branch":"feature/x"}'` |
| `--identifiers JSON` | no | Results, e.g. `'{"commit_sha":"abc1234"}'` |

### carter ops policy-override

Record a deliberate exception to a [permission rule](../guides/safety-and-permissions.md#record-an-exception).
It records the decision; it doesn't change any rule. Every entry is stored with
`"authorized": false`.

| Option | Required | Description |
|--------|----------|-------------|
| `--category` | yes | `read`, `local-write`, `remote-write` or `dangerous` |
| `--action` | yes | The exact action, up to 500 characters |
| `--tier` | yes | `native-deny` (you relaxed a deny), `native-ask` (you confirmed a prompt), `prose-backstop` (only agent guidance applied, e.g. the Narrator review) |
| `--reason` | no | Why, up to 500 characters. Never put secrets here |
