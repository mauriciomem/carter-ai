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
| `~/.carter/audit.log` | Log of `ops:` operations and policy exceptions | Kept | Kept |
| `~/.carter/backups/<timestamp>/` | Files replaced by an install | Added to | Kept |
| `~/.carter/manifest.json` | What Carter installed, with checksums | Rewritten | Removed |

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
| `GITHUB_TOKEN` | The `carter-github` MCP server; reported by `carter ops config --emit` |
| `TFE_TOKEN` | The `carter-terraform` MCP server |
| `TFE_ADDRESS` | Optional, for Terraform Enterprise; unset means HCP Terraform |
| `NO_COLOR` | Set to disable colored installer output |
