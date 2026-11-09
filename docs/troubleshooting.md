# Troubleshooting

Find your symptom, then apply the fix. If nothing here helps, open an
[issue](https://github.com/mauriciomem/carter-ai/issues).

## Installing

| Symptom | Fix |
|---------|-----|
| `carter: command not found` | `~/.local/bin` isn't on your `PATH`. Run `uv tool update-shell` and open a new terminal, or `export PATH="$HOME/.local/bin:$PATH"` |
| `opencode not found on PATH … Nothing was installed.` | Install OpenCode 2.1+ and check that `opencode --version` works in the same shell |
| `OpenCode 2.0.x is too old` | Upgrade OpenCode to 2.1 or newer |
| `uv tool upgrade` says there is nothing to upgrade | `uv tool install --force git+https://github.com/mauriciomem/carter-ai.git` |
| `⚠ … (user-modified, skipping)` for `AGENTS.md` | You (or another tool) changed `~/.config/opencode/AGENTS.md`, so Carter leaves it alone. Delete or rename it and run `carter install` to get Carter's version |

## Agents

| Symptom | Fix |
|---------|-----|
| Carter agents don't show up | Global agents live in `~/.config/opencode/agents/`, workspace agents in `.opencode/agents/`. In a workspace, run `carter check`: it names any agent OpenCode failed to load |
| I can't select Architect, Engineer, … | They are subagents. Select **carter-maestro** and ask it to use the specialist. See [Using Carter](guides/using-carter.md#pick-maestro) |
| Typing `@carter-engineer` attached nothing useful | In OpenCode, `@` attaches files. Name the agent in plain text instead |
| I see two Maestros | One is global (`carter-maestro`), one is the workspace's (`carter-maestro-local`). Use the `-local` one inside that project |
| An agent ignores my `carter.yaml` change | Run `carter update`, then `carter check` |
| `carter check`: "emitted permissions drifted …" | An agent file was edited by hand. Run `carter update` to regenerate it |
| `carter check` reports agents with different rules right after an edit | OpenCode's background service may still serve the old files. Run `carter check` again |
| A model isn't available | Your provider doesn't offer the pinned model. Change it under `models` in `carter.yaml`. See [Cost and models](guides/cost-and-models.md#change-one-agent-or-the-models-themselves) |

## Permissions

| Symptom | Fix |
|---------|-----|
| A push or a `gh` write is denied ("Blocked by configuration policy") | Expected: agents never push or write to GitHub. The work is handed to you |
| Maestro asks before every commit | Expected: Maestro has read-only permissions, so local writes ask |
| A risky command stopped asking | Someone chose "Allow always" at a prompt. Remove the saved allow rule; see [OpenCode permissions](https://opencode.ai/v2/docs/permissions/) |
| An MCP tool asks every time | Expected: MCP tools have no specific rule. Choose "Allow always" for tools you trust |

## MCP servers

| Symptom | Fix |
|---------|-----|
| `⚠ GitHub read-only token not found` during `carter install --mcp` | No token is stored. The server is still configured; run `carter github-token set` in your own terminal, then restart OpenCode |
| GitHub or Terraform server fails to start | Both run in Docker. Check that the Docker daemon is running (`docker info`) |
| Duplicate GitHub tools | You have your own `github` server and Carter's `carter-github`. Remove one |
| My `opencode.jsonc` comments disappeared | Carter rewrites the file as JSON. The original is in `opencode.jsonc.carter-backup` next to it |
| Warning that both `opencode.json` and `opencode.jsonc` exist | OpenCode loads both. Carter uses the `.jsonc`; consider merging them into one file |

## Commit attribution

| Symptom | Fix |
|---------|-----|
| The agent stops and reports `E-CONFIG` | `~/.carter/config.toml` is invalid, or a signing section is incomplete. Agent commits stay off until it is fixed. `carter ops config --emit` shows `commits: refused`. |
| The agent reports `E-ROLE-B-TIER` | The role is `author` and the workspace is below T2 (no signing key, or a `max_tier` cap). Add the key (`carter identity add`), remove the cap, or set `role: co-author` in `carter.yaml` and run `carter update` |
| The agent reports `E-HUMAN-IDENTITY` | Role `author` credits you by your git identity and it is unusable here: `user.name` or `user.email` is empty, is the LLM's address, or is a Carter fallback (the pair `Carter` with `state@carter.invalid`, or `carter-bot@…`; a person named Carter with a real address is fine). Set them in your own git config (an `includeIf` override for this folder counts). `carter check --host` names the reason |
| `E-GUARD-COMMITTER`: "an agent may not change a commit's author" | An agent used `--reset-author` or `--author` while amending a commit by someone else. Nothing was changed. Ask for a plain amend, or do it yourself |
| `carter check --host` says the commit hook script is out of date | The installed `~/.carter/hooks/carter-guard` differs from the one this Carter renders. Run `carter guard install` in your own terminal |
| `carter check --host` says your address is not known to be linked | In role `author` the `Co-authored-by` line is your only credit. Use your `<id>+<login>@users.noreply.github.com` address as `user.email`, or add your address to your GitHub account, then run `carter check --host` again in your own terminal |
| `carter update` says the identity policy was not pinned | It ran in an agent shell, which never pins. Run `carter update` in your own terminal |
| `carter install` says `AGENTS.md` is user-modified | Your global `AGENTS.md` has your edits, so Carter left it alone. Merge its Communication and Git & Language sections by hand |
| ``⚠ unknown key `…` in <file> → delete it`` | Carter doesn't read that key. Nothing was changed and no command failed; delete the key from the file it names. `carter identity add` and `carter update` refuse to rewrite `config.toml` while an unknown key is in it |

## Review-only CI

| Symptom | Fix |
|---------|-----|
| Every commit by an agent or `carter commit` fails with `E-CI-REVIEW` on your own machine | `CI` or `GITHUB_ACTIONS` is set in your shell (or `CARTER_IDENTITY_MODE=review`, or `[identity] mode = "review"`). That marks a CI review run, which never commits. Unset it: `unset CI GITHUB_ACTIONS CARTER_IDENTITY_MODE` |
| `E-CONFIG` mentioning `CARTER_IDENTITY_MODE` or `[identity] mode` | The value is not `auto`, `interactive` or `review`, or it asks for a CI context that is not built (`commit`, `scheduled`), or it is `interactive` inside a CI. The message names the key, never the value |
| `carter ci install review` says the file "was edited" | You or a tool changed `.github/workflows/carter-review.yml`; Carter keeps it. `--dry-run` shows what it would write; `--force` replaces yours |
| The review job is "skipped" on a pull request | Expected for a fork, and when the secret `LLM_API_KEY` is missing from the environment `carter-review`. The job summary says which |
| The review job fails with `CARTER_CI_BASE_SHA` or "could not diff" | The checkout must have history: keep `fetch-depth: 0` in the workflow |
| `carter ci check` reports `CI001`...`CI013` | A rule of the review-only workflow is broken; the code names it. See [Review-only CI](guides/ci-review.md) |

## Guards

| Symptom | Fix |
|---------|-----|
| `carter install` says the guards were skipped | No terminal and no `--yes`. Run `carter guard install` in a terminal |
| `E-HUMAN-TERMINAL` | The command is for you, not an agent. If you are not an agent, this shell inherited agent variables: start the terminal fresh. `carter push` also runs as `!carter push` in OpenCode |
| `E-POLICIES-MISSING: … not loaded` | OpenCode dropped a provider after a guard write (a broken config drops all of them). Carter re-reads for a few seconds first, because OpenCode's background service reloads the file a moment after it changes. `carter guard install` already restored your config from the backup; check the file with `opencode debug config`, then try again |
| After a guard write OpenCode lost a provider | The write is rolled back automatically. If it ever isn't, restore `~/.carter/backups/<timestamp>/opencode.json[c]` over your config |
| `carter check --host` says a Carter agent file's permissions differ from what Carter renders | Someone edited it (or Carter was upgraded). Run `carter guard install` (it re-renders the Carter agent files); `check --host` goes green again |
| `E-STATE-INVALID` | `~/.carter/guard-state.json` is unreadable or from a newer Carter. Carter never rebuilds it: fix or move the file, then run `carter guard install` |
| Every git command fails with "bad config line … gitconfig" | Carter's included git file (`~/.carter/gitconfig`) is malformed. Delete that file (`rm ~/.carter/gitconfig`): git works again at once. `carter guard remove` and `carter check --host` also work while git itself fails, because they read the file with your global git config switched off |
| My `opencode.jsonc` comments disappeared after the guards | Carter rewrote the file as JSON. The original is `opencode.jsonc.carter-backup` |
| `E-B-UNSIGNED` from `carter push` | A commit whose committer is the LLM has no valid LLM signature. Nothing was pushed. Re-create the commit as your own (for example by squashing), or fix the LLM signing setup |
| The agent reports `E-B-DWELL` or `E-B-TIMEOUT` | You approved in under half a second (or OpenCode auto-accepts: `--auto`, the TUI's auto-accept) or after two minutes. Approve by hand, after reading; turn auto-accept off. It counts as a rejection |
| The agent reports `E-B-REJECTED` | Three rejections (rejects, timeouts, dwell refusals, interrupts) in this session family. Start a new session, or run `carter guard status --reset-b` in your terminal |
| The agent reports `E-B-POLLUTED` | The OpenCode server was started from an agent shell or already carries Carter's isolation variables; the names are in the message. Quit it and start OpenCode from a clean terminal |
| The agent reports `E-B-NOAGENT` | The server's `SSH_AUTH_SOCK` is missing, stale or not yours, so B cannot push. Restart OpenCode from a terminal where `ssh-add -l` works |
| The agent reports `E-B-DEFAULT` or `E-B-HTTPS` from `carter_push` | The branch is the remote's default branch, or `origin` is HTTPS (the tool pushes over SSH to a non-default branch only). Run `carter push` yourself |
| The agent reports `E-B-REPOCFG`, `E-B-UNSIGNED` or `E-B-ARGS` from `carter_push` | It refused before asking you; the message says why: repository or SSH config that could run code, an LLM-committed commit without a valid LLM signature, or not a fast-forward of the current branch. Fix it, or run `carter push` yourself and decide ([Write operations](guides/write-operations.md#letting-devops-ask-you-to-push)) |
| The agent reports `E-B-MOVED` | `HEAD` changed after you approved. Ask again |
| `carter_push` does not exist for an agent | Expected for everyone but devops. For devops it needs the `g2` guard group (`carter guard install`; `carter guard remove --only broker` turns it off) and an OpenCode restart. `carter check --host` says which |
| `E-APLUS-ARGS` from `carter push` | Detached HEAD, no `origin`, a non-fast-forward branch, or an extra argument. `carter push` takes no arguments or force option: check out the branch, fetch and rebase |
| `carter push` printed a warning about settings | A repository, git or SSH setting could run code with your credentials (a credential helper, `core.sshCommand`, a hook file, a `ProxyCommand`). The push went on. Read the names and remove what you did not put there |
| `E-PAT-TYPE` from `carter github-token set` | Only fine-grained `github_pat_` tokens are accepted. The error shows at most the first four characters of what you gave it. Create a fine-grained token (Contents: read, Pull requests: write) |
| `E-PAT-PERM` | The token file or its folder is not mode 0600/0700, not yours, a symlink, or inside a git repository. Fix it, or run `carter github-token set` again |
| `carter github-token check` says the token is WRITABLE | GitHub accepted a push attempt: the token has **Contents** write. Revoke it and create one with Contents read |
| `carter github-token check` says agents can't open PRs | The token lacks **Pull requests: write**. Add it on GitHub (keep Contents read) |
| An agent's `gh pr create` fails with `Resource not accessible by personal access token` | Same: add **Pull requests: write** to the token. If it says the branch is not on the remote, run `carter push` first |

## Plugin, gate and isolation

| Symptom | Fix |
|---------|-----|
| An agent command is refused with `E-ISOLATION-MISSING` | `~/.carter/isolation.json` is missing, invalid or no longer matches the hash in the plugin, so agent shells are disabled (your terminal and `!` still work). Run `carter check --host` in your terminal, then `carter guard install` (or `carter guard remove --only plugin` to go back) |
| An agent command is refused with "Refused by the Carter command gate (rule `…`)" (`E-GATE`) | Expected: the gate rejected the command, and the rule id says why. The agent should hand the step to you instead of rephrasing it. Common fixes: put `-R <owner>/<repo>` after the `gh` subcommand, stage explicit paths instead of `git add -A`, and run pushes yourself with `carter push` |
| `E-GATE-FAIL`: "Command gate unavailable; command refused" | The gate could not answer, so the command was refused (fail closed). Run `carter check --host`; if the Python or `carter` path it names is gone (for example after `uv tool upgrade`), run `carter guard install` again in your terminal |
| An agent push stops with `E-PUSH-GUARD` | The `pre-push` hook blocked a push made from an agent shell. Pushing is yours: run `carter push` in your own terminal; the agent then opens the PR |
| `E-GIT-OLD`: global guards need git 2.54 or newer | Your git is older, so the `hooks` group is not installed and `repo_hooks` is offered instead (a hook file per repo). `carter check --host` lists repos that are `unguarded`; upgrade git (for example `brew upgrade git`) and run `carter guard install` to switch to the global hook |
| `E-OPENCODE-VERSION`: the guards are untested on OpenCode … | Your OpenCode is older or newer than the version Carter was tested with; the plugin relies on its own check there. Nothing is blocked; check `carter check --host` |
| `carter check --host` says a server is "waiting for the first agent command" after an OpenCode update | The plugin checks itself again in every new server process, at the first agent command. Run any command through an agent, then `carter check --host` again. If it says the plugin's own check failed, restart OpenCode from a clean terminal |
| `E-SELFTEST`: the plugin's own check failed | Another OpenCode plugin may reject commands after Carter's. Every shell is then treated as an agent shell until the server restarts. Restart OpenCode from a clean terminal; if it repeats, disable the other plugin |
| My agent cannot fetch over SSH | By design: agent shells have no SSH agent. Fetch and pull use HTTPS with the read-only token, which covers public repositories and the repositories that token was created for. Fetch yourself, or add the repository to the token (`carter github-token set`) |
| My agent cannot run `python -c` | The gate refuses interpreter code that mentions `git` or `gh` (rule `interpreter-git`). Ask the agent to use the git command directly, or run it yourself |
| My agent's commit failed and `carter ops config --emit` shows a tier of `t2` | See [Signing and the LLM identity](#signing-and-the-llm-identity): usually the key is locked (`carter identity unlock`). To let agents commit unsigned in a workspace, set `max_tier = "t1"` for it in `~/.carter/config.toml` and run `carter update` |
| `carter check --host` says the `pre-push` hook is inactive | The include line is not in your global git config (it is a symlink or read-only, so Carter did not write it). Add the printed `git config --global --add include.path …` line to your dotfiles |
| `carter check --host` says "git cannot parse … every git command fails" | Delete `~/.carter/gitconfig` and run `carter guard install` again |
| `opencode serve`, `opencode run` or `opencode service start`/`restart`/`stop`/`set` from an agent shell is refused | By design (rule `other-verbs`): a server started from an agent shell would inherit its isolated environment. e2e and spikes that start a server are run by you (`tests/e2e/run.sh`) or CI; restart the service yourself, from a clean terminal. `opencode service status` and `get` are allowed |

## Signing and the LLM identity

| Symptom | Fix |
|---------|-----|
| My agent's commit failed with `error: Couldn't find key in agent?` or `Couldn't get agent socket` and then `fatal: failed to write commit object` (`E-SIGN-LOCKED`, `E-SIGN-NOAGENT`) | The LLM signing key is locked, its lifetime (`unlock --ttl`) ran out, or the agent stopped. Nothing was committed and the changes are still staged. In your own terminal run `carter identity unlock`, then ask the agent to retry |
| `E-UNLOCK-OPENCODE` | `unlock` refuses inside OpenCode: in an agent shell, in the `!` prompt and in the integrated terminal (OpenCode sets `OPENCODE_TERMINAL` in every shell it starts). Open a terminal that OpenCode did not start |
| `E-UNLOCK-TTY` | `unlock` needs a terminal on stdin and stderr to ask for the passphrase. Run it in your own terminal |
| `E-UNLOCK-PATH` or a socket-path length message | Something that is not our agent's socket sits at the socket path, or the path is too long (104 bytes on macOS, 108 on Linux). Carter never removes what is not its own socket: remove the file yourself or shorten `$TMPDIR`/`XDG_RUNTIME_DIR` |
| `E-UNLOCK-BADPASS` | `ssh-add` rejected the passphrase. Try again; an empty line ends the attempt |
| `Signing refused: only the configured LLM key via the agent may sign` (`E-SHIM-REFUSED`) | Something asked git to sign with another key (a `-S<key>`, a `user.signingkey` override). Agent commits never need that. Check `carter check --host` and remove the override |
| The agent reports `E-SIGN-UNAVAILABLE` with a reason in brackets | The signing identity is broken, so the commit was blocked instead of made unsigned. `<reason>` is `config-error` (fix `config.toml`), `tier-required`, `key-missing` or `fingerprint-mismatch` (run `carter identity add` again) or `shim-missing` (the signing shim is gone or changed: run `carter identity add` again). `carter identity show` and `carter check --host` say which |
| A commit hook printed `carter-guard: …` (`E-GUARD-NOIDENT`, `E-GUARD-COMMITTER`, `E-GUARD-SIGNCFG`) | The agent's commit did not carry the identity block the plugin sets, or something overrode the committer or a signing option. If you just changed `max_tier`, run `carter update`; otherwise restart OpenCode from a clean terminal and run `carter check --host` |
| `E-GUARD-TRAILER`: "Co-authored-by trailer missing" | A message editor (or a reword) removed or moved the trailer. Commit again with `-m` and the trailer; editing the message after the trailer is rejected because GitHub would not credit it |
| `E-GUARD-T01SIGN`: "Signing attempted below T2" | A signature was requested where the tier is T0, T1 or capped. Remove `-S` and any `commit.gpgsign` option; if you changed `max_tier`, run `carter update` |
| `E-GUARD-UNSIGNED` after a commit | A warning, never an undo: the commit is unsigned or not signed by the LLM key (a signing option was skipped, or the key changed). Re-create it, or run `carter identity verify`. `carter push` refuses such a commit (`E-B-UNSIGNED`) |
| `E-TIER-CAPPED` / `E-TIER-REQUIRED` | A workspace `max_tier` lowers the tier (agent commits are unsigned there); `require_tier` is a minimum the workspace cannot meet (`carter commit` and the plugin refuse). After a change of `max_tier` run `carter update`; the guard reads the cap from `~/.carter/gitconfig` |
| `E-IDENTITY-CHECK` from `carter identity add` | The account or the key failed a check and nothing was written. The message names the actual cause: not a `User` account, an id mismatch, the key is not registered as an SSH **signing** key, it is registered as an **authentication** key, it is your own key, or the private key file is missing, too open or does not match |
| `E-GITHUB-UNREACHABLE` | The unauthenticated checks could not reach GitHub (network, a 5xx, or a rate limit with the reset time). Nothing was written; try again later |
| `E-SSH-OLD` or `E-GIT-OLD` from `identity add` | Signing needs git 2.40 or newer and OpenSSH 8.4 or newer (`ssh_bin_dir` can point at a newer one, for example Homebrew's). Nothing was written |
| `E-SIGN-HUMAN-FALLBACK`: `carter commit` says it committed unsigned | The key was locked, so the commit is unsigned with the `Co-authored-by` trailer. Your own key is never used. Run `carter identity unlock` and commit again if you want it signed |
| GitHub shows "Unverified" on a commit | The LLM account may have vigilant mode on and the commit was unsigned, or signed with a key that is not registered as a signing key on that account. See [the guide](guides/identity-and-signing.md#the-vigilant-mode-table) |
| `carter identity unlock` seems to do nothing under a password manager | With `agent_socket` or `program` set, the key lives in the password manager and Carter has nothing to unlock: approve the signing request there |

## Uninstalling

| Symptom | Fix |
|---------|-----|
| `carter uninstall` kept the guards | You passed `--keep-guards`. Run `carter guard remove` to take them out |
| `carter uninstall` left files behind | By design. Files you edited are kept (those edited since the last install are listed as `⚠ Kept …`), and memories, `config.toml` and `audit.log` are never removed. Delete them by hand if you don't need them |
