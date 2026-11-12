# Install Carter

This page covers installing Carter, the guards, keeping Carter up to date and removing it.

## What you need

| Requirement | Check with |
|-------------|-----------|
| Python 3.11 or newer | `python3 --version` |
| [uv](https://docs.astral.sh/uv/) | `uv --version` |
| [OpenCode](https://opencode.ai/v2/docs/) 2.1 or newer, on your `PATH` | `opencode --version` |
| Git (2.54 or newer for the global hooks; see [Guards](#guards)) | `git --version` |

Optional:

- The GitHub CLI `gh`, which agents use to open pull requests.
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

| Option | Effect |
|--------|--------|
| `--mcp` | Also configure the MCP servers. See [MCP servers](mcp-servers.md) |
| `--mcp-servers github,terraform` | Only these MCP servers (with `--mcp`) |
| `-y`, `--yes` | Install the guards without asking |
| `-q` / `-v` / `--debug` | Less or more output |

The full list is in the [CLI reference](../reference/cli.md#carter-install).

## Guards

Right after the agents, `carter install` offers the guards. It is the same as running
`carter guard install` yourself. In a terminal it asks **one** question, `Install? [Y/n]`,
under a summary of three or four lines. Your yes covers every group below; Enter is yes. A Carter
upgrade that adds guard content is asked again in this same question, never separately.
Without a terminal (a script, CI) and without `--yes`, the guards are skipped with a notice;
`carter install --yes` installs them without asking.

| Group | What it does |
|-------|--------------|
| `g2` | Carter agents can't push from their shell, and `gh` can read and open, edit or comment on pull requests, nothing else. It also installs the Carter **plugin** (below), and `carter_push` for the devops agent ([Write operations](write-operations.md#letting-devops-ask-you-to-push)). |
| `hooks` | Git hooks (`pre-push`, `prepare-commit-msg`, `commit-msg`, `post-commit`) that call `~/.carter/hooks/carter-guard`: pushes from Carter agent shells are blocked, and agent commits are checked (committer, signing settings, `Co-authored-by`/`Assisted-by` trailer). Your own commits and pushes are unaffected and run no extra command. Needs git 2.54 or newer. |
| `repo_hooks` | Git older than 2.54 only: the same hooks as files in your repositories. A hook or `core.hooksPath` that you or your tools own (husky, pre-commit) is never edited: Carter reports the repository as unguarded and prints a line to chain. |
| `sudo-docker` | Agents can't run `sudo` or `docker`. Packer docker builds must be typed in your terminal. |
| `read-edit-denies` | Agents can't read SSH keys, `gh`/git credentials or the GitHub token, and can't edit `~/.ssh`. |
| `config-edit` | Agents can't edit OpenCode config, git hooks and config, or Carter's own config and control files. |
| `alias` | **Optional.** Adds the git alias `git ai-commit` (`carter commit`), unless you already have an `alias.ai-commit`. Never part of the one question or of `--yes`: use `carter guard install --only alias`. |

A group you decline stays declined. `carter guard status` and `carter check --host` list it, with
the command that asks again (`carter guard install --only <group>`). The one exception: with the LLM
signing on and no commit hooks installed, the single question offers a declined
`hooks` again and says so in one line.
Preview everything with `carter guard install --dry-run`: it lists every file it would write
and writes nothing.

### Scope: only Carter agents and Carter workspaces

The guards bind **Carter's agents** (`carter-*` and the subagents they start) and shells opened in
a **Carter workspace** (a directory with `.carter/carter.yaml` and `.opencode/agents/carter-*.md`).
Another agent, such as OpenCode's `build` or `plan`, outside a Carter workspace is left alone: no
gate, no isolation, and Carter's hooks don't stop its `git push`. Use a Carter agent for anything
you want guarded.

The deny rules (push, `gh` writes, `sudo`/`docker`, reads of credentials, edits of OpenCode, git
and Carter config) are written into each Carter agent's own `permissions:` in
`~/.config/opencode/agents/carter-*.md`, and into your workspace agents by `carter update`. Carter
writes no global OpenCode policies. The one write in your OpenCode config is a `carter_push` deny
for OpenCode's own agents, which only hides Carter's tool from them. Carter backs up that file first,
asks OpenCode for the resolved config before and after, and restores the backup if a provider was
lost. If the file has comments, rewriting drops them; the original is kept as
`<name>.carter-backup`.

### The plugin

Deny rules are literal command matches. The plugin makes them a boundary. It lives in
`~/.config/opencode/plugins/carter/` (OpenCode finds it there; nothing is registered in your config),
with `~/.carter/isolation.json` and `~/.carter/run/`. In every Carter agent shell it applies an
isolation block, and a command **gate** screens each command and refuses the forms a literal match
misses (`git -C . push`, `sh -c "git push"`, aliases, `gh api`).

| In a Carter agent shell | |
|---|---|
| SSH agent | None. `git fetch`/`pull`/`clone` go over HTTPS with the read-only GitHub token, which works for public repositories and for repositories that token covers only |
| GitHub CLI | The token only: reads, and `gh pr create\|edit\|comment` if the token has `Pull requests: write`. `gh api`, merges and pushes are refused |
| Pushing | Refused in any spelling, and again by the `pre-push` hook |
| Commits | Your name and email, **unsigned** unless LLM signing is on, signed by the LLM identity when it is ([Identity and signing](identity-and-signing.md)) |
| Commands | The gate refuses with a message that names the rule |
| Your terminal and OpenCode's `!` shell | Untouched |

A broken gate, plugin or `isolation.json` refuses every **agent** shell (fail closed) and never your
terminal.

**Restart the OpenCode server from a clean terminal** after the install (one that no agent started),
so it loads the plugin with a clean environment. The first agent command then runs a short
check of the plugin; until it has run, `carter check --host` says the server is waiting for the
first agent command.

If your global git config is a symlink or read-only (dotfiles, Nix), Carter doesn't write it. It
prints the exact line instead:

```text
git config --global --add include.path /home/you/.carter/gitconfig
```

Add that one line to your dotfiles' git config yourself. Until you do, the `pre-push` hook is
inactive and `carter check --host` says so.

Check it with `carter check --host` (read-only, in your terminal). To see that a shell really is
isolated, ask an agent to run `carter check --probe`.

### Undo

- `carter guard remove --only plugin` removes only the plugin, `isolation.json` and `run/`. The deny
  rules, hooks and token stay.
- `carter guard remove --only broker` removes only `carter_push`.
- `carter guard remove` (or `carter uninstall`) removes everything Carter wrote and you haven't
  changed. The read-only token file and `~/.carter/state/audit/` stay. `carter uninstall --keep-guards`
  leaves the guards in place.
- If `carter` itself is broken: `rm -r ~/.config/opencode/plugins/carter` (a running OpenCode drops the
  plugin within seconds), and `rm ~/.carter/gitconfig` if git misbehaves.

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

Re-running `carter install` is safe. It updates the agents and skills, copies a file you edited
before replacing it (at its own path under `~/.carter/backups/<timestamp>/`; Carter's own previous
output is not copied), deletes backup directories older than 15 days, and never overwrites your
knowledge files or an `AGENTS.md` you edited. Skills that Carter no longer ships are removed unless you changed them. If your global
`AGENTS.md` has your edits, `carter install` says it is user-modified and leaves it alone.

`~/.carter/config.toml` is created on a first install and never rewritten by `install`. A key Carter
doesn't read is reported once with its file, for example
``⚠ unknown key `x.y` in /home/you/.carter/config.toml → delete it``. Delete it yourself.

Carter never uses your signing key: it doesn't read `user.signingkey` or your SSH keys.

In each workspace, run `carter update` to pick up the new templates.

### Install a specific version

```bash
uv tool install git+https://github.com/mauriciomem/carter-ai.git@v0.18.0
```

Tags are listed on the [releases page](https://github.com/mauriciomem/carter-ai/releases).

## Uninstall

```bash
carter uninstall
uv tool uninstall carter-ai   # removes the carter command itself
```

`carter uninstall` asks nothing and removes only what Carter installed and you haven't changed:

- **Removed:** the `carter-*` agents (one you edited too, after a copy to
  `~/.carter/backups/<timestamp>/`) and skills, the global `AGENTS.md` Carter wrote, untouched
  knowledge files, the MCP servers Carter ships (`carter-github`, `carter-terraform`, `carter-atlassian`) in
  `opencode.json` and `opencode.jsonc`, the guards
  (`carter guard remove`), the LLM identity files (the signing shim, `allowed_signers`, the tier
  mirror, the identity part of `config.toml`, with a backup) and `~/.carter/manifest.json`.
- **Kept:** `~/.carter/memories/`, a `config.toml` where you set anything, the audit log, the GitHub
  token file, backups, and any skill, rule or knowledge file you edited. Files edited since the last install are reported:

```text
  ⚠ Kept ~/.carter/knowledge/mistakes.md: edited since install
```

Workspaces created with `carter init` are never touched. `uninstall` lists the ones it knows
(recorded by `carter init` and `carter update`) with the `rm` line for their
`.opencode/agents/carter-*.md`; run it yourself, and remove `.carter/` and `AGENTS.md` too if you
want them gone.

## Next

- [Using Carter](using-carter.md)
- [Your first workspace](first-workspace.md)
- [Troubleshooting](../troubleshooting.md)
