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
| `--bot-name NAME` | Name credited as co-author on commits (default `carter-bot`). First install only; see [Write operations](write-operations.md#setup) |
| `-q` / `-v` / `--debug` | Less or more output |

The full list is in the [CLI reference](../reference/cli.md#carter-install).

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
knowledge files, `~/.carter/config.toml`, or an `AGENTS.md` you edited. Skills that
Carter no longer ships are removed unless you changed them.

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
