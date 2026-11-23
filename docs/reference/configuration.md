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
these two values and pins them in `~/.carter/config.toml` (see
[User config](#user-config-carterconfigtoml)).

| Key | Default | Description |
|-----|---------|-------------|
| `role` | not set | `co-author` (the default role) or `author`. `author` makes the LLM the author and credits you by a trailer. It needs LLM signing on (a signing key); without it, or under a `max_tier` cap, commits are refused, never downgraded, and `carter update` refuses to pin it next to a cap |
| `require_tier` | not set | The lowest tier this workspace accepts: `t0`, `t1` or `t2` |

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
| `level` | not set | Deprecated alias of `access.level`: it can only tighten the level set in `~/.carter/config.toml` (`strict` when that is absent). An unknown value counts as `strict` |
| `overrides` | `{}` | Per-category effect, e.g. `{remote-write: deny}`. Categories: `read`, `local-write`, `remote-write`, `dangerous`. Effects: `allow`, `ask`, `gate`, `deny`. Only an effect at least as strict as the level's own is applied |
| `allowlist` | not set | Remove a category from an agent, e.g. `{devops: {dangerous: false}}`. A `true` Carter does not already grant is ignored |

A workspace can only tighten. Keys here that loosen a control (an override to a looser effect,
an extra category for an agent) are ignored: `carter update` and `carter check` print one line
and `-v` names the keys. Loosening is human-only: it is set with `[access]` in
`~/.carter/config.toml`. This does not protect your own tightening: an agent that can edit `carter.yaml` can remove it,
and one with edit or shell access can change the rendered agent files directly (`carter check`
reports the drift). `[access]` in `~/.carter/config.toml` is the level you set; a workspace can
only tighten it.

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

Carter keeps your settings and what it derives in two files in `~/.carter/`:

| File | Owner | Holds |
|------|-------|-------|
| `config.toml` | you | Your decisions. Carter never writes it and `carter install` does not create it. It may be absent; comments and keys of your own stay as you left them |
| `config-managed.toml` | Carter | What Carter derives. Mode `0600`; first line `# Written by Carter. Edit config.toml instead.` |

Each key has one owning file. Only what differs from the default is stored, and the defaults
below apply to every key that is absent.

| Owner | Keys |
|-------|------|
| `config.toml` (you) | `[access]`; `[workspaces."<path>"]` `max_tier`, `allow_project_opencode_edit`; `[broker]`; `[attribution]`; `[identity.disclosure]`; `[github]` `probe_repo`; `[identity]` `role`, `mode`; `[identity.signing]` `ttl`, `ssh_bin_dir` |
| `config-managed.toml` (Carter) | `[identity]` `login`, `id`, `name`, `email`; `[identity.signing]` `public_key`, `fingerprint`, `private_key_path`, `mode`, `previous_public_keys`, `agent_socket`, `program`; `[github]` `read_token_file`; `[pins."<path>"]` `role`, `require_tier` |

`carter identity add`, `carter github-token set` and `carter update` (the pins from `carter.yaml`)
write the managed file; `identity remove` takes the identity out of it. After `carter identity add`
it looks like this:

```toml
# Written by Carter. Edit config.toml instead.

[identity]
login = "carter-bot"
id = 12345
name = "Carter Bot"
email = "12345+carter-bot@users.noreply.github.com"

[identity.signing]
public_key = "ssh-ed25519 AAAA..."
fingerprint = "SHA256:..."
private_key_path = "/home/you/.ssh/carter-bot"
```

How the two are read:

- A key of yours found in the managed file is ignored; `carter check --host` names it.
- A table you also set in `config.toml` wins over the managed one; `check --host` says so in one
  line. `identity add` and `update` then refuse to change it: edit `config.toml` yourself.
- The managed file is trusted only if it is a regular file owned by you with no group or other
  access, and neither it nor `~/.carter/` is a symlink. If a check fails, Carter reads it as empty:
  no LLM identity, and `check --host` says `config-managed.toml unsafe`. Carter writes it through
  a temporary file and a rename.

**Upgrading.** A `config.toml` that already holds derived values (an older `identity add`) keeps
loading as it is; Carter never moves or deletes them. To let Carter manage them again, delete
`[identity]`, `[identity.signing]` and any pins from `config.toml`, then run `carter identity add`.
`--role` on `identity add` only checks: set `role = "author"` under `[identity]` yourself.

A key Carter doesn't read is named by `carter check --host`, `carter install` and `carter update`
with its file, for example ``⚠ unknown key `x.y` in /home/you/.carter/config.toml → delete it``.
It never blocks a command. Loading the files never writes to them. `carter check` reports unknown
keys in `.carter/carter.yaml` and in plans the same way.

Every key, with its default (each in the file named above):

```toml
schema = 2

[identity]
role = "co-author"        # co-author | author
login = ""                # the LLM's GitHub account; empty means no LLM identity
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
                          # optional: ttl = "8h" (lifetime for unlock; unset = until locked)
                          # set by `identity add`: mode = "file" (no passphrase) or "agent"

[broker]                  # optional; written only when you set something
min_dwell_ms = 500        # how long an approval must take; 500 is the floor, 10000 the cap

[workspaces."/abs/path"]
max_tier = "t1"           # optional cap: t0 | t1, set by hand, then run `carter update`
                          # role and require_tier are pins: `carter update` writes them to
                          # [pins."/abs/path"] in config-managed.toml

[pins."/abs/path"]        # config-managed.toml only
role = "co-author"
require_tier = "t2"
```

| Table | Keys |
|-------|------|
| `[identity]` | `role`, `login`, `id`, `name`, `email`, `mode` (`auto`, `interactive` or `review`; `CARTER_IDENTITY_MODE` wins; in a detected CI `auto` is `review`, which refuses commits. See [Review-only CI](../guides/ci-review.md#modes)) |
| `[identity.signing]` | The LLM's signing key, written by `carter identity add`: `public_key`, `fingerprint`, `private_key_path` (a path, never read), `previous_public_keys` (kept after a rotation so old commits verify), `ssh_bin_dir` (default `/usr/bin`; where `ssh-keygen`, `ssh-agent` and `ssh-add` come from), `ttl` (how long `identity unlock` keeps the key; none by default), `mode` (`file` for a key without a passphrase, signed straight from `private_key_path`; `agent` otherwise; set by `identity add`), `agent_socket` or `program` (a password manager instead of Carter's own agent) |
| `[github]` | `read_token_file`: where `carter github-token set` stored the GitHub token (a path only, never the token itself). `probe_repo`: optional `owner/name` that `github-token check` uses for its refused push attempt and its pull-request probe instead of a repository you own |
| `[broker]` | Optional, for [`carter_push`](../guides/write-operations.md#letting-devops-ask-you-to-push). `min_dwell_ms`: the shortest an approval may take before it is refused as automatic; the effective value is never below 500 and never above 10000. It always uses the home in your system account entry (what OpenSSH reads) for its git and ssh calls and for the `~/.ssh/config` scan; there is no setting for it |
| `[attribution]` | `footer`: appended to GitHub and Jira bodies |
| `[access]` | What agents may do: `level` and one value per capability id. See [access](#access) |
| `[workspaces."<path>"]` | `max_tier`, `allow_project_opencode_edit` (yours). `role` and `require_tier` are pins in `[pins."<path>"]` of the managed file; an older `config.toml` may still hold them here. The path is the resolved absolute path of the workspace |

### access

`carter access` prints one row per id below, with its value and where the value comes from. Each
capability id is a key of `[access]`.

```toml
[access]
level = "guarded"   # strict (the default when absent) | guarded | relaxed
pr_write = "ask"    # any capability id, up to its ceiling
```

| Key | Description |
|-----|-------------|
| `level` | `strict`, `guarded` or `relaxed`. Each is a preset of the table below |
| `<id>` | A capability id. Values: `allowed`, `ask`, `denied`. It replaces the preset, up to the ceiling |

| Id | Label | strict | guarded | relaxed | Ceiling |
|----|-------|--------|---------|---------|---------|
| `workspace_edit` | Workspace edits | allowed | allowed | allowed | allowed |
| `run_commands` | Run commands | allowed | allowed | allowed | allowed |
| `git_commit` | Git commit | allowed | allowed | allowed | allowed |
| `github_read` | GitHub reads | allowed | allowed | allowed | allowed |
| `pr_write` | PR writes | ask | allowed | allowed | allowed |
| `issue_write` | Issue writes | denied | ask | allowed | allowed |
| `destructive` | Destructive | denied | ask | ask | ask |
| `infra_apply` | Infra apply | denied | ask | ask | ask |
| `opencode_config` | OpenCode config | denied | denied | denied | denied |

`pr_write` and `issue_write` cover opening and commenting. `destructive` covers `rm -rf` and
`git reset --hard`; `infra_apply` covers `terraform apply` and similar. `opencode_config` is edits
of a project's OpenCode config.

The ceiling is the loosest value a key may take; a looser value is an error. `opencode_config`
opens only for a workspace that sets `allow_project_opencode_edit` (below). `carter access` then
shows it as `allowed` with the source `opt-out`.

The floor shows `never` at every level. Setting one of these ids is an error:

| Id | Label | Value |
|----|-------|-------|
| `push` | Push from shell | never |
| `gh_api` | GitHub API | never |
| `github_admin` | GitHub decisions | never |
| `sudo` | Root | never |
| `secrets` | Secrets | never |
| `carter_internals` | Carter internals | never |

The source column is `preset` (from the level), `override` (your key), `workspace` (a stricter
value from `carter.yaml`) or `opt-out`. A workspace takes the same ids under `access:` in
`.carter/carter.yaml` and can only tighten them; `policy.level` there is a deprecated alias of
`access.level`. Any error in `[access]`, or a file that does not parse, renders `strict`;
`carter update` and `carter access` say why. `[access]` is read only from `config.toml`, which
Carter never writes; the same table in the managed file is ignored. See
[Safety and permissions](../guides/safety-and-permissions.md#choose-a-level).

### Letting agents edit a project's OpenCode config

By default the guards deny agents any edit of OpenCode config files, `.opencode/`, git hooks
and git config. To allow it in one workspace (the resolved absolute path), set this by hand
in your own terminal:

```toml
[workspaces."/abs/path/to/project"]
allow_project_opencode_edit = true
```

It takes effect only when a human runs `carter guard install` or `carter update`: they write
three exact-path `allow` rules (`opencode.json`, `opencode.jsonc` and `.opencode/*` of that
workspace) after the denies in the Carter agents' permissions, and
`guard install` lists every active opt-out. It asks nothing. `carter check --host` lists
them too. A path that no longer exists or contains `*` or `?` is skipped with a message.

What you set up is stored as one of three values, used by `max_tier`, `require_tier` and the
`tier` field of `carter ops config --emit`:

| Value | Meaning |
|-------|---------|
| `t0` | no LLM identity: nothing configured, commits carry `Assisted-by: Carter` |
| `t1` | LLM identity, unsigned: an LLM account without a key, commits carry `Co-authored-by: <login> <address>` |
| `t2` | LLM signing on: the account **and** a signing key, so agent commits are signed |

A workspace `max_tier` lowers the setup for that workspace, never raises it. With LLM signing on
the LLM signs agent commits; if signing cannot happen the commit fails and stays staged.
`max_tier = "t1"` for a workspace lets agents commit unsigned there. A `max_tier` takes effect for
the hooks when you run `carter update` (it writes the cap into `~/.carter/gitconfig`); the plugin
reads `config.toml` directly. **Worktree limit:** the cap follows the *main* repository of a
linked worktree, not the worktree's path (`carter check --host` lists such worktrees). Keys that hold
their default are left out of the file. A file Carter cannot read or that is incomplete
(for example, signing keys without an account) is `E-CONFIG`: agent commits are refused
instead of falling back to defaults.
