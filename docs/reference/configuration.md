# Configuration reference

A workspace is configured in `.carter/carter.yaml`, created by `carter init`. After
any change, run `carter update` to regenerate the agents and `carter check` to
validate them.

These settings apply only to workspace agents. The global agents from
`carter install` don't read any `carter.yaml`; they always use the defaults shown
here, with no name suffix.

## Full example

This is the file `carter init` writes, with every default:

```yaml
version: '2'
workspace:
  name: my-project
  mode: umbrella
personality:
  skepticism: scaled
  style: reviewer
agents:
- maestro
- architect
- engineer
- devops
- pm
- learner
- narrator
- security
agent_suffix: local
quality_gate:
  enabled: true
  max_iterations: 2
redaction:
  categories:
  - secrets
  - internal_urls
  - security_incidents
  - pii
  - financials
  - employee_data
  - infra_ids
tdd:
  strict: false
  spec_handoff: true
plans:
  step_file_threshold: 3
  readme_max_lines: 150
  step_max_lines: 80
policy:
  level: guarded
  overrides: {}
models:
  default: anthropic/claude-opus-5-5
  thinkers: anthropic/claude-opus-5-5
  implementers: anthropic/claude-sonnet-5-5
  overrides: {}
docs_language: en
```

`version`, `workspace` and `agents` are required. Any other key you
leave out takes its default. Unknown keys are ignored. Nested blocks merge with the
defaults, so you only write what you change; lists (`agents`,
`redaction.categories`) replace the default list entirely.

## Keys

### workspace

| Key | Default | Description |
|-----|---------|-------------|
| `name` | directory name | Shown in `AGENTS.md` |
| `mode` | `umbrella` | `umbrella` (a directory holding several repositories) or `single` (one repository). Set by `carter init --single` |

### identity

Optional: `carter init` does not write it, and a file without it is valid.

Policy only. Nothing here changes attribution while agents run: `carter update` shows
these two values, asks, and pins them in `~/.carter/config.toml` (see
[User config](#user-config-carterconfigtoml)).

| Key | Default | Description |
|-----|---------|-------------|
| `role` | not set | `co-author` (the default role) or `author`. `author` makes the LLM the author and credits you by a trailer. It needs a signing key (T2); below that tier or under a `max_tier` cap commits are refused, never downgraded, and `carter update` refuses to pin it next to a cap |
| `require_tier` | not set | The lowest tier this workspace accepts: `t0`, `t1` or `t2` |
| `git_account` | not set | Deprecated and ignored. `carter check` and `carter update` warn if it is present |
| `bot_name` | not set | Deprecated and ignored, with the same warning. The co-author comes from `~/.carter/config.toml` |

`allow_project_opencode_edit` and other settings that loosen a control are not accepted
here. Edit-denied settings live only in `~/.carter/config.toml`.

### personality

| Key | Default | Values |
|-----|---------|--------|
| `skepticism` | `scaled` | `scaled`: Maestro challenges risky or multi-file requests and lets trivial ones through. `always`: it challenges everything. `off`: pragmatic, no pushback. Architect and Engineer drop their "question every abstraction" stance when set to `off` |
| `style` | `reviewer` | `reviewer` makes Maestro look for what is missing or could break |

### agents and agent_suffix

| Key | Default | Description |
|-----|---------|-------------|
| `agents` | all eight | Which agents to generate: `maestro`, `architect`, `engineer`, `devops`, `pm`, `learner`, `narrator`, `security` |
| `agent_suffix` | `local` | Appended to agent names (`carter-engineer-local`). Lowercase letters, digits and hyphens; `''` for no suffix |

### quality_gate

| Key | Default | Description |
|-----|---------|-------------|
| `enabled` | `true` | Whether Maestro runs a [review](../guides/using-carter.md#review-before-you-push) when you ask for one |
| `max_iterations` | `2` | Review rounds before Maestro stops and lets you decide |

### tdd

| Key | Default | Description |
|-----|---------|-------------|
| `strict` | `false` | `true` makes the Engineer always write tests before code |
| `spec_handoff` | `true` | Agree on contracts before complex work, and check reviews against the active plan's `must_haves` |

### redaction

| Key | Default | Description |
|-----|---------|-------------|
| `categories` | all seven | What the Narrator removes from outward content: `secrets`, `internal_urls`, `security_incidents`, `pii`, `financials`, `employee_data`, `infra_ids` |

### plans

Size limits for [plans](../guides/memory-and-plans.md#plans), checked by
`carter check`.

| Key | Default | Description |
|-----|---------|-------------|
| `step_file_threshold` | `3` | Plans with more steps get one file per step |
| `readme_max_lines` | `150` | Maximum lines in a plan's `README.md` |
| `step_max_lines` | `80` | Maximum lines in a `step-NN.md` |

### policy

See [Safety and permissions](../guides/safety-and-permissions.md).

| Key | Default | Description |
|-----|---------|-------------|
| `level` | `guarded` | `guarded` or `strict`. Anything else counts as `guarded` |
| `overrides` | `{}` | Per-category effect, e.g. `{remote-write: deny}`. Categories: `read`, `local-write`, `remote-write`, `dangerous`. Effects: `allow`, `ask`, `gate`, `deny` |
| `allowlist` | not set | Grant or remove categories per agent, e.g. `{engineer: {remote-write: true}}` |

An invalid category or effect in `overrides` is an error. In `allowlist`, every
agent must be listed in `agents:`, every category must be one of the four, and every
value must be `true` or `false`; anything else is an error.

### models

See [Cost and models](../guides/cost-and-models.md).

| Key | Default | Description |
|-----|---------|-------------|
| `default` | `anthropic/claude-opus-5-5` | Used by any agent without a tier |
| `thinkers` | `anthropic/claude-opus-5-5` | Maestro, Architect, Learner, Security |
| `implementers` | `anthropic/claude-sonnet-5-5` | Engineer, DevOps, PM, Narrator |
| `overrides` | `{}` | Per-agent model, e.g. `{engineer: anthropic/claude-haiku-5-5}` |

Every value is one OpenCode model string: `provider/model`, optionally followed by
`#variant`. Anything else is an error.

### profile

Not set by default. `budget` moves Learner to the implementer model; `quality`
puts every agent on the thinker model. Precedence: `models.overrides` → `profile` →
tier → `models.default`. An unknown profile is an error.

### docs_language

Default `en`. The language for Carter's own documents: ADRs, RFCs, plans,
checkpoints, knowledge and memories. A language tag such as `es` or `pt-BR`.
Commits, code comments, repository docs, PRs, issues, Jira and Slack text are always
English.

## User config: `~/.carter/config.toml`

`carter install` creates it (schema 2) and migrates an older file once, saving the
original as `config.toml.schema1.bak` (never overwritten). The migration drops the old
`[git] signing_key` (Carter never uses your key) and an email that is not
`<id>+<login>@users.noreply.github.com`; it keeps your footer exactly as written. Loading
the file never writes to it.

```toml
schema = 2

[identity]
role = "co-author"        # co-author | author
login = ""                # the LLM's GitHub account; empty means no identity (T0)
id = 0
name = ""
email = ""                # <id>+<login>@users.noreply.github.com

[attribution]
footer = "_This comment was generated with Carter._"

[github]
read_token_file = ""      # set by `carter github-token set`: ~/.carter/secrets/gh-read.token
probe_repo = ""           # optional "owner/name" for the token's write probe (never printed)

[identity.signing]        # written by `carter identity add`; see the identity-and-signing guide
public_key = ""           # "ssh-ed25519 AAAA..." (no private key is ever stored here)
fingerprint = ""
private_key_path = ""     # a path only; Carter never opens the file
ttl = "8h"                # how long `carter identity unlock` keeps the key loaded

[broker]                  # optional; written only when you set something
min_dwell_ms = 500        # how long an approval must take; 500 is the floor, 10000 the cap

[workspaces."/abs/path"]
max_tier = "t1"           # optional cap: t0 | t1, set by hand, then run `carter update`
role = "co-author"        # pinned by `carter update`
require_tier = "t2"       # pinned by `carter update`
```

| Table | Keys |
|-------|------|
| `[identity]` | `role`, `login`, `id`, `name`, `email`, `mode` |
| `[identity.signing]` | The LLM's signing key, written by `carter identity add`: `public_key`, `fingerprint`, `private_key_path` (a path, never read), `previous_public_keys` (kept after a rotation so old commits verify), `ssh_bin_dir` (default `/usr/bin`; where `ssh-keygen`, `ssh-agent` and `ssh-add` come from), `ttl` (how long `identity unlock` keeps the key, default `8h`), `agent_socket` or `program` (a password manager instead of Carter's own agent) |
| `[identity.disclosure]` | Reserved for a later release; read and kept, not used yet |
| `[github]` | `read_token_file`: where `carter github-token set` stored the read-only token (a path only, never the token itself). `probe_repo`: optional `owner/name` that `github-token check` uses for its refused write attempt instead of a repository you own |
| `[broker]` | Optional, for the [B tools](../guides/push-and-pr-tools.md). `min_dwell_ms`: the shortest an approval may take before B refuses it as automatic; the effective value is never below 500 and never above 10000. B always uses the home in your system account entry (what OpenSSH reads) for its git and ssh calls and for the `~/.ssh/config` scan; there is no setting for it |
| `[attribution]` | `footer`: appended to GitHub and Jira bodies |
| `[workspaces."<path>"]` | `max_tier`, `role`, `require_tier`, `allow_project_opencode_edit`. The path is the resolved absolute path of the workspace |

### Letting agents edit a project's OpenCode config

By default the guards deny agents any edit of OpenCode config files, `.opencode/`, git hooks
and git config. To allow it in one workspace (the resolved absolute path), set this by hand
in your own terminal:

```toml
[workspaces."/abs/path/to/project"]
allow_project_opencode_edit = true
```

It takes effect only when a human runs `carter guard install` or `carter update`: both list
every active opt-out and ask (`--yes` skips only the question). `carter check --host` lists
them too. A path that no longer exists or contains `*` or `?` is skipped with a message.

Tiers: T0 is nothing configured (commits carry `Assisted-by: Carter`), T1 is an LLM
account without a key (`Co-authored-by: <login> <address>`), T2 adds a signing key. A
workspace `max_tier` lowers the tier for that workspace, never raises it. At an effective T2
the LLM signs agent commits; if signing cannot happen the commit fails and stays staged.
`max_tier = "t1"` for a workspace lets agents commit unsigned there. A `max_tier` takes effect for
the hooks when you run `carter update` (it writes the cap into `~/.carter/gitconfig`); the plugin
reads `config.toml` directly. **Worktree limit:** the cap follows the *main* repository of a
linked worktree, not the worktree's path (`carter check --host` lists such worktrees). Unset optional
keys are left out of the file. A file Carter cannot read or that is incomplete
(for example, signing keys without an account) is `E-CONFIG`: agent commits are refused
instead of falling back to defaults.
