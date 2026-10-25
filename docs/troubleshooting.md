# Troubleshooting

Find your symptom, then apply the fix. If nothing here helps, open an
[issue](https://github.com/mauriciomem/carter-ai/issues).

## Installing

| Symptom | Fix |
|---------|-----|
| `carter: command not found` | `~/.local/bin` isn't on your `PATH`. Run `uv tool update-shell` and open a new terminal, or `export PATH="$HOME/.local/bin:$PATH"` |
| `opencode not found on PATH … Nothing was installed.` | Install OpenCode 2.1+ and check that `opencode --version` works in the same shell |
| `OpenCode 2.0.x is too old` | Upgrade OpenCode to 2.1 or newer |
| `uv tool upgrade` says there is nothing to upgrade | `uv tool install --force git+https://github.com/mauriciomem/carter-ai.git` |
| `⚠ … (user-modified, skipping)` for `AGENTS.md` | You (or another tool) changed `~/.config/opencode/AGENTS.md`, so Carter leaves it alone. Delete or rename it and run `carter install` to get Carter's version |

## Agents

| Symptom | Fix |
|---------|-----|
| Carter agents don't show up | Global agents live in `~/.config/opencode/agents/`, workspace agents in `.opencode/agents/`. In a workspace, run `carter check`: it names any agent OpenCode failed to load |
| I can't select Architect, Engineer, … | They are subagents. Select **carter-maestro** and ask it to use the specialist. See [Using Carter](guides/using-carter.md#pick-maestro) |
| Typing `@carter-engineer` attached nothing useful | In OpenCode, `@` attaches files. Name the agent in plain text instead |
| I see two Maestros | One is global (`carter-maestro`), one is the workspace's (`carter-maestro-local`). Use the `-local` one inside that project |
| An agent ignores my `carter.yaml` change | Run `carter update`, then `carter check` |
| `carter check`: "emitted permissions drifted …" | An agent file was edited by hand. Run `carter update` to regenerate it |
| `carter check` reports agents with different rules right after an edit | OpenCode's background service may still serve the old files. Run `carter check` again |
| A model isn't available | Your provider doesn't offer the pinned model. Change it under `models` in `carter.yaml`. See [Cost and models](guides/cost-and-models.md#change-one-agent-or-the-models-themselves) |

## Permissions

| Symptom | Fix |
|---------|-----|
| A push is denied | Only DevOps may push. Ask Maestro to hand the push to carter-devops |
| Maestro asks before every commit | Expected: Maestro has read-only permissions, so local writes ask |
| A risky command stopped asking | Someone chose "Allow always" at a prompt. Remove the saved allow rule; see [OpenCode permissions](https://opencode.ai/v2/docs/permissions/) |
| An MCP tool asks every time | Expected: MCP tools have no specific rule. Choose "Allow always" for tools you trust |

## MCP servers

| Symptom | Fix |
|---------|-----|
| `⚠ GITHUB_TOKEN` during `carter install --mcp` | The token isn't set. The server is still configured; export the variable in your shell profile and restart OpenCode |
| GitHub or Terraform server fails to start | Both run in Docker. Check that the Docker daemon is running (`docker info`) |
| Duplicate GitHub tools | You have your own `github` server and Carter's `carter-github`. Remove one |
| My `opencode.jsonc` comments disappeared | Carter rewrites the file as JSON. The original is in `opencode.jsonc.carter-backup` next to it |
| Warning that both `opencode.json` and `opencode.jsonc` exist | OpenCode loads both. Carter uses the `.jsonc`; consider merging them into one file |

## Uninstalling

| Symptom | Fix |
|---------|-----|
| `carter uninstall` left files behind | By design. Files you edited are kept and listed as `⚠ Kept …`, and memories, `config.toml` and `audit.log` are never removed. Delete them by hand if you don't need them |
