# Push and PR tools (B): let devops ask you to push

By default **nobody but you pushes**. When a branch is ready the agent writes a handoff file and
you run `carter push` and then `carter pr` in your own terminal ([Write operations](write-operations.md)).
That path is called **A+** and it stays the default.

This guide covers the optional second path, **B**: two tools, `carter_push` and `carter_pr`, that
only the **devops** agent has and that **ask you to approve every single use** in the OpenCode
prompt. Nothing is pushed until you click.

> [!WARNING]
> **B is a convenience, not a security boundary.** An agent that deliberately tampers with your
> user account can misuse it: it runs with your SSH agent, as your user, and a program running as
> you can answer OpenCode's prompt through the server API. The prompt, the checks and the dwell
> rule below stop a careless or confused agent; a hostile one needs the OS sandbox, which does not
> exist yet. If that is not acceptable, decline B and keep A+.

## What you get

| | A+ (`carter push`, `carter pr`) | B (`carter_push`, `carter_pr`) |
|---|---|---|
| Who runs it | You, in your terminal | devops asks; you click **Once** in OpenCode |
| Pushes | The current branch, with a typed confirmation on the default branch | A fast-forward of the commit you were shown, to the current **non-default** branch, over **SSH** |
| Default branch, HTTPS `origin` | Allowed (you confirm) | Refused: use A+ |
| Unsigned LLM commits, repo or SSH config that could run code | Shown in red, you decide (unsigned LLM commits are refused) | Refused |
| Needs | Nothing | Revision 3 of the `g2` consent, an SSH `origin`, your SSH agent running |

B never forces, never pushes tags, never deletes a branch, never pushes another branch or
another remote, and the agent supplies **no argument at all**: the repository is the session's, the
branch is the current one, the commit is `HEAD` at the moment of the plan.

## Turning it on (and off)

B arrives with consent group `g2` **revision 3**. If you already use Carter, `carter guard install`
in your terminal shows what B is and asks. A bare `--yes`, `carter update` and every run without a
terminal leave B **off** (`carter guard install --yes --only g2` confirms it on purpose). A "no"
is remembered and nobody asks again until you name the group.

```text
carter guard install                      # shows the explanation, then asks about g2
carter guard install --yes --only g2      # confirm without a question (scripted)
carter guard remove --only broker         # B off again; the rest of g2 stays
```

Restart the OpenCode server afterwards: it loads the plugin at start. `carter check --host` says
whether B is on, and why not if it is off.

## What you will see

1. devops finishes its work and calls `carter_push`. For a PR it writes the handoff file first and
   calls `carter_pr`; the file is the only input of that tool.
2. Carter checks everything it can **without using your credentials** (the repository config, your SSH
   config, the commit signatures, the range) and refuses with a code if something is wrong. You are
   not asked for something that cannot work.
3. OpenCode shows a prompt: `push <owner/repo> <branch>`, the range, the commit list, which agent
   asked and in which session. You get **Once** or **Reject**; there is no "Always".
4. After you approve, Carter checks again (HEAD must still be the commit you saw), pushes with your
   SSH agent, reads the remote branch back and tells the agent the result. The decision is written
   to the audit file.

A rejection ends the agent's turn with no result: that is how OpenCode works. The agent is told
not to ask again for the same change.

## Approving: take a moment

- An approval that arrives in **less than half a second** is refused as automatic
  (`E-B-DWELL`): that is what `--auto` and an auto-accepting client do. It counts as a rejection.
  You can only make the floor **longer** (`[broker] min_dwell_ms`, up to 10 000), never shorter.
- An approval after **120 seconds** is refused (`E-B-TIMEOUT`), and the prompt is withdrawn.
- Do not use `opencode --auto` or the TUI's auto-accept setting with B: every use would be refused,
  and `carter check --host` warns when it finds either. (This guide does not recommend them for
  anything.)
- **Three rejections** (rejects, timeouts, dwell refusals, an interrupt) in one session family stop B
  for that session with `E-B-REJECTED`. A new session starts fresh; to clear the count yourself run
  `carter guard status --reset-b` in your terminal. Nothing an agent can call resets it.

## Headless runs

`opencode run` without `--auto` cannot answer a prompt, so OpenCode rejects B's request at once
(`E-B-HEADLESS`: "permission requested ... auto-rejecting"). With `--auto` the dwell rule refuses it.
For a run that must not even have the tools, Carter installs `~/.carter/opencode-headless.json`:

```text
OPENCODE_CONFIG=~/.carter/opencode-headless.json opencode run --standalone ...
```

The profile is read by the process that **starts** the server. It works with `--standalone`, or for
the run that starts the background service; an OpenCode service that is already running ignores it.
Against a running service the controls are the auto-reject and the dwell floor above.

## What Carter refuses, and what to do

| Code | Meaning | What to do |
|------|---------|------------|
| `E-B-CALLER` | Not devops (a subagent is `general`) | Only devops asks; other agents hand off |
| `E-B-DEFAULT` | The remote default branch (or `main` / `master`) | `carter push` in your terminal; it asks you to type the branch name |
| `E-B-HTTPS` | `origin` is HTTPS | `carter push`; B pushes over SSH only |
| `E-B-REPOCFG` | Repo config, a hook, or your SSH config could run code with your credentials | Review it; `carter push` shows the same findings and lets you decide |
| `E-B-UNSIGNED` | An LLM-committed commit without a valid LLM signature | Unlock the key and recommit, or push it yourself after review |
| `E-B-NOAGENT` | `SSH_AUTH_SOCK` of the OpenCode server is missing, stale or not yours | Restart OpenCode from a terminal with your agent |
| `E-B-POLLUTED` | The server was started from an agent shell or already carries Carter's isolation | Restart OpenCode from a clean terminal; Carter never scrubs this |
| `E-B-MOVED` | HEAD changed after you approved | Ask again |
| `E-B-DWELL`, `E-B-TIMEOUT`, `E-B-REJECTED` | See "Approving" above | |
| `E-B-ARGS` | Not a fast-forward, nothing to push, detached HEAD, `git push` failed, no `origin/HEAD` ... | The detail says which |
| `E-SECRET-SCAN`, `E-HANDOFF` | `carter_pr`: a secret in the title, branch or body, or no valid handoff | Fix the handoff file |

## Files

| Path | What |
|------|------|
| `~/.carter/state/audit/b.jsonl` | One line per decision: time, agent, session and root session, repo, branch, range, commit count, decision, code, dwell. No environment, no URL with credentials, no title. Rotates at 5 MiB (keeps three). Directory 0700, files 0600 |
| `~/.carter/state/audit/audit.log` | The `ops:` audit log, moved here from `~/.carter/audit.log` the first time it is written |
| `~/.carter/run/b-rejections.json` | The rejection counters (0600) |
| `~/.carter/opencode-headless.json` | The headless profile (tracked by `guard-state.json`) |
| `~/.carter/isolation.json` | Schema 2: `plugin.b_enabled`, `b_caller`, `broker_args`, `b_git`, `b_gh` |

`carter_pr` uses your own `gh auth login` (keyring or `hosts.yml`). A token in `GH_TOKEN` or
`GITHUB_TOKEN` in the OpenCode server's environment is **not** passed on; `carter check --host`
warns when it finds one.

`git` and `gh` are found **once**, when you run `carter guard install` (in `/usr/bin`, `/bin`,
`/usr/local/bin`, `/opt/homebrew/bin`), and stored by absolute path; B never searches `PATH`. `ssh`
comes from `[identity.signing] ssh_bin_dir` (default `/usr/bin`).

## Residuals (accepted, written down)

- **Forgeable by a same-user agent until a sandbox exists.** An agent running as you, holding the
  OpenCode server password, can answer the prompt through the server API after any delay; the dwell
  rule is a heuristic against automatic clients, not a boundary (D49).
- Carter's own install (the Python it runs) and any `git`, `gh` or `ssh` directory that you own and
  an agent could write are code B runs with your SSH agent. `carter check --host` warns when those
  are not root-owned. Same class as the point above.
- A plain reject ends the turn with no result; the agent learns from your message only if you give
  one (**Reject** with feedback).
- A repo or SSH config written in the milliseconds between Carter's last check and `git push` is
  not caught. It could redirect the already-approved commit to another SSH host.
- `ProxyJump` in your SSH config is not refused (you wrote it), and `/etc/ssh` is not scanned.
- The real OpenCode prompt, the human dwell time and Apple's `ssh -G` output are checked by hand,
  not in CI.

Next: [Safety and permissions](safety-and-permissions.md), [Identity and signing](identity-and-signing.md).
