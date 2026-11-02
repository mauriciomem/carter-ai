# MCP servers

MCP (Model Context Protocol) servers are plugins that give agents extra tools, such
as searching GitHub issues or reading a Terraform workspace. Carter can configure
three of them for you. They are optional.

| Server | Gives agents | Needs |
|--------|--------------|-------|
| `carter-github` | Read-only access to repositories, files, commits, issues and PRs | Docker, a read-only token stored with `carter github-token set` |
| `carter-terraform` | Terraform Registry, HCP Terraform and Terraform Enterprise workspaces | Docker, `TFE_TOKEN` |
| `carter-atlassian` | Jira issues and Confluence pages | An Atlassian account and a one-time sign-in (no token) |

## Install

Store the GitHub token (next section), set the Terraform token if you want that server,
then run:

```bash
export TFE_TOKEN="..."      # HCP Terraform / Terraform Enterprise API token

carter install --mcp --mcp-servers github,terraform   # just these
carter install --mcp                                  # all three
```

Put the `export` line in your shell profile so OpenCode sees it later. For
Terraform Enterprise, also set `TFE_ADDRESS`; leave it unset for HCP Terraform.
[`.env.example`](../../.env.example) lists every variable. The GitHub token is
**not** an environment variable: `carter-github` reads it from a file.

A missing token is only a warning; the install continues:

```text
→ Checking credentials...
  ⚠ GitHub read-only token not found
    Run `carter github-token set` in your own terminal (a read-only fine-grained token).
  ⚠ TFE_TOKEN
    export TFE_TOKEN="your-value"
```

The Atlassian server needs no token, but you sign in once
([OpenCode MCP servers](https://opencode.ai/v2/docs/mcp-servers/)): run `/mcps` in
OpenCode and select `carter-atlassian`, or run:

```bash
opencode mcp auth carter-atlassian
```

Until then, `opencode mcp list` shows it as needing authentication.

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

## The GitHub token

`carter-github` needs a **fine-grained personal access token** (`github_pat_…`) that can
only read. Classic tokens (`ghp_`) and tokens from `gh auth token` (`gho_`) are refused.
Create it at <https://github.com/settings/personal-access-tokens>:

- **Repository access:** only the repositories Carter works on. Never "All repositories":
  Carter cannot check this for you, because GitHub does not show it to the token.
- **Permissions, all Read-only:** Metadata, Contents, Pull requests, Issues, Actions,
  Checks and Commit statuses. Grant nothing with Write.
- **Expiry:** 90 days or less. `carter github-token check` warns 14 days before.
- **One owner:** a token belongs to one user or organisation. For an organisation that
  uses SAML single sign-on, authorise the token for it. Repositories of several owners
  need several tokens, which this release does not support.

Then, in your own terminal, give it to Carter on standard input (a hidden prompt, or a
pipe from your password manager; never as an argument):

```bash
carter github-token set
carter github-token check
```

`set` writes `~/.carter/secrets/gh-read.token` (directory 0700, file 0600, atomically) and
records its path under `[github] read_token_file` in `~/.carter/config.toml`. The `carter-github`
entry reads `{file:~/.carter/secrets/gh-read.token}`, so nothing sits in your environment or in
the OpenCode config. `check` verifies the file (mode 0600, yours, not a symlink, outside any
repository), that GitHub accepts the token, how long it lasts, and that it **cannot write**:
it asks GitHub to create a branch pointing at an all-zero commit, which no token can
complete; "Resource not accessible" means read-only, anything else is flagged red. Both
commands refuse in an agent shell and print at most the first four characters of a token
in an error. `carter check --host` repeats these checks.

The token is readable by anything running as you, and agents can see anything their shell
sees. Treat it as disclosed to your model provider; that is why it must be read-only.
Agents can't read the file with their file tools once the `read-edit-denies` guard is
installed, but the guards are a speed bump in this release (see
[Install: guards](install.md#guards)). Rotate it by running `carter github-token set`
again; revoke it on GitHub when you no longer need it.

## What "read-only" means for GitHub

`carter-github` runs the official
[GitHub MCP server](https://github.com/github/github-mcp-server) in Docker, pinned to
an exact image, in read-only mode with a short list of tools. That removes GitHub
**write tools** from what the model can call through MCP.

Writing to GitHub is a separate matter, and it is yours: no agent can push or run a `gh`
write command, and your token for the MCP server could not write anyway. You push and open
pull requests with [`carter push` and `carter pr`](write-operations.md#pushing-and-pull-requests-the-handoff).

## Permissions

MCP tools have no specific permission rule, so every call **asks** you. Choosing
"Allow always" for a read tool you trust is reasonable; see
[the limits](safety-and-permissions.md#know-the-limits) first.

## Next

- [Write operations](write-operations.md): Jira writes, and how you push and open pull requests
- [Cost and models](cost-and-models.md)
