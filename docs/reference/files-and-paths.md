# Files and paths

Everything Carter writes, where it lives, and what happens to it on update and
uninstall.

## Global install (`carter install`)

| Path | Contents | Re-install | Uninstall |
|------|----------|------------|-----------|
| `~/.config/opencode/agents/carter-*.md` | The 8 agents, with G2's deny rules in their `permissions:` once the guards are installed | Updated (old copy backed up) | Removed; with an install record an edited one is copied to `~/.carter/backups/<timestamp>/` first and reported (the guard rules in it go away with the guards). Without a record, an edited one is kept and listed |
| `~/.config/opencode/skills/carter-*/` | The 27 skills | Updated (old copy backed up) | Removed unless edited |
| `~/.config/opencode/AGENTS.md` | Global rules loaded in every session | Updated if it is the version Carter recorded and you did not edit it; left alone ("user-modified") if you changed it | Removed unless edited |
| `~/.config/opencode/opencode.json` or `.jsonc` | `carter-*` MCP servers (with `--mcp`) | Servers replaced | `carter-*` servers removed; the file too if nothing else is left in it |
| `~/.config/opencode/opencode.jsonc.carter-backup` | Copy of a config file that had comments | Overwritten | Kept |
| `~/.carter/knowledge/` | 6 global knowledge files | Never overwritten | Removed only if unchanged |
| `~/.carter/memories/{user,repo,session}/` | Raw notes | Kept | Kept |
| `~/.carter/config.toml` | Settings: LLM identity, footer, per-workspace policy | Created if missing; otherwise left alone (a key Carter doesn't read is named with its file) | Removed if it is exactly what `install` wrote (two lines under a header); kept, and listed, if it has any value or comment of yours |
| `<repo>/.github/workflows/carter-review.yml` | The review-only workflow, written by `carter ci install review` in the repository you run it in (first line: a hash of the rest, so an edited file is never overwritten) | Refreshed if unedited | Never removed by Carter (it is your repository's file) |
| `~/.carter/state/audit/audit.log` | Log of `ops:` operations and policy exceptions  | Kept | Kept |
| `~/.carter/state/audit/b.jsonl` (dir 0700, file 0600) | One line per decision of [`carter_push`](../guides/write-operations.md#letting-devops-ask-you-to-push): time, agent, session, repo, branch, range, commit count, decision, code, dwell. Never an environment, a credentialed URL or a title. Rotates at 5 MiB (three older files kept) | Appended by `carter_push` | Kept |
| `~/.carter/backups/<timestamp>/` (UTC) | Copies of files an install replaced that were not Carter's own last output (your edits, files Carter never wrote). Each sits at its own path under the directory (a file from `~/.config/opencode/skills/x/SKILL.md` is at `.config/opencode/skills/x/SKILL.md`), so same-named files never overwrite each other. Each run makes a new `<timestamp>` directory (0700; copies 0600), never one that already exists, and never copies through a symlink. `carter install` deletes `<timestamp>` directories older than 15 days; move a copy out if you want to keep it. Restore with `cp`. The copies `identity add|remove` make of `config.toml` sit directly in the directory (`<timestamp>/config.toml`), not under a mirrored path. Agents cannot write here | Added to; pruned by `install` | Kept |
| `~/.carter/manifest.json` | What Carter installed, with checksums. `uninstall` deletes only listed files that Carter ships by name. Agents cannot write it | Rewritten | Removed |
| `~/.carter/workspaces` (0600) | One absolute path per line: the workspaces where you ran `carter init` or `carter update`. `uninstall` reads it (at most 64 KiB, a regular file only) to tell you where Carter files are left, and lists only directories you own. Agents cannot write it | Appended once per path by `init` and `update` | Removed (after being listed) |
| `~/.carter/guard-state.json` (0600) | What `carter guard install` owns: consents, statements, per-agent denies, file hashes. Separate from `manifest.json` so an older installer can't drop it | Updated in place, never rebuilt; unchanged content is not rewritten | Removed by `guard remove` / `uninstall` (kept with `--keep-guards`) |
| `~/.config/opencode/opencode.json` or `.jsonc` → `agents` | The per-agent `carter_push` denies for OpenCode's own agents (Carter writes no global `policies`) | Converged; your own entries are kept | Removed only where unchanged |
| `~/.carter/backups/<timestamp>/opencode.json[c]` (0600) | Copy of your OpenCode config before a guard write | Added to | Kept |
| `~/.carter/gitconfig` and `gitconfig.d/` | Carter's own git keys behind one `include.path` line in your global git config: the hook entries for `pre-push`, `prepare-commit-msg`, `commit-msg` and `post-commit` (`hook.carter-guard-<event>.*`), the optional `alias.ai-commit`, or `init.templateDir` on git older than 2.54. If your global config is a symlink or read-only, Carter prints the line instead of writing it | Rewritten if unchanged; an edited file is kept and reported | Removed only if unchanged |
| `~/.carter/hooks/carter-guard` (0755) | The POSIX guard script behind the `pre-push` hook. Blocks only agent shells; a missing script never blocks you | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/hooks/template/` | `init.templateDir` content for new clones (git older than 2.54 only) | Rewritten if unchanged | Removed only if unchanged |
| `<repo>/.git/hooks/pre-push`, `prepare-commit-msg`, `commit-msg`, `post-commit` | Per-repo hooks, only on git older than 2.54 and only where that event had none (each event is judged on its own). Recorded with their hashes | Kept | Removed only if unchanged |
| `~/.config/opencode/plugins/carter/index.ts`, `core.ts`, `broker.ts` | The Carter plugin. OpenCode discovers it from this folder (nothing is registered). `index.ts` is rendered with the hash of `isolation.json` | Rewritten if unchanged; an edited file is kept and agent shells are refused until you restore it | Removed only if unchanged |
| `~/.carter/isolation.json` (0600) | The shell-isolation block the plugin applies to agent shells (variables, git config, the paths of Python and `carter`, the declined groups). The plugin refuses to start an agent shell if it changes | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/run/b-rejections.json` (0600) and `b-*.lock` | The `carter_push` rejection counters per session family, and one lock per repository during a push | Written by `carter_push`; cleared by `carter guard status --reset-b` | Removed with `run/` |
| `~/.carter/opencode-headless.json` | The profile that denies `carter_push` to devops for `OPENCODE_CONFIG=` with `opencode run --standalone` (present while `carter_push` is on) | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/run/` (0700), `run/gh-empty/` (0700, empty), `run/plugin-status/<pid>.json` | The empty `gh` config folder agents get, and one status file per OpenCode server process (the plugin's check state, versions, flag names, never values). `carter check --host` reads them | Created; status files rewritten by the plugin | `run/` is removed whole |
| `~/.carter/secrets/gh-read.token` (0600, in a 0700 directory) | The read-only GitHub token, written by `carter github-token set`; read by the `carter-github` MCP entry, `github-token check`, `check --host` and `carter push` | Replaced atomically by `set`; never touched by guards | Kept, with a reminder to delete and revoke it |
| `~/.carter/bin/carter-ssh-sign` (0755) | The signing shim git calls as `gpg.ssh.program`: it signs only with the LLM key through Carter's agent. Recorded with its hash; the plugin refuses to sign if it changes | Rewritten by `identity add` | Removed by `identity remove` only if unchanged |
| `~/.carter/hooks/allowed_signers` (0600, folder 0700) | The LLM's public keys (current and `previous_public_keys`) for `identity verify` and the `post-commit` check | Rewritten by `identity add` | Removed by `identity remove` only if unchanged |
| `~/.carter/gitconfig` (hook tier) and `gitconfig.d/<hash>` | `carter.tier`, `carter.llmEmail`, `carter.llmFingerprint` and one `includeIf "gitdir:"` fragment per workspace with a `max_tier`: how the git hooks learn the tier. The user's own git config is never written for this | Rewritten by `identity add` and `carter update` | The mirror is removed by `identity remove`; the hook entries stay until `guard remove` |
| `~/.carter/run/agent.sock`, `agent.pid`, `unlock.lock` (or `$XDG_RUNTIME_DIR/carter/agent.sock`; on macOS `$TMPDIR/carter-<uid>/`) | Carter's dedicated `ssh-agent` while a key is unlocked | Created by `identity unlock` | Removed by `identity lock --all` / `identity remove` |
| `~/.carter/run/coauthor-link.json` (0600) | Role `author`: whether GitHub knows your `user.email`, one row per address as a **hash** (`noreply` or `verified`, with the time; never the address). Valid for 7 days | Written by `identity add` and `check --host` in your own terminal only | Removed with `run/` |
| `~/.carter/state/audit/guard.log` (0600) | One line per `post-commit` warning (a commit that is unsigned or not signed by the LLM key). Never read by Carter; agents can read it but not edit it. A hook installed by an older Carter keeps writing to `run/guard.log` until the next `carter guard install`; `uninstall` moves that file here | Appended by the hook | Kept |
| `~/.carter/state/audit/` | Audit store | Kept | Kept |

Uninstall uses the checksums in the manifest to decide whether you edited a file.
Anything you changed is kept and listed under `Kept, because they are yours`
(`carter uninstall -v` also prints a `Kept <path>: edited since install` line for each).

## Workspace (`carter init`)

| Path | Contents | `carter update` |
|------|----------|-----------------|
| `.opencode/agents/carter-*-local.md` | The workspace agents | Always rewritten |
| `AGENTS.md` | Project rules for OpenCode | Created only if missing |
| `.carter/carter.yaml` | Workspace settings | Read, never written |
| `.carter/knowledge/` | 5 project knowledge files | Never touched |
| `.carter/state/plans/active/`, `completed/` | Plans | Never touched |
| `.carter/state/sessions/checkpoint.md` | Session checkpoint | Never touched |
| `.carter/.git/` | Private history of `.carter/` (`carter save`) | Never touched |
| `.gitignore` | Gets a `.carter/` line with `--single` | Never touched |

`carter uninstall` never touches workspaces. It lists the ones recorded in `~/.carter/workspaces`
(plus any pinned in `config.toml`) under `Workspaces, not touched`, and for each one prints the `rm`
line, with absolute shell-quoted paths, for its
`.opencode/agents/carter-*.md`; run it yourself. `AGENTS.md`, `.carter/` and
`.github/workflows/carter-review.yml` are named as yours to delete, never as a command: they may hold
your edits or be committed. `AGENTS.md` is named only if it starts with the line Carter writes
(`<!-- Carter writes this file once and does not overwrite it. -->`). A workspace where you have not run `init` or `update` since this record
existed is not listed; find it with
`find ~ -path '*/.opencode/agents/carter-*-local.md' -not -path '*/node_modules/*'` (`-local` is the
default agent suffix; use yours if you set another).

## Written into your repository by agents

| Path | Written by |
|------|-----------|
| `docs/adr/` | The `carter-adr` skill (decision records) |
| `docs/rfcs/` | The `carter-rfc` skill (design proposals) |

## Environment variables

| Variable | Used by |
|----------|---------|
| `GITHUB_TOKEN` | Not used by Carter's MCP server (it reads `~/.carter/secrets/gh-read.token`). `carter ops config --emit` only reports whether it is set |
| `TFE_TOKEN` | The `carter-terraform` MCP server |
| `TFE_ADDRESS` | Optional, for Terraform Enterprise; unset means HCP Terraform |
| `NO_COLOR` | Set to turn off colored output |
