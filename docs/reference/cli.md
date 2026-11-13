# CLI reference

Every `carter` command and option. For a walkthrough, start with
[Install Carter](../guides/install.md).

```text
carter [--version] [-v] [--no-color] [--help] COMMAND [ARGS]
```

Most commands end in one to three lines: `✓ result`, or `✗ cause` followed by `→ fix` with
the error code dimmed at the end. `install` and `uninstall` print a short report instead (below).
`-v` shows the lines a normal run leaves out. Colour is off when the output is not a terminal, with
`NO_COLOR` set, or with `--no-color`; bold and dim stay, and the text is the same as when piped. On a
terminal that cannot show Unicode, `✓ ! ✗ → ·` become `ok ! x -> -`. Warnings and errors go to
stderr, the rest to stdout.

| Command | Purpose |
|---------|---------|
| [`install`](#carter-install) | Install the agents, skills and rules into OpenCode |
| [`uninstall`](#carter-uninstall) | Remove what `install` wrote |
| [`init`](#carter-init) | Create a workspace in a project directory |
| [`update`](#carter-update) | Regenerate a workspace's agents from `carter.yaml` |
| [`check`](#carter-check) | Validate a workspace, or this machine with `--host` |
| [`guard`](#carter-guard) | Install, inspect and remove the guards |
| [`identity`](#carter-identity) | Set up, check, unlock and lock the LLM identity and its signing key |
| [`commit`](#carter-commit) | `git commit` as the LLM identity: signed when LLM signing is on, with the trailer |
| [`github-token`](#carter-github-token) | Store and check the read-only GitHub token |
| [`push`](#carter-push) | Push the current branch to `origin` |
| [`ci`](#carter-ci) | Install and check the review-only CI workflow |
| [`gate`](#carter-gate) | Ask the command gate about a command |
| [`save`](#carter-save) | Commit the workspace state to its private history |
| [`ops`](#carter-ops) | Audit log and config helper used by the `ops:` flow |

Commands that take a `TARGET_DIR` default to the current directory, which must
exist.

## carter install

Install Carter for OpenCode 2.1 or newer. Writes to `~/.config/opencode/` and
`~/.carter/`. Stops without writing anything if OpenCode is missing or too old.

| Option | Description |
|--------|-------------|
| `--mcp` | Also configure the MCP servers |
| `--mcp-servers TEXT` | Comma-separated subset: `github`, `terraform`, `atlassian`. Default: all. Only with `--mcp` |
| `-y`, `--yes` | Install the guards without asking. Without a terminal and without `--yes` the guards are skipped with a notice |
| `-q`, `--quiet` | Errors only |
| `-v`, `--verbose` | Show every step |
| `--debug` | Debug output |

A normal run prints a header (`Carter install  v0.19.2`), warnings, the guard step
([`carter guard install`](#carter-guard-install)), which asks one question, and then a report:

```text
Carter install  v0.19.2

✓ Installed
    agents            8  new
    skills           27  new
    knowledge files   4  new
    config.toml          created
    guards               g2 · hooks · sudo-docker · read-edit-denies · config-edit

→ restart the OpenCode server from a clean terminal to load the agents and plugin
```

On a re-run the notes read `up to date` or `1 updated`. `old backups` appears when copies older than
15 days were removed. If the install replaced files you had edited, one line on stderr names the
folder with their copies (`! Replaced 3 files you had edited  (copies in ~/.carter/backups/<timestamp>/)`).
A row that does not fit the terminal width is split over two lines; nothing is cut. `-v` also lists
every file. Safe to re-run. It also
creates `~/.carter/config.toml` on a first install; an existing file is never rewritten. A key in it
that Carter doesn't read is named at the end, once, with its file
(``⚠ unknown key `x.y` in <path> → delete it``). If your global `AGENTS.md` has your own edits, it is
left alone and reported as user-modified.
See [Install](../guides/install.md#upgrade) and [MCP servers](../guides/mcp-servers.md).

## carter uninstall

Remove the Carter OpenCode install: agents, skills, global rules, unedited knowledge
files, the MCP servers Carter ships (`carter-github`, `carter-terraform`, `carter-atlassian`) and
the install manifest, `~/.carter/run/` and a `config.toml` that holds only defaults. An agent you
edited is removed too, after a copy to `~/.carter/backups/<timestamp>/` (it carries guard rules that
no longer apply), and reported. Edited skills, global rules and knowledge files, memories, secrets,
backups and the audit log are kept. Directories Carter made and left empty go. Without a manifest it
removes only the agent and skill files this version ships, by name and only while their content is
what this version ships (an edited one stays and is listed); your own `carter-*` skills, agents and
MCP servers stay.

| Option | Description |
|--------|-------------|
| `--keep-guards` | Leave the per-agent denies, the agent rules, include line and guard state in place |
| `-v`, `--verbose` | Show every file removed or kept |

It asks nothing. Unless `--keep-guards` is given, uninstall first removes the policy guards it
installed, only where it is unchanged since (anything you edited is kept and reported), then the
LLM identity files. An agent shell keeps both. A guard problem is printed and makes the exit code 1
but never stops the rest of the removal. Workspaces are never touched; the ones recorded by
`carter init` and `carter update` in `~/.carter/workspaces` are listed with a ready-to-run `rm`
line for their `carter-*` agent files.

It ends with a report (skills are counted as directories):

```text
Carter uninstall  v0.19.2

✓ Removed
    guards
    agents            8
    skills           25
    plugin
    AGENTS.md
    MCP servers       2
    knowledge files   4
    config.toml          was all defaults

! Removed although you edited them
    ~/.config/opencode/agents/carter-pm.md
      → copy: ~/.carter/backups/20261112T101500/.config/opencode/agents/carter-pm.md

· Kept, because they are yours
    ~/.config/opencode/skills/carter-adr/SKILL.md          you edited it
    ~/.carter/memories/                                12  your notes
    ~/.carter/backups/                                  4  copies of files Carter replaced

· Workspaces, not touched  (Carter files you can remove)
    ~/src/proj   rm /home/u/src/proj/.opencode/agents/carter-*.md
    also yours to delete: .carter/, AGENTS.md, .github/workflows/carter-review.yml

✓ Uninstalled
→ last step, remove the command     uv tool uninstall carter-ai
→ to delete everything Carter kept  rm -r /home/u/.carter
```

Empty sections are not printed; with nothing installed it is the header, `✓ Uninstalled  nothing
was left to remove` and the last step. The `!` section goes to stderr (a `carter uninstall > file`
leaves it on screen); everything else is stdout. The command that removes the program depends on
where Carter runs from: `uv tool uninstall`, `pipx uninstall`, `brew uninstall` or
`pip uninstall carter-ai`. The `rm` lines use absolute, shell-quoted paths. Without an install
record, a section tells you that agents you had edited were removed without a copy. `-v` lists every
file removed or kept.

## carter init

```text
carter init [OPTIONS] [TARGET_DIR]
```

Create `.carter/`, `.opencode/agents/` and `AGENTS.md` in `TARGET_DIR`. Existing
files (`carter.yaml`, knowledge files, `AGENTS.md`) are not overwritten.

| Option | Description |
|--------|-------------|
| `--single` | Single-repository mode; also adds `.carter/` to `.gitignore` (default: umbrella) |
| `--no-git-state` | Don't create the private Git repository in `.carter/` |
| `--name TEXT` | Workspace name (default: directory name) |
| `--agent-suffix TEXT` | Agent name suffix (default `local`; `''` for none) |
| `--profile [budget\|quality]` | Cost profile. Default: the shipped per-agent tiers |
| `--docs-language TEXT` | Language for Carter's own notes, e.g. `es`, `pt-BR` (default `en`) |

## carter update

```text
carter update [--dry-run] [-v] [TARGET_DIR]
```

Regenerate the `carter-*` agent files from `.carter/carter.yaml`. `AGENTS.md` is
created only if missing; if its commit rule is out of date, `update` says so and prints the
current rule without rewriting the file. `--dry-run` lists the files without writing them.

`update` is also the only place that applies the `identity` policy of `carter.yaml`
(`role` and `require_tier`, see [Configuration](configuration.md#identity)). It pins the
values in `~/.carter/config.toml` under `[workspaces."<path>"]`, refreshes the hook tier and the
`allow_project_opencode_edit` opt-outs (the agents' rules are re-rendered from `config.toml`), and
asks nothing; with `-v` it shows each change and its source. An agent shell never pins, writes the
mirror or refreshes the global agent files. Editing `carter.yaml` alone changes nothing until the
next `update`. It ends with the unknown-key report (each unknown key once, with its file).

| Option | Description |
|--------|-------------|
| `--dry-run` | List what would be rendered and pinned; write nothing |
| `-v`, `--verbose` | Show each change and its source |

`update` stops without pinning when `max_tier` in `config.toml` (set by hand) is below
`require_tier`, when `config.toml` holds keys Carter doesn't manage (it prints the
difference and never overwrites the file; delete the key it names), or when `config.toml` is
invalid.

## carter guard

Guards for OpenCode's Carter agents (human terminal only). They refuse in an agent shell; a
`--dry-run` run writes nothing and works anywhere. `status` is
read-only and works anywhere. Errors print as `✗ <cause>`, `→ <fix>` and the dimmed code, and exit 1.

### carter guard install

```text
carter guard install [--dry-run] [--yes] [--only GROUPS] [-v]
```

Renders the deny set into the `permissions:` of the Carter agent files (the guards apply to Carter
agents and Carter workspaces only), writes the per-agent `carter_push` denies for OpenCode's own agents
into your OpenCode config (`opencode.json` or `.jsonc`) in one atomic, verified write, installs the
Carter plugin (`~/.config/opencode/plugins/carter/`, found by OpenCode without any registration),
`~/.carter/isolation.json` and `~/.carter/run/`, and records what it owns in
`~/.carter/guard-state.json`.

It asks **one** question: a summary of three or four lines and `Install? [Y/n]` (Enter is yes). That
yes is the consent for every group it lists; a no installs nothing. `--yes` skips the question.
Groups you declined earlier stay declined and are not asked again, with one exception: while the
LLM signing is on and no commit-hook group is installed, a declined `hooks` (or
`repo_hooks` on git older than 2.54) is offered again in the same question, with a line saying why.
`--only hooks` asks about a declined group on purpose. The optional `alias` group only comes with
`--only alias`. A run ends with `✓ guards installed  g2 · hooks · ...`; `-v` shows the explanation
of each group and the diff. Restart the OpenCode server after the plugin is installed.

| Option | Description |
|--------|-------------|
| `--dry-run` | Show the groups, how many rules the Carter agents would carry and the per-agent denies; write nothing |
| `-y`, `--yes` | Skip the question. Without a terminal and without `--yes` nothing is installed (a notice says so, exit 0) |
| `--only GROUPS` | Comma-separated: `g2`, `hooks`, `sudo-docker`, `read-edit-denies`, `config-edit`, `alias`, `repo_hooks`. `hooks` needs git 2.54 and `repo_hooks` is for older git (the one that does not apply is skipped). `--yes --only g2` accepts that group without the question, for scripts. `plugin` is not accepted here |
| `-v`, `--verbose` | Show the explanation of each group and the diff |

If a provider is missing after the write, the config is restored from the
backup and the command fails with `E-POLICIES-MISSING`. See
[Install: guards](../guides/install.md#guards).

### carter guard status

```text
carter guard status [--reset-b] [-v]
```

Read-only. A normal run prints `✓ guards  g2, hooks, ...` and one warning line for each
`MISSING` statement, changed file or broken include; `-v` lists the consents (a declined group says how to be asked again), each recorded statement as `loaded` or `MISSING`, file drift, and the include state.
It works with an absent or corrupt guard state and says so.

| Option | Description |
|--------|-------------|
| `--reset-b` | Clear the rejection counters instead (below) |
| `-v`, `--verbose` | List every statement, consent and file |

`--reset-b` clears the rejection counters that stop `carter_push` after
three rejections in one session family. Human terminal only (an agent shell is refused, and
nothing an agent can call resets it). See [Write operations](../guides/write-operations.md#letting-devops-ask-you-to-push).

### carter guard remove

```text
carter guard remove [--dry-run] [--only GROUPS|plugin|broker] [-v]
```

Asks nothing (the OpenCode config is backed up) and needs no terminal; an agent shell is
refused. Removes the agent rules, per-agent denies and Carter's git files, each only where it is
unchanged since Carter wrote it (anything you edited is kept and reported). Keeps
`~/.carter/secrets/gh-read.token` (with a reminder to delete and revoke it) and
`~/.carter/state/audit/`.

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would be removed; write nothing |
| `-v`, `--verbose` | List each statement and file removed or kept |
| `--only GROUPS` | Remove only these groups (and forget their consent). `plugin` removes just the plugin, `isolation.json` and `~/.carter/run/`: the agent rules, per-agent denies, hooks and the token stay, and a bare `carter guard install --yes` doesn't bring the plugin back. `broker` turns only [`carter_push`](../guides/write-operations.md#letting-devops-ask-you-to-push) off: the plugin and `isolation.json` are re-rendered without it, and the headless profile is removed. They can be combined with group names |

**Emergency rollback without Carter.** If `carter` itself is broken, delete the plugin
directory from your own terminal: `rm -r ~/.config/opencode/plugins/carter`. A running
OpenCode drops the plugin within seconds (restart the server to be sure). If git itself fails
because of Carter's git config, delete `~/.carter/gitconfig`. The OpenCode config you had
before the first install is in `~/.carter/backups/`.

## carter identity

The LLM's signing identity. `add` sets it up, `show` and `verify` look at it, `unlock` and `lock`
manage the key Carter's dedicated `ssh-agent` holds. `unlock` and `lock` read
`~/.carter/config.toml` (`[identity.signing]`), write nothing to it, and take the three OpenSSH
tools from `[identity.signing] ssh_bin_dir` (default `/usr/bin`).

### carter identity add

```text
carter identity add --login LOGIN [--ssh-public-key PATH|key::...] [--private-key PATH] [--agent-socket PATH] [--signing-program PATH] [--dry-run] [-v]
```

Sets up the LLM identity from a GitHub account **you** created and a signing key **you** registered:
Carter never creates an account, never registers a key and never reads a private key. With only
`--login` you get an LLM identity, unsigned (a `Co-authored-by` trailer); with `--ssh-public-key` you get LLM signing on
(signed commits). Give it the key's `.pub` file **or** the private key: the other path is the same
name with `.pub` added or removed (`--private-key` is only for a key stored elsewhere, and a
`key::` literal needs it, or `--agent-socket` / `--signing-program`). A key without a passphrase is
accepted without a word and the shim signs from its file; a key with one needs `carter identity
unlock` afterwards.

It checks first, with unauthenticated reads of GitHub (no token is sent): the account is a `User`,
its id is the configured one, the key is registered as an **SSH signing key** on the account and is
**not** an authentication key (`https://github.com/<login>.keys`), and it is not your own
`user.signingkey`. It needs git 2.40 or newer and OpenSSH 8.4 or newer. The private file is checked
with `stat` and the OpenSSH tools only (it exists, is a regular file, mode 0600 or tighter, and
matches the public key); Carter never reads its bytes. A `key::` literal that holds a private key is
refused without echoing a byte of it. Any failed check writes **nothing**
(`E-IDENTITY-CHECK` with the actual cause, or `E-GITHUB-UNREACHABLE` for a network, rate-limit or
server problem).

It asks nothing. On success it prints `✓ <login> · LLM signing on · SHA256:2hx1K1j22SYE…` (plus `· author`
or `· no passphrase`, and `→ next: carter identity unlock` only when the key has a passphrase) and
writes `config.toml` (the previous file is kept in
`~/.carter/backups/`), the signing shim `~/.carter/bin/carter-ssh-sign`, `allowed_signers`, and the
hook tier in `~/.carter/gitconfig`; every file is recorded with its hash and a failure puts them
all back. Running `add` again with another key is a **rotation**: the old public key moves to
`previous_public_keys`, so old commits still verify. It never writes your global git config.
`--role` writes `[identity] role` in `config.toml` (your preference; a pinned workspace role or
`CARTER_IDENTITY_ROLE` still wins). `--role author` needs LLM signing on: without a key (given now or already
configured) it is `E-ROLE-B-TIER` and nothing is written. With LLM signing already on,
`add --login <name> --role author` changes only the role. With role `author` it also reports
whether your git identity is usable and whether GitHub knows your address (asked of GitHub and `gh`
only in your own terminal; a dry run caches nothing).

| Option | Meaning |
|--------|---------|
| `--login LOGIN` | The LLM's GitHub login (a User account). Required. |
| `--ssh-public-key PATH\|key::...` | Its signing key: the `.pub` file or the private key (the other is derived), or a `key::` literal (LLM signing on). |
| `--private-key PATH` | The private key, if it is not next to the `.pub`; stored, never read. |
| `--agent-socket PATH` | A password manager's agent socket, instead of Carter's agent. |
| `--signing-program PATH` | A signing program such as `op-ssh-sign`, kept behind the shim. |
| `--role co-author\|author` | `co-author` (default): you author, the LLM commits. `author`: the LLM authors and you are credited by a trailer (only with LLM signing on; not for DCO repositories). |
| `--dry-run` | Run every check, show the plan, write nothing. Works anywhere, an agent shell too. |
| `-v`, `--verbose` | Show the files and notes of the plan. |

Writing is refused in an agent shell (`E-HUMAN-TERMINAL`); a terminal is not needed.

### carter identity show

```text
carter identity show [-v]
```

Read-only and allowed anywhere. Prints the identity, the role and where it came from, the
configured and effective tier with the workspace cap, the commit shape that follows, and, with LLM signing on, the
key's fingerprint, the agent state (`ok`, locked, `wrong-key`, stale), whether the signing helper is Carter's
and names the configured socket, whether the hook tier the guard reads agrees with `config.toml`,
and the guard and policy coverage for the current directory. It prints names, ids and fingerprints,
never a key or a token. A defect in `config.toml` is `E-CONFIG`, never a silent default. The exit
code is 1 if a line is `RED`. With no passphrase on the key the agent line says the signing helper signs from
the key file.

| Option | Meaning |
|--------|---------|
| `-v`, `--verbose` | Reserved: `show` prints every line already. |

### carter identity verify

```text
carter identity verify [--remote OWNER/REPO] [--sha SHA] [--commit REV] [-q] [-v]
```

Without options it signs one commit in a temporary repository with the real shim and the loaded
key, checks it against a temporary `allowed_signers` (the current key and the previous ones) and
checks the shape: the author is not the LLM, the committer is, the signer is the stored
fingerprint, the trailer is in the message. No network. A locked key (`E-SIGN-LOCKED`) is
reported, never prompted for, and exits 1; so do the wrong key loaded, a signing helper naming another socket
and a changed fingerprint, each with its own message. With `--remote OWNER/REPO --sha SHA` it asks
GitHub (unauthenticated) whether that commit shows as Verified; an unreachable GitHub is
`E-GITHUB-UNREACHABLE`, never a pass.

| Option | Meaning |
|--------|---------|
| `--remote OWNER/REPO` | Ask GitHub about one commit (with `--sha`). |
| `--sha SHA` | The commit to ask about (with `--remote`). |
| `--commit REV` | Check that a local commit is signed by the LLM key, against Carter's own `allowed_signers` (no `allowedSignersFile` setting is needed). |
| `-q`, `--quiet` | Print nothing; the exit code says it (0 = good). The agent's way to check its commit. |
| `-v`, `--verbose` | Show every check, not just the problems. |

### carter identity remove

```text
carter identity remove [--dry-run] [-v]
```

Takes back what `add` wrote, and only what is still unchanged (each file is recorded with its hash;
an edited one is kept and listed). In this order: the key leaves Carter's agent and the agent
stops (never `ssh-agent -k`), the `[identity]` and `[identity.signing]` parts of
`~/.carter/config.toml` (a copy goes to `~/.carter/backups/`; workspace pins and the footer stay;
a file that held only the identity is removed), the shim, `allowed_signers`, the socket directory,
and the hook tier with its workspace caps. It then prints **what stays**: the guards, hooks,
policies and the `git ai-commit` alias (`carter guard remove` takes those), the read-only GitHub
token, the account and the registered key on GitHub, and your private key file.
`carter guard remove` and `carter identity remove` are independent: either order works, and each
leaves the other's files. `carter uninstall` runs both. It asks nothing and needs no terminal
(the config is backed up first); it refuses in an agent shell (`E-HUMAN-TERMINAL`).

| Option | Meaning |
|--------|---------|
| `--dry-run` | Show what would be removed; change nothing. Works anywhere. |
| `-v`, `--verbose` | List each file removed or kept. |

If `carter` itself is broken: deleting `~/.carter/gitconfig` restores plain git, and deleting
`~/.carter/bin/carter-ssh-sign` makes agent commits fail (they are never made unsigned).

### carter identity unlock

```text
carter identity unlock [--ttl DURATION] [--extend]
```

Starts Carter's own `ssh-agent` if it is not running (socket `$XDG_RUNTIME_DIR/carter/agent.sock`,
else `~/.carter/run/agent.sock`; on macOS `$TMPDIR/carter-<uid>/agent.sock`; directory 0700,
socket 0600) and loads the LLM key into it with `ssh-add` (`-t` only when you pass `--ttl`). `ssh-add` asks for the key's
passphrase on your terminal; Carter never sees it. Run it in your own terminal, **not** in
OpenCode's: it refuses in any agent shell and anywhere `OPENCODE_TERMINAL` is set (the integrated
terminal included, `E-UNLOCK-OPENCODE`), and without a terminal on stdin and stderr
(`E-UNLOCK-TTY`). It is only for a key **with** a passphrase (or a password manager): a key without
one is signed from its file and says "nothing to unlock".

| Option | Meaning |
|--------|---------|
| `--ttl DURATION` | Keep the key loaded this long, e.g. `8h` or `30m`. Without it (and without `[identity.signing] ttl`) the key stays loaded until you lock it. |
| `--extend` | Ask again and replace the lifetime of a key that is already loaded. |

A key that is already loaded is not asked for again ("already unlocked"). A wrong passphrase is
`ssh-add`'s own retry; an empty line ends it. If a stale socket or an orphaned agent is left from
a crash, `unlock` replaces it; a path that is not an agent socket is never touched
(`E-UNLOCK-PATH`). With a password manager (`agent_socket` or `program`) it prints that the key is
managed there and does nothing.

### carter identity lock

```text
carter identity lock [--all]
```

Removes only the LLM key from Carter's agent (already absent is a success) and stops the agent
when it is empty. `--all` also stops Carter's agent when other keys are loaded and any leftover
agent that names the same socket directory. Agent commits fail with `E-SIGN-LOCKED` until the next
`unlock`. It refuses in agent shells like `unlock` but needs no terminal, so a logout script can
call it.

## carter commit

```text
carter commit [GIT COMMIT ARGUMENTS...]
```

`git commit` with the LLM identity, for your own terminal (agents commit through the plugin's
environment, which does the same). It has no options of its own: every argument goes to
`git commit` as typed (`-m`, `--`, quotes, empty strings), and `git ai-commit` is the same command
as an alias. The exit code is git's.

- **LLM signing on, key loaded:** you stay the author (your git identity), the committer and signer are the LLM
  (`%G?` is `G`, `git verify-commit` is good), and `Co-authored-by: <login> <noreply address>` is
  added once. `--amend` keeps the author and date and signs again as the LLM.
- **LLM signing on, key locked:** at your terminal nothing is asked. It prints `✗ key locked → carter identity unlock`
  and the commit is made **unsigned** with the trailer; `E-SIGN-HUMAN-FALLBACK` says it shows Unverified. In an agent shell it is refused (`E-SIGN-AGENT-REFUSE`) and your changes stay
  staged.
- **LLM identity, unsigned:** unsigned, you as author and committer, with the trailer (`E-COMMIT-NO-KEY`). **No LLM identity:**
  unsigned, with `Assisted-by: Carter`. A workspace `max_tier` lowers the tier for commits made
  there. An unmet `require_tier` is `E-TIER-REQUIRED`; a broken `config.toml` is `E-CONFIG`. **The
  role is ignored here**: you are always the author, a role `author` configuration changes nothing
  and the command says "role not applied (own terminal)".
- **Your own key is never used.** `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `GIT_CONFIG_*` and your
  `SSH_AUTH_SOCK` are not passed on, unsigned commits are made with signing switched off and every
  `gpg.*.program` set to `false`, and a bare `-S` or `--gpg-sign` is dropped with a note.
- **Refused**, never skipped or passed on (use plain `git commit` for these): `--no-verify`, `-n`, `--no-gpg-sign`, `-S<key>`,
  `--gpg-sign=<key>`, `-s`, `--signoff` and `--author` (exit 2). `-a` and `--reset-author` pass.

### git ai-commit

The optional `alias` group of `carter guard install` (never part of a bare `--yes`; ask for it with
`carter guard install --only alias`) adds `alias.ai-commit = !cd "${GIT_PREFIX:-.}" && carter commit`
to `~/.carter/gitconfig`, unless you already have an `alias.ai-commit`. Git appends the arguments
itself, so they arrive once and the command runs from the directory you typed it in.

## carter github-token

The read-only GitHub token that the `carter-github` MCP server reads (create it as described
in [MCP servers](../guides/mcp-servers.md#the-github-token)). Both commands refuse in an agent
shell and print at most the first four characters of a token in an error.

### carter github-token set

```text
carter github-token set
```

Reads one fine-grained `github_pat_` token from standard input (a hidden prompt on a
terminal, or a pipe) and stores it in `~/.carter/secrets/gh-read.token` (directory 0700, file
0600, written atomically), then records the path under `[github] read_token_file` in
`~/.carter/config.toml`. It prints `✓ token stored` and `→ next: carter github-token check`. It
takes no arguments, so the token never reaches your shell history, and stderr must be a terminal. Classic (`ghp_`), OAuth (`gho_`), user, server and refresh
tokens are refused with `E-PAT-TYPE`.

### carter github-token check

```text
carter github-token check [-v]
```

Checks the stored token: the file (0600, yours, not a symlink, outside any repository:
`E-PAT-PERM`), that GitHub accepts it and that it is a fine-grained token, its expiry (a
warning within 14 days) and two permissions, each with an empty or impossible request on a
repository you own (or `[github] probe_repo`); its name is never printed.

- **Contents write is a failure.** The check asks GitHub to create a branch at an all-zero
  commit, which no token can complete. "Resource not accessible" means the token cannot push;
  any other answer is red. With no repository of yours visible the probe is skipped (INFO).
- **Pull requests write is wanted:** the check posts an empty body to the pull-request
  endpoint, which can never create anything. A validation error (HTTP 422) means the token may
  open PRs (`✓ agents can open PRs`); "Resource not accessible" is a warning, not a failure:
  ``⚠ agents can't open PRs → add "Pull requests: write" to the token``.

It makes four requests (`GET /user`, `GET /user/repos`, the two probes) to `$GITHUB_API_URL`
(default `https://api.github.com`; plain http only for loopback). Exit 1 if anything is red. It
cannot tell whether the token covers "All repositories"; it prefers a narrow selection (only the
repositories Carter works on) and says so.

## carter push

```text
carter push [--dry-run] [--set-upstream] [-v]
```

Pushes `HEAD` to the same-named branch on `origin`, after checks, and asks nothing. For a human
only: run it in your terminal or as `!carter push` in OpenCode (the plugin tags that shell as yours;
no terminal is needed). It refuses in an agent shell before running any git command. There are no
other options and no arguments: no force, no tags, no other remote or refspec.

| Option | Description |
|--------|-------------|
| `--dry-run` | Run every check and show what would be pushed; push nothing |
| `-u`, `--set-upstream` | Set `origin/<branch>` as the upstream |
| `-v`, `--verbose` | List the commits, the files and git's own output |

In order: repository and SSH settings that could run code with your credentials are named in
one warning line (and the push goes on); the target ref is fetched; the commits are counted and
the files and hook or CI paths checked; signatures of LLM-committed commits must verify
(`E-B-UNSIGNED`, the one refusal that follows from the commits). Then it pushes and prints
`✓ main → origin · 1 commit (signed)`. Repository hooks are not run. See
[Write operations](../guides/write-operations.md#pushing-and-pull-requests).

## carter ci

Review-only CI. Guide: [Review-only CI](../guides/ci-review.md).

### carter ci install

```text
carter ci install review [--comment] [--dry-run] [--force] [-v]
```

Writes `.github/workflows/carter-review.yml` in the repository that contains the current
directory, and nothing else. **Own terminal only**: it refuses in an agent shell and, unless
`--dry-run`, in a shell without a terminal. It never overwrites a file you edited (the file starts
with a hash line over the rest); it refreshes an unedited one.

| Option | Description |
|--------|-------------|
| `--comment` | Opt in to a pull request comment: a second job with `pull-requests: write` (widens the scope; the installer says so) |
| `--dry-run` | Print the workflow and write nothing |
| `--force` | Replace a file that was edited by hand |
| `-v`, `--verbose` | Show the steps that follow (environment, secret, CODEOWNERS) |

### carter ci review

```text
carter ci review [--comment]
```

What the workflow runs. Reads `LLM_API_KEY`, `CARTER_CI_BASE_SHA` and optionally `CARTER_CI_KEY_ENV`,
`CARTER_CI_MODEL`, `GITHUB_STEP_SUMMARY`, `GITHUB_EVENT_PATH` and `CARTER_CI_COMMENT_FILE`; runs a
read-only OpenCode and writes the review to the summary. Exit 0 for a completed review (or a skip
in CI when the key is absent), 1 for a driver failure. `--comment` also prints the review body.

### carter ci check

```text
carter ci check FILE
```

Checks a workflow file against the review-only rules: `pull_request` only, `contents: read`, no
`write` outside the documented comment job, SHA pins, timeout, concurrency, no persisted checkout
credentials, the secret only in a step's `env`, no `${{ }}` in `run:`. Exit 1 when a rule is broken.

## carter check

```text
carter check [--no-harness] [--host | --probe] [-v] [TARGET_DIR]
```

With `--host`, check this machine instead of a workspace (read-only, names only; see
[below](#carter-check---host)). With `--probe`, check that this very agent shell is isolated
(see [below](#carter-check---probe)); `--probe` and `--host` exclude each other.

Validate a workspace. Exits with status 1 and lists the problems if any check fails:

- agent files, `AGENTS.md` and knowledge files exist;
- each agent's `permissions` and `model` match what `carter.yaml` generates;
- plans and the session checkpoint follow their [schemas](frontmatter.md);
- OpenCode loads every agent with the same description, model and rules.

The last step runs `opencode debug agents`, which starts OpenCode's background
service if it isn't running and leaves it running. It first waits until the newest
agent file is 1.5 s old. A stale or failed result is retried, up to 5 attempts with
0.5, 1, 2 and 4 s pauses. A single call that takes longer than 30 s fails the check
at once, without retrying. It is
skipped with a warning when `opencode` isn't on `PATH`; `--no-harness` skips it on
purpose.

On success, `carter check` prints `✓ Workspace OK` and, above it, one line naming the pinned models,
because Carter can't verify that your provider offers them (`-v` adds the role behind each model).
On failure every `✗` line has its `→` fix and the run ends with `✗ workspace: N problems`.

### carter check --host

Checks the guards on this machine. It never writes and never prints environment values,
tokens or provider settings. It first prints `checking GitHub...` on stderr (always, even when no
token or identity is configured), because the GitHub checks (the token and the identity's keys) can
take a few seconds; they run alongside the local checks. A normal run prints the warnings (`!`) and problems (`✗`, each with
its fix) and one summary line (`✓ host  2 warnings`); `-v` prints every row as `✓` OK, `·` INFO,
`!` WARN or `✗` RED. The exit code is 1 only if something is red:

- every policy Carter owns is loaded by OpenCode (`E-POLICIES-MISSING` names the missing
  one), your providers are still loaded, and the agents' `carter_push` denies are still in the config;
- the files recorded in `guard-state.json` match their hashes;
- **first, before any git or OpenCode call:** Carter's included git config parses (a
  malformed one makes every git command fail; the report still completes);
- the git include line is present (or, for a dotfile-managed config, the line to add), and
  git lists the `pre-push` hook as `global`; on git older than 2.54 each repo in scope
  (current directory, workspaces) is `guarded` or `unguarded: <reason>`, a WARN that is a
  FAIL while LLM signing is on;
- the plugin directory and `isolation.json` match their recorded hashes and each other (the
  hash baked into the plugin); each OpenCode server's plugin state from
  `~/.carter/run/plugin-status/<pid>.json` (working, waiting for the first agent command, or its own check failed), a server on
  another OpenCode version or older than the plugin file ("restart the server"), and plugin
  files Carter did not write, listed by name;
- the server environment, by name only: variables that show the server was started from an agent
  shell, or that Carter sets in agent shells, and `GH_TOKEN`/`GITHUB_TOKEN` in the OpenCode server's
  environment;
- [`carter_push`](../guides/write-operations.md#letting-devops-ask-you-to-push) (the `push tool` rows): on or off,
  the headless profile, the audit store (modes, counts of decisions, nothing else), the rejection counters,
  a persisted auto-accept or an OpenCode started with `--auto` (`carter_push` is refused there),
  whether the server's environment and SSH agent would be accepted, an HTTPS `origin`, and
  `git`/`gh`/`ssh` not owned by root;
- every agent's effective `carter_push` rule from `opencode debug agents`
  (`RED` names the agent; an agent whose config entry OpenCode dropped gets a hint);
- OpenCode and git version bands (`E-OPENCODE-VERSION`, `E-GIT-OLD`);
- the limits: a shell command can still write config files outside Carter's own control paths;
- the read-only GitHub token, if you stored one: its file, type, expiry and that it cannot
  write (the same checks as [`github-token check`](#carter-github-token-check)), and that the
  `carter-github` MCP entry reads the token file;
- declined groups, active `allow_project_opencode_edit` opt-outs, project config that can run
  code, and `carter.yaml` policy that `carter update` has not pinned yet;
- **the LLM identity** (when one is configured): the hook tier in `~/.carter/gitconfig`
  against `config.toml` (`RED` when they sit on opposite sides of LLM signing on and off, because agent commits then
  fail; `WARN` otherwise, with "run `carter update`"), each workspace cap (`RED` when missing or
  malformed: a malformed one makes git fail inside that workspace), linked worktrees where the
  cap does not follow the path (`WARN`, by path), and, with LLM signing on, the signing helper (unchanged, and the
  socket it names), the agent state (a locked key is `INFO`: "agent commits will fail until you
  unlock"; the wrong key or a stale socket is `WARN`), `allowed_signers`, whether the key is
  absent from `https://github.com/<login>.keys` (`RED` if it is an authentication key; `INFO`
  "not checked" offline; no token is sent) and listed as a signing key (`WARN` if not), the four
  hook events, an older git on the machine, and git 2.40 or newer (`E-GIT-OLD`). LLM signing on with no commit
  hooks installed is `RED`, and the fix names the group (`carter guard install --only hooks` when
  you declined it);
- **role `author`**: without LLM signing or under a cap it is `RED` (`E-ROLE-B-TIER`); with it on, your git identity in the
  current directory (`RED` with `E-HUMAN-IDENTITY` and a short reason if unusable), whether GitHub
  knows your address (`WARN` if not; the lookup runs in your own terminal and is cached for 7
  days, in an agent shell only the cache is read), a DCO file in the repository (`WARN`), a
  precedence conflict (`WARN`), and an out-of-date commit hook script (`RED`). Your name
  and address are never printed.

Without the plugin the check says "plugin not installed" (never a pass).

A run that prints a URL or other text from OpenCode is a bug: Carter runs OpenCode without a
terminal and captures everything it writes.

### carter check --probe

Run it **inside an agent shell** (ask your agent to run it); it refuses elsewhere with
`E-PROBE-SCOPE`. It prints one line per probe, `PASS`, `FAIL` or `SKIP`, then the name, and
exits 1 on any `FAIL`. Nothing else is printed: no environment value, no token and no path
outside `~/.carter`. Probes: `ssh_agent_absent`, `ssh_denied` (offline is `SKIP`),
`gh_pat_only`, `push_refused`, `commit_unsigned`, `agent_tagged`.

## carter gate

### carter gate check

```text
carter gate check [--json] [--cwd DIR] [--skip-groups GROUPS] [COMMAND]
```

Asks the command gate what it would do with COMMAND (or the text on standard input), without
running it. The same code the plugin calls for every agent shell command. Read-only, so it
works anywhere, agent shells included. Exit 0 means allowed, 1 means refused (a message naming
the rule is printed).

| Option | Description |
|--------|-------------|
| `--json` | Print the gate's reply as JSON: `decision`, `rule`, `message` |
| `--cwd DIR` | The directory the command would run in (relative paths and git aliases are resolved there) |
| `--skip-groups GROUPS` | Comma-separated consent groups you declined, as `isolation.json` records them: their rules are skipped |

## carter save

```text
carter save [-m MESSAGE] [TARGET_DIR]
```

Commit everything in `.carter/` to its private repository (`.carter/.git`), so a
deleted plan or checkpoint can be recovered. Your Git identity is the author. Prints
`nothing to save (no changes, or git state is off)` when there is nothing to do.

| Option | Description |
|--------|-------------|
| `-m`, `--message TEXT` | Commit message (default: `chore: checkpoint state (<timestamp>)`) |

## carter ops

```text
carter ops {audit|policy-override|config --emit [--field NAME]} [--key value ...]
```

A small helper for the [`ops:` flow](../guides/write-operations.md). It doesn't run
Git or GitHub commands itself. Output is JSON on stdout; errors go to stderr. Exit
code 0 means success, 1 a usage or validation error. `carter ops --help` prints
the usage.

### carter ops config --emit

Print, as JSON, the attribution the agents must use right now. `--field NAME` prints just that one
value as plain text (an agent reads `coauthor_trailer` or `commits` without printing the rest).
The values are resolved when you run it, from `~/.carter/config.toml` and the environment:

| Key | Meaning |
|-----|---------|
| `tier` | `t0` (nothing configured), `t1` (LLM account, no key) or `t2` (account and key) |
| `role`, `role_source` | `co-author` or `author`, and where it came from (`workspace`, `env`, `config`, `default`) |
| `author`, `committer` | `human` or `llm`: who git records. The author is `llm` only in role `author` with LLM signing on |
| `signer_fpr` | The LLM key's public fingerprint when LLM signing is on, else empty |
| `coauthor_trailer` | The trailer line for commit messages: `Assisted-by: Carter` with no LLM identity, `Co-authored-by: <login> <noreply address>` otherwise; in role `author` it is **your** line, `Co-authored-by: <user.name> <user.email>` |
| `coauthor_linked` | Whether GitHub credits that trailer (from the cache; role `author` needs your address linked) |
| `mode` | `interactive`, or `review` in a CI review run ([Review-only CI](../guides/ci-review.md)) |
| `commits` | `allowed` or `refused` |
| `refusal_reason` | The error code when `commits` is `refused` (for example `E-CONFIG`, `E-ROLE-B-TIER`, `E-HUMAN-IDENTITY` or `E-CI-REVIEW`) |
| `footer` | Text appended to GitHub and Jira bodies |
| `has_github_token` | Whether `GITHUB_TOKEN` is set in the environment (the token file is not counted) |

An invalid `config.toml` gives `commits: refused` with `E-CONFIG`: agent commits stay off
until it is fixed. Carter never reads your signing key.

### carter ops audit

Append one entry to `~/.carter/state/audit/audit.log` after an operation. It prints nothing on success.

| Option | Required | Description |
|--------|----------|-------------|
| `--operation NAME` | yes | Operation name, e.g. `git-flow` |
| `--result success\|failure` | yes | Outcome |
| `--params JSON` | no | Inputs, e.g. `'{"branch":"feature/x"}'` |
| `--identifiers JSON` | no | Results, e.g. `'{"commit_sha":"abc1234"}'` |

### carter ops policy-override

Record a deliberate exception to a [permission rule](../guides/safety-and-permissions.md#record-an-exception).
It records the decision; it doesn't change any rule. Every entry is stored with
`"authorized": false`.

| Option | Required | Description |
|--------|----------|-------------|
| `--category` | yes | `read`, `local-write`, `remote-write` or `dangerous` |
| `--action` | yes | The exact action, up to 500 characters |
| `--tier` | yes | `native-deny` (you relaxed a deny), `native-ask` (you confirmed a prompt), `prose-backstop` (only agent guidance applied, e.g. the Narrator review) |
| `--reason` | no | Why, up to 500 characters. Never put secrets here |
