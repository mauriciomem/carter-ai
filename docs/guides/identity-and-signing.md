# Identity and signing

This guide explains how Carter can give your AI agents **their own identity** in git: a
GitHub account of their own and a key that signs the commits they make. You stay the author
of everything; the agent is credited, and its commits can be proven to come from its key.

You do not need any of this to use Carter. Without it, agent commits use your own git
config, are unsigned, and carry a `Co-authored-by` or `Assisted-by` line. Read on if you
want commits that GitHub can show as signed by the agent's own account.

> [!NOTE]
> Everything here runs on your machine, in your own terminal. Carter never creates a GitHub
> account, never registers a key for you, and never reads or stores a private key or a
> passphrase. You make the account and the key; Carter checks them, wires them up, and
> keeps the key's lock for you.

## The idea in one minute

- **You** are the *author* of a commit (your name, from your `git config`).
- **The agent's identity** (call it "the LLM account") is the *committer*, and the commit is
  *signed* with the LLM's own SSH key.
- GitHub then shows "you and the LLM" on the commit and, when the key is registered, the
  green **Verified** badge.
- The LLM's key can sit behind a **passphrase**. Then you *unlock* it in your own terminal
  once. While it is locked, agent commits **fail** (they never fall back to unsigned) and
  your changes stay staged. A key without a passphrase is signed from its file and needs no
  unlock.
- Your own key is never used for any of this.

## Roles

| Role | Author | Committer and signer | Trailer | Status |
|------|--------|----------------------|---------|--------|
| `co-author` (default) | you | the LLM account, with its key | `Co-authored-by: <LLM login> <noreply address>` | available |
| `author` | the LLM account | the LLM account | `Co-authored-by: <you>` | available at T2 only; [see below](#role-author-the-llm-is-the-author) |

The default is the one most people want. Role `author` is for when you want GitHub to show the LLM
as the author of its work and to credit you as the co-author. You choose it later, on purpose.

## Tiers: what is configured, and what a stranger sees

| Tier | What you configured | Agent commit | What GitHub shows |
|------|---------------------|--------------|-------------------|
| **T0** | nothing | you as author and committer, unsigned, `Assisted-by: Carter` | your commit; no badge |
| **T1** | the LLM account only (`carter identity add --login <name>`) | you as author and committer, unsigned, `Co-authored-by: <LLM>` | your commit, with the LLM as co-author |
| **T2** | the account **and** its signing key | you as author, the LLM as committer, **signed** by the LLM key, `Co-authored-by: <LLM>` | "you and the LLM"; Verified (see the table below) |

Two rules protect you from surprises:

- Below T2 an agent can **never** sign: a bare `-S`, `--gpg-sign` or `git tag -s` fails
  instead of reaching your own key.
- At T2 an agent commit is signed by the LLM or **fails**. It is never silently made
  unsigned.

`carter ops config --emit` prints the tier, the role and the other facts the agents read.

## Role `author`: the LLM is the author

In this role the LLM is the **author and the committer**, the commit is signed by its key, and
**you** are credited by a trailer built from your own git identity:

```text
author:     <LLM name> <id+login@users.noreply.github.com>
committer:  the same, signed with the LLM key
trailer:    Co-authored-by: <your user.name> <your user.email>
```

**How to turn it on.** It needs T2 (the account and the key). Either of these:

- `carter identity add --login <name> --role author` (a role-only change when the identity already
  exists; `--role co-author` turns it back), or
- put `role: author` under `identity:` in the workspace's `carter.yaml` and run `carter update`,
  which shows the change and pins it for that workspace.

`CARTER_IDENTITY_ROLE=author` set **before** OpenCode starts chooses it for one session. The agent
cannot change the role: it cannot set variables, and the pinned file is not writable by it.

**Which source wins.** The workspace pin, then `CARTER_IDENTITY_ROLE`, then `[identity] role` in
`config.toml`, then `co-author`. If a weaker source disagrees with the winner you get a warning
(`carter identity show`, `carter check --host`), never a refusal. A role value that is not one of
the two is an error that switches agent commits off.

**It never degrades.** Role `author` is never swapped for role `co-author`, and never made
unsigned:

| Situation | What happens |
|-----------|--------------|
| Below T2, or a workspace cap (`max_tier`) | Agent commits are refused (`E-ROLE-B-TIER`). `carter update` also refuses to pin `author` next to a cap |
| The key is locked or expired | The commit fails and your changes stay staged, as in role `co-author` |
| Your `user.name` or `user.email` is empty, is the LLM's, or is one of Carter's own fallbacks | Refused (`E-HUMAN-IDENTITY`): there is nobody to credit |
| The plugin did not load, the shim changed, the config is broken | The commit fails (`E-SIGN-UNAVAILABLE`, the guard's `E-GUARD-NOIDENT`) |

**Your identity is read from git, in the folder of the commit.** The line is
`Co-authored-by: <user.name> <user.email>` exactly as `git config` reports them there, so a
`includeIf` override for a work folder is respected. Carter never invents or replaces it. A name
with odd characters (a new line, `<`, `>`) is refused rather than pasted into a message.

**GitHub must know your address, or you get no credit.** In this role the trailer is the only thing
that ties the commit to you. Carter checks it and says so:

- `yes (noreply)`: it is an `<id>+<login>@users.noreply.github.com` address and GitHub agrees on the
  account (an unauthenticated lookup);
- `yes (verified)`: it is one of the verified emails of your account (asked with `gh api
  /user/emails`);
- otherwise it is `unknown` and you get a warning. Fix it by using your noreply address as
  `user.email`, or by adding the address to your GitHub account.

The two lookups run only in **your own terminal**, from `carter identity add` and `carter check
--host`. The answer is remembered for 7 days in `~/.carter/run/coauthor-link.json` as a hash, never
as an address; `carter ops config --emit` reads that file and never asks the network.

**What GitHub shows.** The commit is shown as made by the LLM account with you as co-author, and
Verified when the LLM key is registered as a signing key. The contribution graph counts the LLM
for the commit; you count as co-author only when your address is linked. We have checked this
against GitHub's documentation, not yet on a real repository (that check is a manual step).

| The commit | Neither account in vigilant mode | LLM account in vigilant mode | Your account in vigilant mode |
|------------|----------------------------------|------------------------------|-------------------------------|
| Role `author`, signed by the LLM | Verified | Verified | Verified, or Partially verified if GitHub counts co-authors (not confirmed) |
| The same commit after **you** amend it and sign with your key | Verified | Partially verified | Verified |
| The same commit after **you** amend it without signing | no badge | Unverified | Unverified |

Both "Partially verified" and "Unverified" after a rewrite are truthful: the signature is no longer
the author's. Do not turn vigilant mode off to hide them. Let the agent do rewrites: it keeps the
original author and signs as the LLM again.

**What an agent may and may not rewrite.** `git commit --amend`, `rebase`, `cherry-pick` and
`commit -C` keep the **original author** of a commit. An agent that asks for a different author
(`--reset-author`, `--author`) is stopped: the command gate refuses the literal command, and if it
reaches git anyway the commit hook rejects it (`E-GUARD-COMMITTER`, "an agent may not change a
commit's author"). That is how a commit of yours cannot become the LLM's.

**Not for projects that check a DCO sign-off.** A DCO check compares the `Signed-off-by` line with
the commit's **author**. Carter never signs off for the LLM, so an LLM-authored commit cannot
pass such a check. `carter identity show` and `carter check --host` warn when the repository has
`.github/dco.yml`, `.github/dco.yaml`, `.dco.yml` or a `DCO` file. Use `role: co-author` there
and pin it with `carter update`. Squash-merging a pull request usually makes the PR's author the
author of the squashed commit, which undoes this role on `main`.

**`carter commit` ignores the role.** At your own terminal you are always the author and the LLM
the committer (see above); it tells you "role not applied (own terminal)".

**After an upgrade** run `carter guard install` once: the commit hook script in `~/.carter/hooks/`
is re-rendered, and `carter check --host` reports a script from an older Carter as `RED` while the
role is `author`.

## Before you start

1. **Make the LLM account.** A normal, separate GitHub *user* account (not an organization,
   not a bot app) that you own. Note its login.
2. **Make a key just for it** (a passphrase is optional; with one you `unlock` it each day,
   without one the signing shim signs straight from the key file):

   ```bash
   ssh-keygen -t ed25519 -f ~/.ssh/carter_llm -C "carter llm key"
   ```

   Do not reuse your own key. Carter refuses a key that is your `user.signingkey`.
3. **Register the public key on the LLM account as a "Signing key" only.** In GitHub:
   *Settings → SSH and GPG keys → New SSH key → Key type: **Signing Key***. Do **not**
   also register it as an *Authentication Key*: that would let the key log in as the LLM.
   `carter identity add` and `carter check --host` both check this and refuse or warn.
4. **Recommended: turn on vigilant mode on the LLM account** (*Settings → SSH and GPG keys →
   Flag unsigned commits as unverified*). The next sections explain what it does.
5. Make sure you have **git 2.40 or newer** and **OpenSSH 8.4 or newer** (the check is
   automatic; Apple's and every current Linux's OpenSSH qualify).

A few other prerequisites are good hygiene around any signing setup: give your own SSH keys
passphrases, and keep your own `gh` token free of the `admin:public_key` and `gist`
scopes. `carter check --host` reports what it can see.

## Set it up: `carter identity add`

Run it in your terminal (it refuses inside an agent shell). One path is enough: give the `.pub`
file or the private key and Carter derives the other by adding or removing `.pub`. First look
without writing:

```bash
carter identity add --login my-llm-account --ssh-public-key ~/.ssh/carter_llm --dry-run
```

It asks GitHub (no token, only public data) and checks that:

- the account exists, is a normal **User**, and has the id Carter will store;
- the key is on the account as a **signing** key and is **not** an authentication key
  (the public page `https://github.com/<login>.keys` lists authentication keys);
- the key is not your own signing key, and the private file exists, is yours and mode 0600, and
  matches the public key (checked with `stat` and OpenSSH only: Carter never reads its bytes).

If any check fails, **nothing is written** (`E-IDENTITY-CHECK` names the real cause, or
`E-GITHUB-UNREACHABLE` if GitHub could not be reached). When everything passes, drop
`--dry-run`. Carter asks nothing and prints one line, `✓ my-llm-account · T2 · SHA256:2hx1K1j22SYE…`
(with `→ next: carter identity unlock` only if the key has a passphrase). It writes:

| What | Where |
|------|-------|
| the identity and the key's public half | `~/.carter/config.toml` (the old file is kept in `~/.carter/backups/`) |
| the private key's **path** (never its content) | `~/.carter/config.toml` |
| a small signing script that only the LLM key can use | `~/.carter/bin/carter-ssh-sign` |
| the list of public keys that count as the LLM's | `~/.carter/hooks/allowed_signers` |
| the "tier mirror" the git hooks read | `~/.carter/gitconfig` |

Everything is recorded with a checksum so that Carter later removes only what is still
unchanged. If something fails half-way, every file is put back.

With only `--login` you get **T1**. Running `add` again with a different key is a
**rotation**: the old public key is remembered so that old commits still verify.

## Every day: unlock, work, lock

A key **without** a passphrase needs none of this: `identity add` saw that it opens without
one, and the signing shim signs straight from the key file (`identity show` says "no
passphrase"). `unlock` is for keys that have a passphrase, and for password-manager setups.

```bash
carter identity unlock          # in your OWN terminal; it asks for the key's passphrase
```

- Carter starts its own small `ssh-agent` and loads the key into it. It stays loaded until you
  lock it; ask for a lifetime with `--ttl 2h` (or `[identity.signing] ttl`). Run
  `unlock --extend` to renew the clock.
- The passphrase goes straight to OpenSSH's `ssh-add` on your terminal. Carter never sees it.
- `unlock` refuses inside OpenCode, on purpose: in an agent shell, in the `!` prompt and
  in the integrated terminal (`E-UNLOCK-OPENCODE`). Open a terminal OpenCode did not start.
- A key without a passphrase can be used by any program of yours that can read the file:
  give the LLM its own key, with no other use, and keep it mode 0600.
- `carter identity lock` removes the key from the agent and stops the agent.
  `lock --all` also stops a leftover agent. Locking an already locked key is fine.

What the **agent state** line of `carter identity show` means:

| State | Meaning | What to do |
|-------|---------|------------|
| ok | the key is loaded | nothing |
| locked / not running | the agent holds no key (it was never unlocked, expired or was locked) | `carter identity unlock` |
| wrong key | the agent holds other keys but not the LLM's | `carter identity lock --all`, then `unlock` |
| stale | the socket does not answer (a crashed agent) | `carter identity lock --all`, then `unlock` |
| something else at the socket path | a file that is not our socket | Carter never touches it: remove it yourself |

## What the agent does when the key is locked

The agent's commit fails with git's own message (for example `error: Couldn't find key in
agent?` followed by `fatal: failed to write commit object`). **Nothing is committed and your
changes stay staged.** The agent stops, tells you to run `carter identity unlock` in your own
terminal, and retries once only when you ask. It will not try another way: no `--no-gpg-sign`,
no other committer, no other key.

## Committing yourself: `carter commit`

`carter commit` is `git commit` with the LLM identity, for your own terminal:

```bash
git add src/auth.py
carter commit -m "feat(auth): add token refresh"
```

- Key unlocked: you are the author, the LLM is the committer and the commit is signed.
- Key locked, at a terminal: Carter asks **once** if you want to unlock now. If you say no
  (or there is no terminal), the commit is made **unsigned**, with the `Co-authored-by` line,
  and says so. Your own key is never used. See the Unverified badge in the table below.
- It passes everything else straight to `git commit` (`-a`, `--amend`, `-F`, `--`, paths).
  It never accepts `--no-verify`, `-n`, `--no-gpg-sign`, `-S<key>`, `--gpg-sign=<key>`, `-s`,
  `--signoff` or `--author`; for those use plain `git commit`.
- `--amend` keeps the author and the date and signs the new version as the LLM.

For `git ai-commit`, opt in with `carter guard install --only alias`. It is the same command
under a git alias (and is never part of a bare `--yes`). Agents do not use it.

## The vigilant mode table

GitHub's *vigilant mode* decides how **unsigned** commits are labelled, per account, at the
time you view them. The columns are the settings of the two accounts.

| The commit | Neither account on | LLM account on | Your account on |
|------------|--------------------|----------------|-----------------|
| Agent commit signed by the LLM (T2) | Verified | Verified | **Partially verified** |
| Unsigned commit crediting the LLM (T1, `carter commit` after you said no to unlock) | no badge | **Unverified** | **Unverified** |

How to read it: with *your* account's vigilant mode on, every LLM-signed commit shows
"Partially verified" (it still satisfies a "Require signed commits" rule). With the *LLM*
account's mode on, any commit that credits the LLM without its signature shows "Unverified",
which is the truthful label. Carter recommends the LLM account's mode **on**; whether to turn
yours on is your call (it also changes how your own commits look).

## Merge strategy: what happens to the signature

Carter does not choose your merge strategy. This is what each does to an agent commit's
signature and trailer:

| How the PR lands | The LLM signature | The `Co-authored-by` trailer |
|------------------|-------------------|------------------------------|
| Merge commit | kept on each commit; the merge commit is signed by GitHub or by you | kept |
| Squash and merge | dropped (the new commit is GitHub's) | kept only if the squash message keeps it |
| Rebase and merge (the button) | replaced (GitHub rewrites the commits) | kept in the messages |
| Rebase or amend on your machine | dropped for commits rewritten by you | kept in the message |

If you squash, the final commit on `main` is not LLM-signed whatever you configure here; the
signature still protects the branch while it is under review.

## Password managers

The key can live in a password manager's SSH agent instead of Carter's agent. Set
`--agent-socket <path>` (the manager's socket) or `--signing-program <path>` (a program such
as `op-ssh-sign`) when you run `identity add`; Carter then has nothing to unlock and the
manager asks for approval (how often depends on its settings).

- **1Password:** keep the LLM key in its own vault and list that vault in the agent's
  `agent.toml`; do not put your own keys in a vault the agent can use without per-request
  approval.
- **Bitwarden:** the same advice: a separate entry, approval on use.
- Never let a password manager's setup tool edit your git config automatically (the
  "Configure Commit Signing → Edit Automatically" button): it would point *your* git at that
  key. Set up the LLM identity only through `carter identity add`.
- With `--signing-program` Carter has **no check** of what the program signs. That is a
  residual risk of that mode (see below).

## macOS notes

- The agent's socket lives under `$TMPDIR/carter-<uid>/` (macOS limits a socket path to 104
  bytes; Linux 108). `carter identity unlock` stops with `E-UNLOCK-PATH` if the path is too
  long.
- Apple's OpenSSH in `/usr/bin` works. For a newer OpenSSH (for example Homebrew's), set
  `[identity.signing] ssh_bin_dir = "/opt/homebrew/bin"`; Carter then uses `ssh-keygen`,
  `ssh-agent` and `ssh-add` from there.
- Signing takes tens of milliseconds more than on Linux; a commit still feels instant.

## Workspace caps (`max_tier`) and `carter update`

To make agents commit **unsigned** in one workspace, set in `~/.carter/config.toml`:

```toml
[workspaces."/home/me/projects/legacy-repo"]
max_tier = "t1"
```

Then run `carter update` in your terminal. The plugin reads the file directly, but the git
hooks read a copy (the tier mirror and one small fragment per capped workspace) that
`carter update` refreshes. If the two disagree, an agent commit is rejected with a message
that says "run `carter update`" instead of silently doing the wrong thing.

> [!WARNING]
> **Worktree limit.** A linked `git worktree` follows the cap of its **main** repository, not
> of the folder it sits in. A worktree inside a capped workspace whose main repository is
> outside it is **not** capped, and the other way round. `carter check --host` lists such
> worktrees by path.

A change of `max_tier`, `role` or `require_tier` always needs `carter update` (it asks nothing).

## Where the guards watch, and the paths no hook sees

With the `hooks` group at revision 2, three git hooks check agent commits in every repository
on the machine (your own commits and pushes run nothing extra):

- `prepare-commit-msg` rejects a wrong committer, a missing identity block, a wrong signing
  setup, or a signing attempt below T2, and adds the `Co-authored-by` or `Assisted-by` line
  exactly once. Skipping verification with `--no-verify` does not skip it.
- `commit-msg` checks that the trailer is still there.
- `post-commit` only **warns** when the commit is unsigned or signed by the wrong key. It never
  undoes anything, and leaves a line in `~/.carter/run/guard.log`.

Git does not run these hooks for a few ways of making a commit: `git stash`, `git commit-tree`,
`git notes add` and `git am`; `post-commit` also does not run for a plain `--no-ff` merge
commit. The backstops are the command gate (it refuses `commit-tree` and the other plumbing
verbs in agent shells), and the check inside `carter push`: it refuses any commit whose
committer is the LLM and that has no valid LLM signature (`E-B-UNSIGNED`).

## Check and verify

```bash
carter identity show          # who is who, the key's state, the guards, nothing secret
carter identity verify        # signs a test commit in a temporary repo and checks it
carter check --host           # the whole machine: mirror, shim, agent, hooks, GitHub's key lists
```

`verify --remote <owner/repo> --sha <sha>` asks GitHub whether a pushed commit is Verified.
A locked key, the wrong key, a stale socket and a changed fingerprint each give their own
message.

## Undo

```bash
carter identity remove        # takes back what `add` wrote, only what is unchanged
carter guard remove           # the guards (hooks, agent rules, plugin), separately
```

They are independent: either order works. After `identity remove` agent commits are unsigned
again. What stays, and is yours to remove: the account and the registered key on GitHub, the
private key file, the GitHub token, the hooks and agent rules until you run `guard remove`.

If `carter` itself is broken, no tool is needed: deleting `~/.carter/gitconfig` makes git
behave as if Carter's keys were never there (a malformed file in `~/.carter/gitconfig.d/` is
deleted the same way), and deleting `~/.carter/bin/carter-ssh-sign` makes agent commits fail
(they are never made unsigned).

## Type, never paste

A line that starts with `!` in OpenCode runs in *your* shell. Type such lines yourself (`!carter
push` works there once the plugin has tagged the shell as yours); never paste
one from anywhere, because a pasted line is sent to the model instead. In the same
spirit, keep `.github/workflows/` under `CODEOWNERS` (a required review): an LLM-signed pull
request that changes a workflow file should always get a human look.

## What signing does not protect

Honest limits, so you can judge what you are getting:

- **Same-user access.** Anything that runs as you can talk to Carter's agent socket while the
  key is unlocked and ask for a signature. The passphrase, the lock and the short lifetime
  limit this; they do not remove it. An agent that evades the command gate could use it.
- **`--no-verify`** skips the `commit-msg` check; the checks in `prepare-commit-msg` and the
  signature check at `carter push` still hold. A message editor can then drop the trailer.
- **Paths no hook sees** (above) are caught only by the gate and by `carter push`.
- **The read-only GitHub token** is visible to the model, as it sits in the agent's
  environment. Give it the fewest repositories and no write permission.
- **`--signing-program` mode** has no shim check: Carter cannot see what the program signs.
- **The private key file** is protected only by its file mode (0600) and, if it has one, its passphrase. Without a passphrase, anything that runs as you and can read the file can sign as the LLM.
- **A squash merge** removes the LLM's signature from `main`.
- **The hooks do not know the role.** They check that the commit is consistent (the committer is the LLM; when the author is the LLM the trailer is yours, otherwise the LLM's). A shell that carries the LLM as author in a workspace pinned to `co-author` would still produce an honest role-`author` commit; the plugin never builds that, and the command gate forbids setting `GIT_AUTHOR_*`.
- **`--author` on a brand new commit** is stopped only by the command gate, not by the hook.

## See also

[CLI reference](../reference/cli.md#carter-identity) · [Configuration](../reference/configuration.md) ·
[Files and paths](../reference/files-and-paths.md) · [Troubleshooting](../troubleshooting.md#signing-and-the-llm-identity) ·
[Safety and permissions](safety-and-permissions.md)
