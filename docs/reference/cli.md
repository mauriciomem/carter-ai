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
| [`identity`](#carter-identity) | Unlock and lock the LLM signing key (more subcommands arrive with slice 2b) |
| [`github-token`](#carter-github-token) | Store and check the read-only GitHub token |
| [`push`](#carter-push) | Push the current branch to `origin` after showing and checking it |
| [`pr`](#carter-pr) | Open a pull request from the agent's handoff file |
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

## carter guard

Policy guards for OpenCode (human terminal only). They refuse in an agent shell; a
`--dry-run` or `--print-policies` run writes nothing and works anywhere. `status` is
read-only and works anywhere. Errors print as `Error: <E-CODE>: <message>` and exit 1.

### carter guard install

```text
carter guard install [--dry-run] [--yes] [--only GROUPS] [--print-policies]
```

Writes consented policies and per-agent denies into your OpenCode config
(`opencode.json` or `.jsonc`) in one atomic, verified write, and records what it owns in
`~/.carter/guard-state.json`. Every group is shown with a one-line effect and needs your yes.
The `g2` group at revision 2 also installs the Carter plugin
(`~/.config/opencode/plugins/carter/`, found by OpenCode without any registration),
`~/.carter/isolation.json` and `~/.carter/run/`. The plugin changes every agent shell, so a
bare `--yes`, `carter install --yes` and a run without a terminal never upgrade an existing
revision 1: they print "plugin and isolation need your confirmation". Only a yes in a
terminal, or `--yes --only g2`, does. A refusal is remembered and not asked again. Restart
the OpenCode server after the plugin is installed.

| Option | Description |
|--------|-------------|
| `--dry-run` | Show the groups, the statements it would add and the per-agent denies; write nothing |
| `-y`, `--yes` | Accept every group without asking. Without a terminal and without `--yes` nothing is installed (a notice says so, exit 0) |
| `--only GROUPS` | Comma-separated: `g2`, `hooks`, `sudo-docker`, `read-edit-denies`, `config-edit`, `alias`, `repo_hooks`. `alias` has nothing to install yet and is never recorded; `hooks` needs git 2.54 and `repo_hooks` is for older git (the one that does not apply is skipped). `--only g2` with `--yes` confirms the plugin (revision 2); `plugin` is not accepted here |
| `--print-policies` | Print the `policies` block to paste by hand and exit |

If a provider or a statement is missing after the write, the config is restored from the
backup and the command fails with `E-POLICIES-MISSING`. See
[Install: guards](../guides/install.md#guards).

### carter guard status

```text
carter guard status
```

Read-only. Lists the consents (declined groups are residuals), each recorded statement as
`loaded` or `MISSING`, file drift, and the include state. It works with an absent or corrupt
guard state and says so.

### carter guard remove

```text
carter guard remove [--dry-run] [--yes] [--only GROUPS|plugin]
```

Removes the policies, per-agent denies and Carter's git files, each only where it is
unchanged since Carter wrote it (anything you edited is kept and reported). Keeps
`~/.carter/secrets/gh-read.token` (with a reminder to delete and revoke it) and
`~/.carter/state/audit/`.

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would be removed; write nothing |
| `-y`, `--yes` | Remove without asking. Without a terminal and without `--yes` the command is refused |
| `--only GROUPS` | Remove only these groups' statements (and forget their consent). `plugin` removes just the plugin, `isolation.json` and `~/.carter/run/` and puts `g2` back to revision 1: the policies, per-agent denies, hooks and the token stay, and a bare `--yes` never brings the plugin back. It can be combined with group names |

**Emergency rollback without Carter.** If `carter` itself is broken, delete the plugin
directory from your own terminal: `rm -r ~/.config/opencode/plugins/carter`. A running
OpenCode drops the plugin within seconds (restart the server to be sure). If git itself fails
because of Carter's git config, delete `~/.carter/gitconfig`. The OpenCode config you had
before the first install is in `~/.carter/backups/`.

## carter identity

The LLM's signing identity. `unlock` and `lock` manage the key Carter's dedicated `ssh-agent`
holds; the other subcommands (`add`, `show`, `verify`, `remove`, `env`) arrive with the rest of
slice 2b. Both commands read `~/.carter/config.toml` (`[identity.signing]`), write nothing to it,
and take the three OpenSSH tools from `[identity.signing] ssh_bin_dir` (default `/usr/bin`).

### carter identity unlock

```text
carter identity unlock [--ttl DURATION] [--extend] [--allow-no-passphrase]
```

Starts Carter's own `ssh-agent` if it is not running (socket `$XDG_RUNTIME_DIR/carter/agent.sock`,
else `~/.carter/run/agent.sock`; on macOS `$TMPDIR/carter-<uid>/agent.sock`; directory 0700,
socket 0600) and loads the LLM key into it with `ssh-add -t`. `ssh-add` asks for the key's
passphrase on your terminal; Carter never sees it. Run it in your own terminal, **not** in
OpenCode's: it refuses in any agent shell and anywhere `OPENCODE_TERMINAL` is set (the integrated
terminal included, `E-UNLOCK-OPENCODE`), and without a terminal on stdin and stderr
(`E-UNLOCK-TTY`).

| Option | Meaning |
|--------|---------|
| `--ttl DURATION` | How long the key stays loaded, e.g. `8h` or `30m` (default `[identity.signing] ttl`, `8h`). |
| `--extend` | Ask again and replace the lifetime of a key that is already loaded. |
| `--allow-no-passphrase` | Accept a key without a passphrase. Without the flag such a key is refused (`E-UNLOCK-NOPASS`): any process of yours could sign as the LLM without unlocking. |

A key that is already loaded is not asked for again ("already unlocked"). A wrong passphrase is
`ssh-add`'s own retry; an empty line ends it. If a stale socket or an orphaned agent is left from
a crash, `unlock` replaces it; a path that is not an agent socket is never touched
(`E-UNLOCK-PATH`). With a password manager (`agent_socket` or `program`) it prints that the key is
managed there and does nothing.

### carter identity lock

```text
carter identity lock [--all]
```

Removes only the LLM key from Carter's agent (already absent is a success) and stops the agent
when it is empty. `--all` also stops Carter's agent when other keys are loaded and any leftover
agent that names the same socket directory. Agent commits fail with `E-SIGN-LOCKED` until the next
`unlock`. It refuses in agent shells like `unlock` but needs no terminal, so a logout script can
call it.

## carter github-token

The read-only GitHub token that the `carter-github` MCP server reads (create it as described
in [MCP servers](../guides/mcp-servers.md#the-github-token)). Both commands refuse in an agent
shell and print at most the first four characters of a token in an error.

### carter github-token set

```text
carter github-token set
```

Reads one fine-grained `github_pat_` token from standard input (a hidden prompt on a
terminal, or a pipe) and stores it in `~/.carter/secrets/gh-read.token` (directory 0700, file
0600, written atomically), then records the path under `[github] read_token_file` in
`~/.carter/config.toml`. It takes no arguments, so the token never reaches your shell
history, and it needs a terminal. Classic (`ghp_`), OAuth (`gho_`), user, server and refresh
tokens are refused with `E-PAT-TYPE`.

### carter github-token check

```text
carter github-token check
```

Checks the stored token: the file (0600, yours, not a symlink, outside any repository:
`E-PAT-PERM`), that GitHub accepts it and that it is a fine-grained token, its expiry (a
warning within 14 days) and that it **cannot write**, by asking GitHub to create a branch at
an all-zero commit, which no token can complete, on a repository you own (or `[github]
probe_repo`); its name is never printed. "Resource not accessible" is read-only; any other
answer to a write is red; with no repository of yours visible the probe is skipped (INFO). It makes three requests (`GET /user`, `GET /user/repos`, the
probe) to `$GITHUB_API_URL` (default `https://api.github.com`; plain http only for loopback).
Exit 1 if anything is red. It cannot tell whether the token covers "All repositories"; it prefers a narrow
selection (only the repositories Carter works on) and says so.

## carter push

```text
carter push [--dry-run] [--set-upstream]
```

Pushes `HEAD` to the same-named branch on `origin`, after checks. **Own terminal only**:
it refuses in an agent shell and in any shell without a terminal (including OpenCode's `!`
shell) before running any git command. There are no other options and no arguments: no force,
no tags, no other remote or refspec.

| Option | Description |
|--------|-------------|
| `--dry-run` | Run every check and show what would be pushed and asked; push nothing |
| `-u`, `--set-upstream` | Set `origin/<branch>` as the upstream |

In order: repository and SSH settings that could run code with your credentials are shown
and you decide; the target ref is fetched; the commits, files and hook or CI paths are listed
(those in red); signatures of LLM-committed commits must verify (`E-B-UNSIGNED`); GitHub's
protection for the branch is noted when the read-only token can see it; then it asks `y`
(on the default branch, you type its name). Repository hooks are not run. See
[Write operations](../guides/write-operations.md#pushing-and-pull-requests-the-handoff).

## carter pr

```text
carter pr
```

Opens a pull request from `.carter/state/handoff/<encoded-branch>.md`, the only input it
reads. **Own terminal only**, like `push`. The file's title, branch and body are scanned for
secrets (`E-SECRET-SCAN`) before `gh` is run; `head_sha` must be part of the branch
(`E-HANDOFF`). It shows the title, target, base and the first 40 lines of the body, asks
`y/N`, runs `gh pr create` with your own `gh` login and deletes the file only after the pull
request exists. If the repository is a fork, the target is its parent. If the branch is not on
`origin` at `HEAD`, it runs the `carter push` flow first.

## carter check

```text
carter check [--no-harness] [--host | --probe] [TARGET_DIR]
```

With `--host`, check this machine instead of a workspace (read-only, names only; see
[below](#carter-check---host)). With `--probe`, check that this very agent shell is isolated
(see [below](#carter-check---probe)); `--probe` and `--host` exclude each other.

Validate a workspace. Exits with status 1 and lists the problems if any check fails:
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

### carter check --host

Checks the guards on this machine. It never writes and never prints environment values,
tokens or provider settings. Each line is `OK`, `INFO`, `WARN` or `RED`; the exit code is 1
only if something is `RED`:

- every policy Carter owns is loaded by OpenCode (`E-POLICIES-MISSING` names the missing
  one), your providers are still loaded, and the per-agent denies are still in the config;
- the files recorded in `guard-state.json` match their hashes;
- **first, before any git or OpenCode call:** Carter's included git config parses (a
  malformed one makes every git command fail; the report still completes);
- the git include line is present (or, for a dotfile-managed config, the line to add), and
  git lists the `pre-push` hook as `global`; on git older than 2.54 each repo in scope
  (current directory, workspaces) is `guarded` or `unguarded: <reason>`, a WARN that is a
  FAIL while T2 is configured;
- the plugin directory and `isolation.json` match their recorded hashes and each other (the
  hash baked into the plugin); each OpenCode server's self-test state from
  `~/.carter/run/plugin-status/<pid>.json` (`passed`, `unproven`, `failed`), a server on
  another OpenCode version or older than the plugin file ("restart the server"), and plugin
  files Carter did not write, listed by name;
- the server environment, by name only: agent or human signals, Carter's isolation markers
  and `GH_TOKEN`/`GITHUB_TOKEN` in the OpenCode server's environment;
- every agent's effective `carter_push`/`carter_pr` rule from `opencode debug agents`
  (`RED` names the agent; an agent whose config entry OpenCode dropped gets a hint);
- OpenCode and git version bands (`E-OPENCODE-VERSION`, `E-GIT-OLD`);
- the accepted residual (D67): shell writes outside Carter's own control paths are not gated;
- the read-only GitHub token, if you stored one: its file, type, expiry and that it cannot
  write (the same checks as [`github-token check`](#carter-github-token-check)), and that the
  `carter-github` MCP entry reads the token file;
- declined groups, active `allow_project_opencode_edit` opt-outs, project config that can run
  code, and `carter.yaml` policy that `carter update` has not pinned yet.

Without the plugin the check says "plugin not installed" (never a pass), and shows
"g2 rev 2 pending" when the plugin is waiting for your confirmation.

### carter check --probe

Run it **inside an agent shell** (ask your agent to run it); it refuses elsewhere with
`E-PROBE-SCOPE`. It prints one line per probe, `PASS`, `FAIL` or `SKIP`, then the name, and
exits 1 on any `FAIL`. Nothing else is printed: no environment value, no token and no path
outside `~/.carter`. Probes: `ssh_agent_absent`, `ssh_denied` (offline is `SKIP`),
`gh_pat_only`, `push_refused`, `commit_unsigned`, `agent_tagged`.

## carter gate

### carter gate check

```text
carter gate check [--json] [--cwd DIR] [--skip-groups GROUPS] [COMMAND]
```

Asks the command gate what it would do with COMMAND (or the text on standard input), without
running it. The same code the plugin calls for every agent shell command. Read-only, so it
works anywhere, agent shells included. Exit 0 means allowed, 1 means refused (a message naming
the rule is printed).

| Option | Description |
|--------|-------------|
| `--json` | Print the gate's reply as JSON: `decision`, `rule`, `message` |
| `--cwd DIR` | The directory the command would run in (relative paths and git aliases are resolved there) |
| `--skip-groups GROUPS` | Comma-separated consent groups you declined, as `isolation.json` records them: their rules are skipped |

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
| `has_github_token` | Whether `GITHUB_TOKEN` is set in the environment (the token file is not counted) |

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
