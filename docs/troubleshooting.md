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
| A push or a `gh` write is denied ("Blocked by configuration policy") | Expected: agents never push or write to GitHub. The work is handed to you |
| Maestro asks before every commit | Expected: Maestro has read-only permissions, so local writes ask |
| A risky command stopped asking | Someone chose "Allow always" at a prompt. Remove the saved allow rule; see [OpenCode permissions](https://opencode.ai/v2/docs/permissions/) |
| An MCP tool asks every time | Expected: MCP tools have no specific rule. Choose "Allow always" for tools you trust |

## MCP servers

| Symptom | Fix |
|---------|-----|
| `⚠ GitHub read-only token not found` during `carter install --mcp` | No token is stored. The server is still configured; run `carter github-token set` in your own terminal, then restart OpenCode |
| GitHub or Terraform server fails to start | Both run in Docker. Check that the Docker daemon is running (`docker info`) |
| Duplicate GitHub tools | You have your own `github` server and Carter's `carter-github`. Remove one |
| My `opencode.jsonc` comments disappeared | Carter rewrites the file as JSON. The original is in `opencode.jsonc.carter-backup` next to it |
| Warning that both `opencode.json` and `opencode.jsonc` exist | OpenCode loads both. Carter uses the `.jsonc`; consider merging them into one file |

## Commit attribution

| Symptom | Fix |
|---------|-----|
| The agent stops and reports `E-CONFIG` | `~/.carter/config.toml` is invalid, or a signing section is incomplete. Agent commits stay off until it is fixed. `carter ops config --emit` shows `commits: refused`. If it is still a schema-1 file, run `carter install` to migrate it |
| The agent reports `E-ROLE-B-TIER` | The role is `author`, which needs a signing key. Set `role: co-author` in `carter.yaml` and run `carter update`, or add the key (not available yet) |
| `carter update` says "Not pinned" | The `identity` policy is only applied after you confirm. Run it in a terminal, or pass `--yes` |
| `carter install` printed a "commit rule" note | Your global `AGENTS.md` has your edits, so Carter left it alone. Merge the rule from `~/.carter/upgrade-notes/<version>.md` |
| A warning about `identity.git_account` or `identity.bot_name` | Both are deprecated and ignored. Delete them from `.carter/carter.yaml` |

## Guards

| Symptom | Fix |
|---------|-----|
| `carter install` says the guards were skipped | No terminal and no `--yes`. Run `carter guard install` in a terminal |
| `Error: E-HUMAN-TERMINAL` | The command runs only in your own terminal, not through an agent. If you are not an agent, this shell inherited agent variables: start the terminal fresh |
| `Error: E-POLICIES-MISSING: … not loaded` | OpenCode dropped a policy (a broken config drops all of them and your providers). `carter guard install` already restored your config from the backup; check the file with `opencode debug config`, then try again |
| After a guard write OpenCode lost a provider | The write is rolled back automatically. If it ever isn't, restore `~/.carter/backups/<timestamp>/opencode.json[c]` over your config |
| `carter guard status` or `check --host` says `MISSING` for a policy | Re-run `carter guard install`; if it keeps failing, `carter guard install --print-policies` and paste the block yourself |
| `Error: E-STATE-INVALID` | `~/.carter/guard-state.json` is unreadable or from a newer Carter. Carter never rebuilds it: fix or move the file, then run `carter guard install` |
| Every git command fails with "bad config line … gitconfig" | Carter's included git file is malformed. `carter guard remove` unsets the include line without needing git to work; this release writes no such file |
| My `opencode.jsonc` comments disappeared after the guards | Carter rewrote the file as JSON. The original is `opencode.jsonc.carter-backup`; use `--print-policies` to paste by hand next time |
| `Error: E-HANDOFF` from `carter pr` | There is no valid `.carter/state/handoff/<encoded-branch>.md` for the current branch (the error names the expected path and the bad key, never a value), or its `head_sha` is not part of the branch. Ask the agent to rewrite it, or check out the branch it was written for |
| `Error: E-SECRET-SCAN` from `carter pr` | The title, branch or body matches a credential pattern (the error names the rule, not the text). Nothing was sent and the file is kept: edit it and run `carter pr` again |
| `Error: E-B-UNSIGNED` from `carter push` | A commit whose committer is the LLM has no valid LLM signature. Nothing was pushed. Re-create the commit as your own (for example by squashing), or fix the LLM signing setup |
| `Error: E-APLUS-ARGS` from `carter push` | Detached HEAD, no `origin`, a non-fast-forward branch, or an extra argument. `carter push` takes no arguments or force option: check out the branch, fetch and rebase |
| `carter push` lists settings in red and asks to continue | A repository, git or SSH setting could run code with your credentials (a credential helper, `core.sshCommand`, a hook file, a `ProxyCommand`). Read the names, remove what you did not expect, and answer `y` only if you did put them there |
| `Error: E-PAT-TYPE` from `carter github-token set` | Only fine-grained `github_pat_` tokens are accepted. The error shows at most the first four characters of what you gave it. Create a fine-grained, read-only token |
| `Error: E-PAT-PERM` | The token file or its folder is not mode 0600/0700, not yours, a symlink, or inside a git repository. Fix it, or run `carter github-token set` again |
| `carter github-token check` says the token is WRITABLE | GitHub accepted a write attempt: the token has a Write permission. Revoke it and create a read-only one |
| `carter pr` fails with HTTP 403 | `gh` is using an exported `GH_TOKEN` or `GITHUB_TOKEN` (read-only) instead of your login. Unset it for that shell |

## Uninstalling

| Symptom | Fix |
|---------|-----|
| `carter uninstall` kept my policies | Without a terminal and without `--yes` the guards are kept; run `carter guard remove`, or `carter uninstall --yes` |
| `carter uninstall` left files behind | By design. Files you edited are kept (those edited since the last install are listed as `⚠ Kept …`), and memories, `config.toml` and `audit.log` are never removed. Delete them by hand if you don't need them |
