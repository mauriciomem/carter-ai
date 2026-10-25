# MCP servers

MCP (Model Context Protocol) servers are plugins that give agents extra tools, such
as searching GitHub issues or reading a Terraform workspace. Carter can configure
three of them for you. They are optional.

| Server | Gives agents | Needs |
|--------|--------------|-------|
| `carter-github` | Read-only access to repositories, files, commits, issues and PRs | Docker, `GITHUB_TOKEN` |
| `carter-terraform` | Terraform Registry, HCP Terraform and Terraform Enterprise workspaces | Docker, `TFE_TOKEN` |
| `carter-atlassian` | Jira issues and Confluence pages | An Atlassian account (OAuth sign-in, no token) |

## Install

Set the tokens for the servers you want, then run:

```bash
export GITHUB_TOKEN="..."   # a GitHub personal access token
export TFE_TOKEN="..."      # HCP Terraform / Terraform Enterprise API token

carter install --mcp --mcp-servers github,terraform   # just these
carter install --mcp                                  # all three
```

Put the `export` lines in your shell profile so OpenCode sees them later. For
Terraform Enterprise, also set `TFE_ADDRESS`; leave it unset for HCP Terraform.
[`.env.example`](../../.env.example) lists every variable.

A missing token is only a warning; the install continues:

```text
→ Checking credentials...
  ⚠ GITHUB_TOKEN
    export GITHUB_TOKEN="your-value"
```

The Atlassian server needs no token. It signs you in through OAuth in OpenCode the
first time it is used.

> [!TIP]
> **Install only what you use.** Every configured server's tool list is sent to the
> model with each request, which makes MCP servers one of the largest parts of every
> request. A server you skip costs nothing.

## Where the configuration goes

Carter adds its servers under `mcp.servers` in your global OpenCode config
([OpenCode MCP servers](https://opencode.ai/v2/docs/mcp-servers/)), next to any
servers you already have:

| You have | Carter writes to |
|----------|------------------|
| Neither file | a new `~/.config/opencode/opencode.json` |
| `opencode.json` | `opencode.json` |
| `opencode.jsonc` | `opencode.jsonc` |
| Both | `opencode.jsonc`, and removes its own servers from `opencode.json` (with a warning) |

Carter rewrites the file as plain JSON. If it contained comments, the original is
kept next to it first:

```text
  ⚠ opencode.jsonc had comments; rewriting it does not keep them
    Original saved as ~/.config/opencode/opencode.jsonc.carter-backup
  ✓ carter-github → opencode.jsonc (mcp.servers)
```

If you already have a server called `github` (or `terraform`, `atlassian`), Carter
installs its own as `carter-github` alongside and warns you. Remove one of the two
to avoid duplicate tools.

`carter uninstall` removes the `carter-*` servers from both files.

## What "read-only" means for GitHub

`carter-github` runs the official
[GitHub MCP server](https://github.com/github/github-mcp-server) in Docker, pinned to
an exact image, in read-only mode with a short list of tools. That removes GitHub
**write tools** from what the model can call through MCP.

It does not stop Carter from writing to GitHub. `git push` and `gh` commands still
work, under the normal [permission rules](safety-and-permissions.md): only DevOps may
run them, and they ask first.

## Permissions

MCP tools have no specific permission rule, so every call **asks** you. Choosing
"Allow always" for a read tool you trust is reasonable; see
[the limits](safety-and-permissions.md#know-the-limits) first.

## Next

- [Write operations](write-operations.md): Jira and GitHub writes
- [Cost and models](cost-and-models.md)
