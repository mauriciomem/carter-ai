# Your first workspace

A **workspace** is a project directory where Carter keeps its own settings, plans and
knowledge. You create one with `carter init`. The global install keeps working
everywhere else.

Use a workspace when a project needs any of these:

- different models or a stricter safety level,
- plans and checkpoints that survive between sessions,
- project-specific knowledge (gotchas, conventions, decisions).

## Create it

The directory must already exist:

```bash
mkdir -p ~/my-project
carter init ~/my-project
```

```text
Initialized .carter/ in /home/you/my-project
ℹ  Strictness policy is 'guarded': remote-write and dangerous (infra-mutate / destructive) actions are gated per the risk taxonomy (see the maestro policy table).
Workspace 'my-project' initialized (umbrella mode)
```

Useful options:

| Option | Effect |
|--------|--------|
| `--name NAME` | Workspace name (default: the directory name) |
| `--single` | Single-repository mode: also adds `.carter/` to the project's `.gitignore` |
| `--profile budget\|quality` | Pick a [cost profile](cost-and-models.md) |
| `--agent-suffix SUFFIX` | Suffix for agent names (default `local`; `''` for none) |
| `--docs-language TAG` | Language for Carter's own notes, e.g. `es` or `pt-BR` |
| `--no-git-state` | Don't create the private history repo in `.carter/.git` |

The default mode, **umbrella**, suits a directory that holds several repositories.
Use `--single` when the workspace is one repository, so Carter's files stay out of
its history.

## What it creates

```text
my-project/
├── AGENTS.md                 project rules for OpenCode (only if absent)
├── .carter/
│   ├── .git/                 private history for Carter's state
│   ├── carter.yaml           your settings
│   ├── knowledge/            five project knowledge files
│   └── state/
│       ├── plans/active/
│       ├── plans/completed/
│       └── sessions/         session checkpoint
└── .opencode/
    └── agents/               the 8 workspace agents (carter-*-local.md)
```

The nested `.carter/.git` keeps a history of plans and knowledge without touching
your project's own Git history.

## Global and workspace agents

Workspace agents get a suffix so you can tell them apart from the global ones:
`carter install` writes `carter-engineer`, `carter init` writes
`carter-engineer-local`. When you run OpenCode inside the workspace you see both
Maestros; pick **carter-maestro-local** to use this project's settings.

Set `agent_suffix: ""` in `carter.yaml` (or `--agent-suffix ''`) if you prefer the
same names as the global agents.

## Change settings

Edit `.carter/carter.yaml`, then regenerate the agents:

```bash
carter update ~/my-project            # or: carter update   (inside the project)
carter update ~/my-project --dry-run  # preview which files would be written
```

The settings you are most likely to change:

| Key | What it does |
|-----|-------------|
| `policy.level` | `guarded` (default) or `strict`. See [Safety](safety-and-permissions.md) |
| `profile` / `models` | Which AI model each agent uses. See [Cost and models](cost-and-models.md) |
| `quality_gate` | Turn the pre-push review on or off; set the number of review rounds |
| `tdd.strict` | Make the Engineer write tests before code, always |
| `personality.skepticism` | How hard Maestro challenges your requests: `scaled`, `always` or `off` |
| `agents` | Which agents to generate |

Every key is described in the [configuration reference](../reference/configuration.md).

> [!IMPORTANT]
> `carter update` rewrites the `carter-*` agent files on every run, so don't edit
> them by hand; change `carter.yaml` instead. It never touches `AGENTS.md` or your
> knowledge files once they exist.

## Validate

```bash
carter check ~/my-project
```

```text
OpenCode loaded all 8 Carter agents
ℹ  Model pins: maestro → anthropic/claude-opus-5-5, architect → anthropic/claude-opus-5-5, engineer → anthropic/claude-sonnet-5-5, devops → anthropic/claude-sonnet-5-5, pm → anthropic/claude-sonnet-5-5, learner → anthropic/claude-opus-5-5, narrator → anthropic/claude-sonnet-5-5, security → anthropic/claude-opus-5-5. Carter cannot verify your OpenCode provider subscription includes them.
Workspace OK
```

`carter check` confirms that:

- every agent file, `AGENTS.md` and knowledge file exists,
- each agent's permissions and model still match `carter.yaml`,
- plans and the session checkpoint follow their [schemas](../reference/frontmatter.md),
- OpenCode itself loads every agent with those settings (it runs
  `opencode debug agents`, which starts OpenCode's background service if needed;
  see the [CLI reference](../reference/cli.md#carter-check) for retries and timeouts).

Nothing runs this automatically. Run it after you change settings or edit a plan.
Use `--no-harness` to skip the OpenCode step.

## Save state

```bash
carter save ~/my-project -m "before refactor"
```

`carter save` commits everything in `.carter/` to its private history, so a
deleted plan or checkpoint can be recovered. Maestro offers to do this at natural
pauses.

## Next

- [Memory and plans](memory-and-plans.md)
- [Safety and permissions](safety-and-permissions.md)
- [Configuration reference](../reference/configuration.md)
