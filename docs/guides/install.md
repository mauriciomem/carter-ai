# Install Carter

This page covers installing Carter, keeping it up to date and removing it.

## What you need

| Requirement | Check with |
|-------------|-----------|
| Python 3.11 or newer | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) | `uv --version` |
| [OpenCode](https://opencode.ai/v2/docs/) 2.1 or newer, on your `PATH` | `opencode --version` |
| Git | `git --version` |

Optional:

- The GitHub CLI `gh`, used by the [write operations](write-operations.md) flow.
- Docker, if you want the GitHub or Terraform [MCP servers](mcp-servers.md).

## 1. Install the `carter` command

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git
carter --version
```

uv puts the `carter` executable in `~/.local/bin`. If your shell can't find it,
add that directory to your `PATH` once:

```bash
uv tool update-shell   # updates your shell startup file
exec $SHELL            # reload, or open a new terminal
```

## 2. Install the agents into OpenCode

```bash
carter install
```

This checks that OpenCode 2.1+ is on your `PATH`, then writes:

| What | Where |
|------|-------|
| 8 agents | `~/.config/opencode/agents/carter-*.md` |
| 27 skills | `~/.config/opencode/skills/carter-*/` |
| Global rules for every session | `~/.config/opencode/AGENTS.md` |
| Knowledge files, memory folders, settings | `~/.carter/` |

If OpenCode is missing or too old, nothing is written:

```text
Error: opencode not found on PATH. Install or upgrade OpenCode (>= 2.1): https://opencode.ai/v2/docs/ Nothing was installed.
```

Useful options:

| Option | Effect |
|--------|--------|
| `--mcp` | Also configure the MCP servers. See [MCP servers](mcp-servers.md) |
| `--mcp-servers github,terraform` | Only these MCP servers (with `--mcp`) |
| `-y`, `--yes` | Also install the policy guards without asking |
| `--bot-name NAME` | Deprecated and ignored (prints a warning). See [Attribution](write-operations.md#attribution) |
| `-q` / `-v` / `--debug` | Less or more output |

The full list is in the [CLI reference](../reference/cli.md#carter-install).

## Guards

After the agents are installed, `carter install` offers the guards (the same as running
`carter guard install`). In a terminal it asks about each group, with a one-line effect:

| Group | What it does |
|-------|--------------|
| `g2` | Agents can't push or write to GitHub from their shell; `gh` is read-only; per-agent denies for the push and PR tools. At revision 2 it also installs the Carter **plugin**: every agent shell is isolated and a command **gate** screens each command (see below). |
| `hooks` | Pushes by agent shells are blocked, and at revision 2 agent commits are checked (committer, signing settings, `Co-authored-by`/`Assisted-by` trailer) in every repo on this machine: git `pre-push`, `prepare-commit-msg`, `commit-msg` and `post-commit` hooks calling `~/.carter/hooks/carter-guard`, pulled in by one `include.path` line. Your own commits and pushes are unaffected and run no extra command. Needs git 2.54 or newer. A revision-1 install keeps only `pre-push` until you confirm revision 2 (`carter guard install` in a terminal). |
| `sudo-docker` | Agents can't run `sudo` or `docker`; Packer docker builds must be typed in your terminal. |
| `read-edit-denies` | Agents can't read SSH keys, `gh`/git credentials or the read-only token, and can't edit `~/.ssh`. |
| `config-edit` | Agents can't edit OpenCode config, git hooks and config, or Carter's own config and control files. |
| `alias` | **Optional.** Adds the git alias `git ai-commit` (`carter commit`) to Carter's git config, unless you already have an `alias.ai-commit`. A bare `--yes` never installs it: use `carter guard install --only alias` or answer yes in a terminal. |
| `repo_hooks` | Git older than 2.54 only: the same push guard as a `pre-push` hook file in your repos (the current one and your workspaces), and in `init.templateDir` if you have none. A hook or `core.hooksPath` you or your tools own (husky, pre-commit) is never edited: Carter reports the repo as unguarded and prints a line to chain. Asked with Enter = yes. |

Nothing is written without your yes. With no terminal (CI, a script) and without `--yes`,
the agents and skills are installed as before and the guards are skipped with a notice;
`carter install --yes` accepts every group on a fresh machine. Declined groups are remembered
and listed by `carter guard status` and `carter check --host` as residuals.

The policies go into your OpenCode config in one atomic write. Carter keeps a backup,
asks OpenCode for the resolved config before and after, and restores the backup if a
provider or a statement was lost. Preview with `carter guard install --dry-run` (it lists
every file it would write and writes nothing). If the config has comments, rewriting drops
them: the original is kept as `<name>.carter-backup`, or use `--print-policies` and paste the
block yourself.

### The plugin (`g2`, revision 2)

The policies alone are literal command matches: a speed bump, not a boundary. The plugin
makes them one. It is installed as `~/.config/opencode/plugins/carter/` (OpenCode finds it
there; nothing is registered in your config), with `~/.carter/isolation.json` and
`~/.carter/run/`.

**It changes every agent shell, so an existing install is never upgraded silently.** If you
had the guards before the plugin existed (`g2` at revision 1), `carter install --yes`,
`carter guard install --yes` and any run without a terminal print "plugin and isolation need
your confirmation" and change nothing. Only a yes in your own terminal, or
`carter guard install --yes --only g2`, confirms. The question comes with this explanation:
what changes in agent shells, what does not (your own terminal and the `!` shell are not touched), where it is
recorded, how to undo it, and that the OpenCode server must be restarted. A no is remembered
and not asked again; `carter guard install --only g2` reconsiders.

**Restart the OpenCode server from a clean terminal** afterwards (a terminal that an agent
did not start and that has no agent variables), so that it loads the plugin and its
environment is clean. The first agent command then runs a short self-test; until it passes,
`carter check --host` shows the plugin as `unproven`.

What changes in an agent's shell (no SSH agent, a read-only token, no push, unsigned commits):

| | Before the plugin | With the plugin |
|---|---|---|
| SSH agent | Inherited: agents can use your SSH keys | None. `git fetch`/`pull`/`clone` go over HTTPS with the read-only token, which works for public repositories and for repositories that token covers only |
| GitHub CLI | Your `gh` login | The read-only token only: reads work, `gh api` and writes do not |
| Pushing | Denied by literal matches (`git push`) | Also denied in any spelling (`git -C . push`, `sh -c`, aliases, interpreters) and by `no_push` |
| Commits | Your git config (signed if it signs) | Your name and email, **unsigned**, with the `Assisted-by` trailer |
| Commands | Literal deny lists | A gate rejects the rejected forms with a message that names a rule |
| Your terminal and `!` | Untouched | Untouched |

A broken gate, plugin or `isolation.json` refuses every **agent** shell (fail closed) and
never your terminal.

If your global git config is a symlink or read-only (dotfiles, Nix), Carter does not write
it. It prints the exact line, for example:

```text
git config --global --add include.path /home/you/.carter/gitconfig
```

Add that one line to your dotfiles' git config yourself; until you do, the `pre-push` hook is
inactive and `carter check --host` says so. `carter guard remove` prints the matching
`--unset-all` line.

Check it with `carter check --host` (read-only, in your terminal) and, to see that a shell is
really isolated, ask an agent to run `carter check --probe`.

### Undo

- `carter guard remove --only plugin` removes only the plugin, `isolation.json` and `run/`.
  The policies, hooks and token stay, and a bare `--yes` never brings the plugin back.
- `carter guard remove` (or `carter uninstall`) removes everything Carter wrote and you have
  not changed; the read-only token file and `~/.carter/state/audit/` stay.
  `carter uninstall --keep-guards` leaves the guards in place.
- If `carter` itself is broken: `rm -r ~/.config/opencode/plugins/carter` (a running
  OpenCode drops the plugin within seconds), and `rm ~/.carter/gitconfig` if git misbehaves.

What the guards still cannot do is in [Safety and permissions](safety-and-permissions.md#what-the-guards-cannot-do).

## 3. Check it worked

Start `opencode`, press `Shift+Tab` until **carter-maestro** is selected, and ask it
something. Then continue with [Using Carter](using-carter.md).

## Upgrade

```bash
uv tool upgrade carter-ai
carter install
```

If uv says there is nothing to upgrade, force a reinstall from the latest commit:

```bash
uv tool install --force git+https://github.com/mauriciomem/carter-ai.git
```

Re-running `carter install` is safe. It updates the agents and skills, copies any
file it replaces to `~/.carter/backups/<timestamp>/`, and never overwrites your
knowledge files or an `AGENTS.md` you edited. Skills that Carter no longer ships are
removed unless you changed them.

`~/.carter/config.toml` is created on a first install. An older (schema 1) file is
migrated once to schema 2, explicitly and only by `carter install`: the original is copied
to `~/.carter/config.toml.schema1.bak` first and never overwritten, your footer is kept,
and the old `[git] signing_key` and a `carter-bot@` email are dropped. If the file can't
be migrated (for example, invalid TOML), install says so and leaves it untouched.

Carter never uses your signing key: it doesn't read `user.signingkey` or your SSH keys.

If your global `~/.config/opencode/AGENTS.md` has your own edits, `carter install` can't
update its commit rule. It prints the new rule and saves it to
`~/.carter/upgrade-notes/<version>.md`; merge it by hand.

If you use workspaces, run `carter update` in each one afterwards to pick up the new
templates.

### Install a specific version

Pin a release tag for a reproducible setup:

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git@v0.16.0
```

Tags are listed on the [releases page](https://github.com/mauriciomem/carter-ai/releases).

## Uninstall

```bash
carter uninstall
uv tool uninstall carter-ai   # removes the carter command itself
```

`carter uninstall` removes only what Carter installed and you have not changed:

- **Removed:** the `carter-*` agents and skills, the global `AGENTS.md` Carter wrote,
  untouched knowledge files, the `carter-*` MCP servers in `opencode.json` and
  `opencode.jsonc`, and `~/.carter/manifest.json`.
- **Also removed, in your terminal (or with `--yes`):** the guards (`carter guard remove`) and the
  LLM identity files (the signing shim, `allowed_signers`, the tier
  mirror and the identity part of `config.toml`, with a backup). Each only if unchanged. The two
  are independent; without a terminal and without `--yes` both are kept.
- **Kept:** `~/.carter/memories/`, the rest of `config.toml`, `audit.log`, backups, and any file
  you edited. Files edited since the last install are reported:

```text
  ⚠ Kept ~/.carter/knowledge/mistakes.md: edited since install
```

Knowledge files you had already edited before a re-install are kept without a
message. Delete any of these by hand if you don't need them. Workspaces created with `carter init`
are never touched; remove their `.carter/`, `.opencode/agents/carter-*` and
`AGENTS.md` yourself.

## Next

- [Using Carter](using-carter.md)
- [Your first workspace](first-workspace.md)
- [Troubleshooting](../troubleshooting.md)
