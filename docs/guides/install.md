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

After the agents are installed, `carter install` offers the policy guards (the same as
running `carter guard install`). In a terminal it asks about each group, with a one-line
effect:

| Group | What it does |
|-------|--------------|
| `g2` | Agents can't push or write to GitHub from their shell; `gh` is read-only; per-agent denies for the push and PR tools. |
| `sudo-docker` | Agents can't run `sudo` or `docker`; Packer docker builds must be typed in your terminal. |
| `read-edit-denies` | Agents can't read SSH keys, `gh`/git credentials or the read-only token, and can't edit `~/.ssh`. |
| `config-edit` | Agents can't edit OpenCode config, git hooks and config, or Carter's own config and control files. |

Nothing is written without your yes. With no terminal (CI, a script) and without `--yes`,
the agents and skills are installed as before and the guards are skipped with a notice;
`carter install --yes` accepts every group. Declined groups are remembered and listed by
`carter guard status` and `carter check --host` as residuals.

The policies go into your OpenCode config in one atomic write. Carter keeps a backup,
asks OpenCode for the resolved config before and after, and restores the backup if a
provider or a statement was lost. Preview with `carter guard install --dry-run`. If the
config has comments, rewriting drops them: the original is kept as `<name>.carter-backup`,
or use `--print-policies` and paste the block yourself. **Restart the OpenCode server** (or
OpenCode) after the policies change so it reloads its config.

**What this is, in this release:** the policies are literal command matches, a speed bump
and not a boundary. The plugin and the shell isolation that would make them one are not
installed yet, agent shells still inherit your SSH agent and `gh` login, the read-only
GitHub token (`carter github-token set`) is stored but not injected into agent shells, and
agent commits still use your own git config. `carter check --host` says "plugin not installed" for as long
as that is true.

Remove them with `carter guard remove` (or `carter uninstall`). Only what Carter wrote and
you have not changed is removed; the read-only token file and `~/.carter/state/audit/` stay.
`carter uninstall --keep-guards` leaves the guards in place.

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
- **Kept:** `~/.carter/memories/`, `config.toml`, `audit.log`, backups, and any file
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
