# Carter documentation

New to Carter? Read the first three guides in order. Everything else can wait
until you need it.

## Start here

1. [Install Carter](guides/install.md): prerequisites, install, upgrade, uninstall.
2. [Use Carter](guides/using-carter.md): pick an agent, ask for work, run a review.
3. [Your first workspace](guides/first-workspace.md): per-project settings and memory.

## Guides

| Page | Read it when you want to… |
|------|---------------------------|
| [Safety and permissions](guides/safety-and-permissions.md) | Understand what each agent may do, and choose `guarded` or `strict` |
| [Write operations (`ops:`)](guides/write-operations.md) | Let Carter commit, push, open PRs or comment on Jira, with your approval |
| [MCP servers](guides/mcp-servers.md) | Give agents read access to GitHub, Terraform or Jira/Confluence |
| [Memory and plans](guides/memory-and-plans.md) | Keep lessons, decisions and multi-session plans |
| [Cost and models](guides/cost-and-models.md) | Pick models per agent and keep your token bill down |

## Reference

| Page | Contents |
|------|----------|
| [CLI](reference/cli.md) | Every `carter` command and flag |
| [Configuration](reference/configuration.md) | Every key in `.carter/carter.yaml` |
| [Permissions](reference/permissions.md) | The exact permission rules Carter writes for each agent |
| [Files and paths](reference/files-and-paths.md) | What Carter writes where, and what uninstall keeps |
| [Frontmatter](reference/frontmatter.md) | Schemas for plans, checkpoints, decision records and RFCs |

## Help

- [Troubleshooting](troubleshooting.md): symptoms and fixes.
- [Issues](https://github.com/mauriciomem/carter-ai/issues): report a bug or ask a question.

## Contributing

- [Development](contributing/development.md): set up a checkout, repo layout, releases.
- [Testing](contributing/testing.md): unit tests, CI, and the
  [eval framework](../evals/README.md).

## A few terms

| Term | Meaning |
|------|---------|
| **OpenCode** | The terminal app that runs the agents and talks to the AI model. Carter only writes files for it |
| **Agent** | A named AI role with its own instructions, model and permissions, a bit like a service account |
| **Primary agent / subagent** | You pick a primary agent in OpenCode (Maestro). Subagents (the specialists) are launched by it |
| **Skill** | A playbook an agent loads on demand, like a runbook |
| **MCP server** | A plugin that gives agents extra tools, such as reading GitHub issues |
| **Token** | The unit AI providers bill by: roughly a word fragment of input or output |
| **Workspace** | A project directory set up with `carter init` |
