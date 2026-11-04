# Files and paths

Everything Carter writes, where it lives, and what happens to it on update and
uninstall.

## Global install (`carter install`)

| Path | Contents | Re-install | Uninstall |
|------|----------|------------|-----------|
| `~/.config/opencode/agents/carter-*.md` | The 8 agents | Updated (old copy backed up) | Removed unless edited |
| `~/.config/opencode/skills/carter-*/` | The 27 skills | Updated (old copy backed up) | Removed unless edited |
| `~/.config/opencode/AGENTS.md` | Global rules loaded in every session | Updated if it is an unedited earlier Carter version; left alone (with an upgrade note) if you changed it | Removed unless edited |
| `~/.config/opencode/opencode.json` or `.jsonc` | `carter-*` MCP servers (with `--mcp`) | Servers replaced | `carter-*` servers removed |
| `~/.config/opencode/opencode.jsonc.carter-backup` | Copy of a config file that had comments | Overwritten | Kept |
| `~/.carter/knowledge/` | 6 global knowledge files | Never overwritten | Removed only if unchanged |
| `~/.carter/memories/{user,repo,session}/` | Raw notes | Kept | Kept |
| `~/.carter/config.toml` | Schema-2 settings: LLM identity, footer, per-workspace policy | Created if missing; a schema-1 file is migrated once (original kept as `config.toml.schema1.bak`); otherwise left alone | Kept |
| `~/.carter/config.toml.schema1.bak` | Copy of the file before its migration | Never overwritten | Kept |
| `~/.carter/upgrade-notes/<version>.md` | The new commit rule, when your global `AGENTS.md` has your edits and could not be updated | Written once per version | Kept |
| `~/.carter/state/audit/audit.log` | Log of `ops:` operations and policy exceptions (moved here from `~/.carter/audit.log` the first time it is written) | Kept | Kept |
| `~/.carter/state/audit/b.jsonl` (dir 0700, file 0600) | One line per decision of the [B tools](../guides/push-and-pr-tools.md): time, agent, session, repo, branch, range, commit count, decision, code, dwell. Never an environment, a credentialed URL or a title. Rotates at 5 MiB (three older files kept) | Appended by the broker | Kept |
| `~/.carter/backups/<timestamp>/` | Files replaced by an install | Added to | Kept |
| `~/.carter/manifest.json` | What Carter installed, with checksums | Rewritten | Removed |
| `~/.carter/guard-state.json` (0600) | What `carter guard install` owns: consents, statements, per-agent denies, file hashes. Separate from `manifest.json` so an older installer can't drop it | Updated in place, never rebuilt; unchanged content is not rewritten | Removed by `guard remove` / `uninstall` (kept with `--keep-guards`) |
| `~/.config/opencode/opencode.json` or `.jsonc` → `policies`, `agents` | Carter's policy block (the tail of `policies`) and the per-agent `carter_push`/`carter_pr` denies | Re-appended at the tail; your own entries are kept | Removed only where unchanged |
| `~/.carter/backups/<timestamp>/opencode.json[c]` (0600) | Copy of your OpenCode config before a guard write | Added to | Kept |
| `~/.carter/gitconfig` and `gitconfig.d/` | Carter's own git keys behind one `include.path` line in your global git config: the hook entries for `pre-push`, `prepare-commit-msg`, `commit-msg` and `post-commit` (`hook.carter-guard-<event>.*`), the optional `alias.ai-commit`, or `init.templateDir` on git older than 2.54. If your global config is a symlink or read-only, Carter prints the line instead of writing it | Rewritten if unchanged; an edited file is kept and reported | Removed only if unchanged |
| `~/.carter/hooks/carter-guard` (0755) | The POSIX guard script behind the `pre-push` hook. Blocks only agent shells; a missing script never blocks you | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/hooks/template/` | `init.templateDir` content for new clones (git older than 2.54 only) | Rewritten if unchanged | Removed only if unchanged |
| `<repo>/.git/hooks/pre-push`, `prepare-commit-msg`, `commit-msg`, `post-commit` | Per-repo hooks, only on git older than 2.54 and only where that event had none (each event is judged on its own). Recorded with their hashes | Kept | Removed only if unchanged |
| `~/.config/opencode/plugins/carter/index.ts`, `core.ts`, `broker.ts` | The Carter plugin. OpenCode discovers it from this folder (nothing is registered). `index.ts` is rendered with the hash of `isolation.json` | Rewritten if unchanged; an edited file is kept and agent shells are refused until you restore it | Removed only if unchanged |
| `~/.carter/isolation.json` (0600) | The shell-isolation block the plugin applies to agent shells (variables, git config, the paths of Python and `carter`, the declined groups). The plugin refuses to start an agent shell if it changes | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/run/b-rejections.json` (0600) and `b-*.lock` | The B rejection counters per session family, and one lock per repository during a push | Written by the broker; cleared by `carter guard status --reset-b` | Kept |
| `~/.carter/opencode-headless.json` | The profile that denies the B tools to devops for `OPENCODE_CONFIG=` with `opencode run --standalone` (only while `g2` is at revision 3) | Rewritten if unchanged | Removed only if unchanged |
| `~/.carter/run/` (0700), `run/gh-empty/` (0700, empty), `run/plugin-status/<pid>.json` | The empty `gh` config folder agents get, and one status file per OpenCode server process (self-test state, versions, flag names, never values). `carter check --host` reads them | Created; status files rewritten by the plugin | Removed |
| `~/.carter/secrets/gh-read.token` (0600, in a 0700 directory) | The read-only GitHub token, written by `carter github-token set`; read by the `carter-github` MCP entry, `github-token check`, `check --host` and `carter push` | Replaced atomically by `set`; never touched by guards | Kept, with a reminder to delete and revoke it |
| `~/.carter/bin/carter-ssh-sign` (0755) | The signing shim git calls as `gpg.ssh.program`: it signs only with the LLM key through Carter's agent. Recorded with its hash; the plugin refuses to sign if it changes | Rewritten by `identity add` | Removed by `identity remove` only if unchanged |
| `~/.carter/hooks/allowed_signers` (0600, folder 0700) | The LLM's public keys (current and `previous_public_keys`) for `identity verify` and the `post-commit` check | Rewritten by `identity add` | Removed by `identity remove` only if unchanged |
| `~/.carter/gitconfig` (tier mirror) and `gitconfig.d/<hash>` | `carter.tier`, `carter.llmEmail`, `carter.llmFingerprint` and one `includeIf "gitdir:"` fragment per workspace with a `max_tier`: how the git hooks learn the tier. The user's own git config is never written for this | Rewritten by `identity add` and `carter update` | The mirror is removed by `identity remove`; the hook entries stay until `guard remove` |
| `~/.carter/run/agent.sock`, `agent.pid`, `unlock.lock` (or `$XDG_RUNTIME_DIR/carter/agent.sock`; on macOS `$TMPDIR/carter-<uid>/`) | Carter's dedicated `ssh-agent` while a key is unlocked | Created by `identity unlock` | Removed by `identity lock --all` / `identity remove` |
| `~/.carter/run/coauthor-link.json` (0600) | Role `author`: whether GitHub knows your `user.email`, one row per address as a **hash** (`noreply` or `verified`, with the time; never the address). Valid for 7 days | Written by `identity add` and `check --host` in your own terminal only | Kept |
| `~/.carter/run/guard.log` (0600) | One line per `post-commit` warning (a commit that is unsigned or not signed by the LLM key). Never read by Carter | Appended by the hook | Kept |
| `~/.carter/state/audit/` | Audit store | Kept | Kept |

Uninstall uses the checksums in the manifest to decide whether you edited a file.
Anything you changed is kept and reported as `⚠ Kept …`.

## Workspace (`carter init`)

| Path | Contents | `carter update` |
|------|----------|-----------------|
| `.opencode/agents/carter-*-local.md` | The workspace agents | Always rewritten |
| `AGENTS.md` | Project rules for OpenCode | Created only if missing |
| `.carter/carter.yaml` | Workspace settings | Read, never written |
| `.carter/knowledge/` | 5 project knowledge files | Never touched |
| `.carter/state/plans/active/`, `completed/` | Plans | Never touched |
| `.carter/state/sessions/checkpoint.md` | Session checkpoint | Never touched |
| `.carter/state/handoff/<branch>.md` | A branch's PR handoff written by an agent (`/` is written `%2F`). Never part of the `.carter/.git` snapshots, because it may hold unredacted text. Read only by `carter pr`, which deletes it after the pull request is created | Never touched |
| `.carter/.git/` | Private history of `.carter/` (`carter save`) | Never touched |
| `.gitignore` | Gets a `.carter/` line with `--single` | Never touched |

`carter uninstall` never touches workspaces. To remove one, delete `.carter/`, the
`carter-*` files in `.opencode/agents/`, and `AGENTS.md` if Carter created it.

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
| `NO_COLOR` | Set to disable colored installer output |
