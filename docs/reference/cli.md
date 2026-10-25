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
| `--bot-name TEXT` | Co-author name for commits made through `ops:` (default `carter-bot`) |
| `--base-dir DIRECTORY` | Install into another base directory (for testing) |
| `-q`, `--quiet` | Errors only |
| `-v`, `--verbose` | Detailed output |
| `--debug` | Debug output |

Safe to re-run. See [Install](../guides/install.md#upgrade) and
[MCP servers](../guides/mcp-servers.md).

## carter uninstall

Remove the Carter OpenCode install: agents, skills, global rules, unedited knowledge
files, `carter-*` MCP servers and the install manifest. Edited files, memories,
`config.toml` and the audit log are kept.

| Option | Description |
|--------|-------------|
| `--base-dir DIRECTORY` | Uninstall from another base directory (for testing) |

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
carter update [--dry-run] [TARGET_DIR]
```

Regenerate the `carter-*` agent files from `.carter/carter.yaml`. `AGENTS.md` is
created only if missing. `--dry-run` lists the files without writing them.

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
service if it isn't running and leaves it running. It retries for a few seconds if
OpenCode still serves old files, and times out after 30 seconds per call. It is
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

Print the attribution settings the agents use: bot name and email, signing key,
footer, and whether `GITHUB_TOKEN` is set.

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
