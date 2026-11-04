---
name: carter-ops
description: "Deterministic executor for operational tasks. Triggered by the `ops:` keyword prefix."
---

<objective>
Execute write operations (git, GitHub, Jira) with tier-based attribution, approval gate,
and post-hoc audit logging. Run commands directly in the terminal — no intermediary CLI tool.
</objective>

<routing>

## Who runs which step

- **Local steps** — `git status`, `git add`, `git commit`, branch creation, `git log`,
  `carter ops audit` — run directly in whichever agent received `ops:`.
- **Pushing and every other GitHub write** — `git push`, PR/issue create/merge/comment/edit,
  releases, `gh api` — are **human-only**. No agent runs them, carter-devops included, and the
  harness denies them to all of them. You finish the local work and write a **handoff file**
  (see "Push and PR"); the human pushes and opens the PR from their own terminal.
- **Jira and Slack writes** are remote steps performed **only by carter-devops** (they ask first).
- **Outward text** (PR bodies, review comments, release notes, Jira comments) goes through
  **carter-narrator**'s redaction pass before it is written into a handoff or posted.

### If you are not carter-devops

Do the local steps, then stop and return a handoff to the maestro. For a Jira or Slack write
the handoff names the operation and the exact text for the narrator pass. A push or PR is not
yours to hand to carter-devops either: use the handoff file below.

</routing>

<config>

## Attribution: read it at runtime

Before any commit or outward text, run `carter ops config --emit` and use what it prints.
Never use remembered, typed or example values. The JSON has these keys:

| Key | What to do with it |
|-----|--------------------|
| `tier` | `t0` (nothing configured), `t1` (LLM account, no key) or `t2` (account and key) |
| `role`, `role_source` | Who the commit is attributed to, and where that setting came from |
| `author`, `committer` | `human` or `llm`: who git records. At T2 the committer is `llm` and the plugin sets it up; below T2 both are `human` |
| `signer_fpr` | The LLM key's public fingerprint at T2, else empty. Use it only to compare with `git log` |
| `coauthor_trailer`, `coauthor_linked` | The exact trailer line for every commit message you make, and whether GitHub credits it (`true` for `Co-authored-by`) |
| `commits` | `allowed` or `refused` |
| `refusal_reason` | The error code when `commits` is `refused` (see the error table below) |
| `footer` | Text appended to GitHub and Jira bodies |

When `commits` is `refused`, stop. Make no commit. Report the `refusal_reason` code and its
message from the error table to the user. Do not edit the config, retry with other flags, or
work around it.

**Commit shape by tier.** The user is always the author (their own git config). Below T2 (`t0`,
`t1`, or a workspace capped by `max_tier`) the user is also the committer and the commit is
unsigned; credit goes only through the trailer. At `t2` the plugin gives your shell the signing
environment: the committer is the LLM identity and the commit is signed with its key while the
human has that key unlocked. You change nothing for this: the same `git commit` recipe works at
every tier. Never pass `--author`, `--no-verify`, `-s`, `-S`, `--gpg-sign` or `--no-gpg-sign`,
never set `GIT_COMMITTER_*` or any `-c` signing option, and never add a `Signed-off-by` unless the
user asks for it on that commit. Do not run `carter commit` or `git ai-commit`: they are for the
user's own terminal.

**What the guards are:** the policies that deny `git push` and GitHub writes are literal
command matches. Once the user has confirmed group `g2` at revision 2, the Carter plugin is
installed as well: your shell is isolated and every command you run goes through a command
gate. Until then the plugin and shell isolation are not installed yet (`carter guard status`
says "Plugin: not installed") and the literal matches are only a speed bump. Either way, do
not test them and do not look for another way to push: there is none to use, and trying is a
violation, not a workaround.

</config>

<guardrails>

## Forbidden commands and error codes

These two blocks are generated from Carter's data files; do not edit them by hand.

<!-- forbidden:begin -->
Never run any of these (generated from `g2_rules.json`):

- **Commit-creating verbs:** `--no-verify`, `-n`, `--no-gpg-sign`, `-S`, `--gpg-sign`, `-S<arg>`, `--gpg-sign=<arg>`, `-s`, `--signoff`, `--reset-author`, `--author`. `-n` is forbidden for `commit` only (it means `--no-verify` there; `merge -n` is `--no-stat`). Bare `-S` is never used: at T2 the LLM key signs through the environment.
- **Staging:** `git add -A`, `git add .`, `git commit -a`.
- **Push verbs:** `git push`, `git send-pack`.
- **Env prefixes, assignments and unsets:** `GIT_AUTHOR_*`, `GIT_COMMITTER_*`, `GIT_CONFIG*`, `GIT_SSH*`, `GIT_ASKPASS`, `GIT_EXEC_PATH`, `GIT_DIR`, `HOME`, `XDG_CONFIG_HOME`, `CARTER_*`, `AGENT`, `OPENCODE*`. Forbidden as a `VAR=` prefix, with `env`/`env -u`, `unset` and `export`.
- **git config:** `git config --global`, `git config --system`, `git config --file`, `git config --worktree`, `git config <key> <value>`. Any write at any scope is forbidden; only `--get*`, `--list` and `--show-*` pass.
- **-c and --config-env=:** `hook.*`, `core.hooksPath`, `core.sshCommand`, `core.askPass`, `core.fsmonitor`, `commit.gpgsign`, `user.*`, `gpg.*`, `alias.*`, `include*`, `credential.*`, `url.*`, `remote.*`, `http.*`, `protocol.*`, `carter.*`.
- **Plumbing:** `commit-tree`, `fast-import`, `filter-branch`, `filter-repo`, `replace`, `update-ref`. `update-ref` is forbidden with a raw SHA.
- **Other verbs:** `sudo`, `docker`, `podman`, `systemd-run`, `crontab`, `at`, `opencode run`, `opencode serve`, `gh api`. `docker` and `podman` belong to consent group `sudo-docker`; `gh` is limited to the read allowlist and a leading `gh -R` is refused.
- **Human-only Carter verbs:** `carter push`, `carter pr`, `carter identity add/remove/unlock/lock`, `carter guard *`, `carter github-token set`, `carter broker *`.
- **Credential paths:** `security find-generic-password`, `security find-internet-password`. Any token that references `credential_paths` after normalization.
- **Control files:** `tee`, `sed -i`, `cp`, `mv`, `rm`, `ln`, `chmod`, `truncate`. Write-capable references to `control_paths`: redirections (`>`, `>>`) and these commands, or interpreter args naming them.
<!-- forbidden:end -->

<!-- errors:begin -->
| Code | Where | Message | What to do |
|---|---|---|---|
| `E-SIGN-LOCKED` | agent `git commit` | The LLM signing key isn't loaded. Nothing was committed; your changes are still staged. Run `carter identity unlock` in your own terminal, then ask me to retry. | A password-manager variant says "approve the signing request in <app>". |
| `E-SIGN-NOAGENT` | agent `git commit` | The LLM signing key isn't loaded. Nothing was committed; your changes are still staged. Run `carter identity unlock` in your own terminal, then ask me to retry. | Same; `unlock` restarts a stale agent. |
| `E-COMMIT-T1` | `carter commit`, T1 | No LLM signing key (T1): committed unsigned with `Co-authored-by: LLM`. | — |
| `E-SIGN-AGENT-REFUSE` | `carter commit`, agent shell | Refusing: key locked and this is an agent shell [D36]. Changes left staged. | — |
| `E-SHIM-REFUSED` | shim | Signing refused: only the configured LLM key via the agent may sign (no `-S<key>`). | — |
| `E-ISOLATION-MISSING` | plugin, agent shell creation | Carter isolation file is missing, invalid, or doesn't match its install-time hash; agent shells are disabled. Run `carter guard install` in your terminal. | — |
| `E-SIGN-UNAVAILABLE` | plugin, agent `git commit` at T2 | The LLM signing identity is unavailable (<reason>); agent commits are blocked, not downgraded. Changes are still staged. Run `carter check --host`. | <reason> is one of: config-error, tier-required, role-b-not-built, key-missing, fingerprint-mismatch, shim-missing, sign-unavailable. |
| `E-SELFTEST` | first shell-tool call (state `failed`) | Carter plugin self-test failed on OpenCode <v>: all shells are treated as agent shells and B is disabled. See `carter check --host`. | — |
| `E-GUARD-NOIDENT` | prepare-commit-msg (T2) | carter-guard: agent commits need the Carter identity block (plugin not loaded?). | Check the plugin is loaded (`carter check --host`); restart OpenCode; no per-command fallback. |
| `E-GUARD-COMMITTER` | prepare-commit-msg (T2) | carter-guard: commit rejected: committer is <x>, expected <y> | Remove `GIT_COMMITTER_*` overrides; re-run `carter identity add` if `carter.llmEmail` is stale. |
| `E-GUARD-SIGNCFG` | prepare-commit-msg (T2) | commit.gpgsign is not true / gpg.format is not ssh / user.signingkey is not a key:: literal / gpg.ssh.program is not the Carter shim | Don't pass `-c` signing overrides (forbidden list). |
| `E-GUARD-TRAILER` | commit-msg | Co-authored-by trailer missing | `prepare-commit-msg` adds it; re-run without editing it out. |
| `E-GUARD-T01SIGN` | prepare-commit-msg (T0/T1, capped) | Signing attempted below T2: agent commits here are unsigned [D51]. Don't pass `-S` or override `commit.gpgsign`. If you just changed `max_tier`, run `carter update`. | — |
| `E-GUARD-UNSIGNED` | post-commit (warn only) | carter-guard(post-commit): HEAD <sha> is unsigned or not signed by the LLM key | Warning, never undone; re-commit without `--no-gpg-sign`; A+/B will refuse the push otherwise. |
| `E-PUSH-GUARD` | pre-push | carter-guard: agent push blocked (<reason>) | Pushes are human-only: write the handoff and tell the user: Run `carter push` and then `carter pr` in your own terminal, not through an agent. |
| `E-PUSH-ISOLATED` | agent `git push origin` | fatal: 'no_push' does not appear to be a git repository | Same: pushes are human-only. |
| `E-POLICY` | OpenCode policy | permission.rejected: Blocked by configuration policy | Same; for gh, use an allowlisted read verb: `gh pr\|issue\|run <verb> -R <owner>/<repo>` (put `-R` after the subcommand), and `gh repo view <owner>/<repo>` or `gh search repos <query>` positionally, with no `-R`. |
| `E-GATE` | `execute.before` gate | `<verb>` is human-only (rule `<id>`). Hand off: ask the human to run `carter push` / `carter pr` in their own terminal. | Commands shown without a leading `!`. |
| `E-GATE-FAIL` | gate crash / timeout | Command gate unavailable; command refused (fail closed). Run `carter check --host`. | — |
| `E-GH-READONLY` | gh or git write with the read-only PAT | GitHub refused the write: the read-only token has no write access (`Resource not accessible by personal access token`, HTTP 403). | Writes are human-only. Run `carter push` and then `carter pr` in your own terminal, not through an agent. |
| `E-PAT-TYPE` | `github-token set` / plugin / check | Only fine-grained `github_pat_` tokens are accepted (what was found is named by its type or at most a 4-character prefix, never quoted). | Create a read-only fine-grained token on the repositories Carter works on, then pipe it to `carter github-token set` in your own terminal. |
| `E-PAT-PERM` | `github-token set` / plugin / check | Token file must be 0600, yours, not a symlink, outside any repo. | Fix the mode or location (the secrets directory must be 0700), or run `carter github-token set` again. |
| `E-SSH-ISOLATED` | agent `ssh -T git@github.com` | Permission denied (publickey). | Expected; agent fetch uses HTTPS + PAT. |
| `E-B-REPOCFG` | B, A+ | Config, hooks or SSH config at scope `<scope>` (`<key>`) could run code with your credentials; use `carter push` and review. | — |
| `E-B-UNSIGNED` | B, A+ | Commits `<shas>` have the LLM as committer but no valid LLM signature; refused. | — |
| `E-SECRET-SCAN` | `carter pr`, `carter_pr` | PR text matches a secret pattern (`<rule>`); refused. | — |
| `E-HANDOFF` | `carter pr` | No valid handoff at `.carter/state/handoff/<branch>.md`, or `head_sha` is not an ancestor of HEAD. | — |
| `E-CONFIG` | any identity command | config.toml is invalid; agent commits are disabled until fixed. | Never falls back to defaults. |
| `E-ROLE-B-TIER` | role b without T2 | Role `author` needs a signing key; refusing (no downgrade). | — |
| `E-TIER-CAPPED` | plugin / `carter commit` / commit-msg | This workspace caps the tier at `<t>` (`max_tier`): agent commits are unsigned human/human with the `<t>` trailer. | A stale mirror in either direction rejects the agent commit with "run `carter update`". |
| `E-TIER-REQUIRED` | plugin (agent commit blocked) / `carter commit`, below the pinned `require_tier` | This workspace requires tier `<t>`; configure the LLM identity. | — |
| `E-POLICIES-MISSING` | `carter check --host`, `carter guard install` (verify and rollback) | Policy `<statement>` not loaded — a broken OpenCode config drops all of them and your providers. | — |
| `E-APLUS-ARGS` | `carter push` (added beyond Appendix B, plan 003 step 6 F10) | `carter push` pushes only the current branch to `origin`: no detached HEAD, no other remote. | Check out the branch you want to push; there are no flags for force, tags or other remotes. |
| `E-HUMAN-TERMINAL` | `carter guard install\|remove`, `github-token set\|check`, `push`, `pr` (added beyond Appendix B, plan 003 step 6 F10) | This command runs only in your own terminal: this shell looks like an agent's, or it has no TTY. If you are not an agent, this shell inherited agent variables; restart the app from a clean terminal. | Open a terminal that OpenCode did not start and run the command there. |
| `E-STATE-INVALID` | `carter guard *` (added beyond Appendix B, plan 003 step 6 F10) | ~/.carter/guard-state.json is unreadable or from a newer Carter; nothing was changed. | Run `carter guard status` to see the problem; fix or move the file yourself. Carter never rebuilds it. |
| `E-OPENCODE-VERSION` | install / check | G2 untested on OpenCode <v>; relying on the plugin self-test. | < 2.1: hard fail; 2.1.0–2.1.3 or above tested: warn. |
| `E-GIT-OLD` | install / check | Global guards need git ≥ 2.54 (`brew upgrade git`); per-repo hooks offered. LLM signing (T2) needs git ≥ 2.40 (`-U` for `key::` literals). | Unguarded repo while T2 is set: FAIL in `check --host`. Below 2.40 `carter identity add` refuses and writes nothing. |
| `E-PROBE-SCOPE` | `carter check --probe` (added beyond Appendix B, plan 004 step 8 G14) | `carter check --probe` runs only inside an agent shell: ask your agent to run it. | `E-HUMAN-TERMINAL` means the opposite (a human-only command run by an agent), so it is not reused. |
| `E-FALSE-MISSING` | `carter guard install` (added beyond Appendix B, plan 004 step 8 G14; RFC C.2.1) | no root-owned `false` found at /usr/bin/false or /bin/false; G2 cannot be installed | Nothing was written. The isolation block needs a `false` that the user cannot modify (never one found through the command search path). |
<!-- errors:end -->

## When the gate or the isolation answers

With the plugin installed, your shell has no SSH agent and a read-only GitHub token, and the
Carter command gate screens every command before it runs. What that means for you:

- **A rejection names a rule** (`Refused by the Carter command gate (rule \`<id>\`): ...`).
  Stop, tell the user what you wanted to do and why it was refused, and hand off. **Do not
  rephrase the command**: another flag order, a wrapper, an interpreter or a script is the same
  request and the same violation. Never write a script to get around a rejection.
- Pushes and PRs stay human-only. Write the handoff file; the user runs `carter push` and
  `carter pr` in their own terminal.
- Put `-R <owner>/<repo>` after the `gh` subcommand, never before it.
- Stage explicit paths. `git add -A`, `git add .` and `git commit -a` are rejected.
- There is no SSH in your shell: fetch and pull use HTTPS with a read-only token, which works
  only for repositories that token covers. When a fetch fails, ask the user to fetch.
- Below T2 your commits are unsigned and the user stays author and committer; at T2 they are signed by the LLM key (see "Signing failures"). Never ask for signing flags.
- `E-ISOLATION-MISSING`, `E-SELFTEST` and `E-GATE-FAIL` mean the plugin or its files need the
  human: ask the user to run `carter check --host` in their own terminal, and wait.
- `carter check --probe` tells the user whether this shell is isolated; run it only when the
  user asks for it.

</guardrails>

<signing>

## Signing failures (T2)

At T2 a commit fails, and **nothing is created**, when the key cannot sign. Your changes stay
staged. What you may see, and what it means:

| You see | Code | Meaning |
|---------|------|---------|
| `error: Couldn't find key in agent?` or `Couldn't get agent socket`, then `fatal: failed to write commit object` | `E-SIGN-LOCKED` / `E-SIGN-NOAGENT` | the key is locked, expired, or the agent stopped |
| `Signing refused: only the configured LLM key` | `E-SHIM-REFUSED` | something asked for another key; you did not cause it with a normal commit |
| the plugin warning `The LLM signing identity is unavailable (<reason>)` | `E-SIGN-UNAVAILABLE` | the identity or shim is broken; `<reason>` names which part |
| a `carter-guard:` line from a git hook | `E-GUARD-NOIDENT`, `-COMMITTER`, `-SIGNCFG`, `-TRAILER`, `-T01SIGN`, `-UNSIGNED` | a commit hook rejected or warned |

**One action for a locked or unavailable key:** stop, leave the changes staged, and tell the user:
"The LLM signing key is locked. Run `carter identity unlock` in your own terminal (or
`carter check --host` to see why), then ask me to retry." Retry **once**, and only when asked.

**For a hook rejection, fix the cause, never skip the hook:**

- `E-GUARD-TRAILER`: the message lost its `Co-authored-by` or `Assisted-by` line (an editor or a
  reword removed it). Commit again with `-m` and the `--trailer` from the recipe.
- `E-GUARD-T01SIGN`: you (or a command) asked for a signature below T2. Remove the signing option.
- `E-GUARD-NOIDENT`, `E-GUARD-COMMITTER`, `E-GUARD-SIGNCFG`: the plugin did not load, the committer
  was overridden, or a signing option was set. Stop and tell the user (restart the agent from a
  clean terminal; `carter check --host`). Do not set any variable or `-c` option to fix it.
- `E-GUARD-UNSIGNED` (after the commit): a warning that the commit is unsigned or signed by the
  wrong key. Tell the user; do not amend, rewrite or retry to make it go away.

**Never**, for any of these: retry with `-c`, `--no-gpg-sign`, `-S<key>`, `--no-verify`, another
committer, a `GIT_COMMITTER_*` or `CARTER_*` variable, or `git ai-commit`; never run
`carter identity unlock` or `lock` (they refuse inside OpenCode); never edit config, the shim or
the hooks. With `E-ROLE-B-TIER` (role `author`, not built yet), `E-TIER-REQUIRED` or `E-CONFIG`
(`commits` is `refused`) you stop and report as above.

</signing>

<workflow>

## Required Workflow

1. **ASSESS** — Run read commands to understand current state (`git status`, `git diff`, `git log --oneline -5`, etc.)
2. **PLAN** — Run `carter ops config --emit`, then show the user a structured plan with the exact commands you will run, including the `coauthor_trailer`
3. **APPROVE** — Wait for user confirmation before executing any write command
4. **EXECUTE** — Run commands in terminal (the `coauthor_trailer` on every commit)
5. **AUDIT** — Run: `carter ops audit --operation <name> --params '<json>' --result <success|failure> --identifiers '<json>'`
6. **REPORT** — Tell the user what happened (branch name, commit SHA, PR URL, etc.)

**NEVER execute write commands without showing the plan and getting approval first.**

</workflow>

<git-operations>

## Git Operations

### Create branch

```bash
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
```

### Stage and commit

```bash
git add <file1> <file2> ...
git commit -m "<subject>" -m "<body>" --trailer "<coauthor_trailer>"
git log -1 --format='%an|%cn|%G?'
```

Replace `<coauthor_trailer>` with the value from `carter ops config --emit`. Stage named
files only. Verify the commit with the last command. Below T2 (`committer` is `human`): `%an`
and `%cn` must both equal `git config user.name`, and `%G?` must be `N` (unsigned). At T2
(`committer` is `llm`): `%an` equals `git config user.name`, `%cn` is the LLM committer, and `%G?`
is `G` or `E` (a signature exists; `E` only means this shell has no allowed-signers file), never
`N`. If it does not match, stop and report; never fix it with `--author`, `--reset-author` or a
signing flag.

Commit messages, branch names and PR text are always in English, whatever language the user
chats in. If `--trailer` is unavailable (git < 2.32), put the `coauthor_trailer` line as the
last paragraph of the message.

### Finish the branch locally

```bash
git checkout <base> && git pull origin <base> && git checkout -b <branch-name>
git add <file1> <file2> ...
git commit -m "<subject>" -m "<body>" --trailer "<coauthor_trailer>"
git log -1 --format='%an|%cn|%G?'
```

Then stop at the commit: pushing is the human's step (next section).

### Commit message conventions

- Conventional format: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`
- Present tense: "add feature" not "added feature"
- Reference issues: `Closes #70` or ticket ID in body

</git-operations>

<push-and-pr>

## Push and PR (the human does it)

You never push and never open or edit anything on GitHub. When a branch is ready, write the
handoff file `.carter/state/handoff/<encoded-branch>.md` with your file tools, where
`<encoded-branch>` is the branch name with `%` written as `%25` and `/` as `%2F`
(`feat/x` → `feat%2Fx.md`). Front matter has exactly these keys, nothing else; quote the
`title` (it often contains a colon):

```markdown
---
title: "feat: one line, Conventional Commits style"
base: main
draft: false
head_sha: <40 lowercase hex characters: git rev-parse HEAD>
repo: <owner/name>
---

PR description in Markdown. Append the `footer` from `carter ops config --emit` after a `---`.
```

Write the description in the `carter-code-review` register when it is a code review (default
Standard); otherwise use the **Brief register** (defined in `carter-docs`): lead with the ask,
concise, scoped.

The file is untrusted input to the human's `carter pr`: it reads only these keys, scans the
title, branch and body for secrets, shows everything and asks. Put no tokens, keys, internal
URLs or credentials paths in it (the narrator's redaction pass comes first).

Then tell the user, in these words:

Run `carter push` and then `carter pr` in your own terminal, not through an agent.

Rules: never prefix the commands with `!` and never ask the user to paste them into the TUI;
never pass `--force` or any flag to a push; never write the handoff for a branch you did not
finish or whose commits you did not verify with `git log -1 --format='%an|%cn|%G?'`. For an
issue, a PR comment, a review or a release there is no agent path in this version: give the
user the drafted text (with the footer) to post themselves.

</push-and-pr>

<jira-operations>

## Jira Operations (via carter-atlassian MCP)

All Jira reads and writes go through the `carter-atlassian` MCP server (remote,
OAuth — no API tokens). Load the `carter-atlassian` skill for ticket conventions.
Jira writes are remote steps: carter-devops performs them, after the narrator's
redaction pass on the body.

Append the `footer` from `carter ops config --emit` to ALL body text.

</jira-operations>

<error-recovery>

## Error Recovery

| Error | Recovery |
|-------|----------|
| Local branch is behind its remote | `git pull origin <branch> --rebase`, then update the handoff `head_sha`; the human pushes |
| Branch already exists | Ask user: switch to existing branch or pick a new name? |
| A commit fails or `commits` is `refused` | Stop. Report `refusal_reason` (see the error table); do not retry with other flags |
| Jira auth error | Re-authenticate the `carter-atlassian` MCP server (OAuth) in your client |
| `gh` not found | Reads only: suggest installing the GitHub CLI (`gh`) |
| A push or `gh` write is denied (`E-POLICY`, "Blocked by configuration policy") | Expected: write the handoff file; never retry another way |
| `coauthor_trailer` missing or wrong | Re-run `carter ops config --emit` and use its value |

</error-recovery>

<boundaries>

## What is NOT ops:

Read operations run directly without the `ops:` prefix — no approval needed:

`git log`, `git status`, `git diff`, `git blame`, `git branch --list`,
`gh issue list`, `gh pr list`, `gh pr view`, `gh pr diff`, `gh pr checks`, JQL queries via MCP.

`gh` is read-only for agents and limited to `gh pr|issue|run view|list` (`pr diff`, `pr checks`),
`gh repo view` and `gh search`; `gh status` and `gh api` are denied. Where `gh` needs a
repository, put `-R <owner>/<repo>` **after** the subcommand (`gh pr view 3 -R o/r`, never
`gh -R o/r pr view 3`). `gh repo view` and `gh search repos` take it positionally and have no
`-R`: `gh repo view <owner>/<repo>`, `gh search repos <query>`.

</boundaries>

<plan-format>

## Plan Display Format

When showing the plan to the user, use this structure:

```
**Operation:** <type> (e.g., git-flow, gh-issue, jira-comment)
**Branch:** <name> (if applicable)
**Files:** <list> (if applicable)
**Message:** <commit message or body text>
**Attribution:** authored by you (your git config), unsigned; trailer: `<coauthor_trailer>`

Commands:
1. <exact command 1>
2. <exact command 2>
3. ...

Approve?
```

</plan-format>
