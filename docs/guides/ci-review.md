# Review-only CI: let Carter review your pull requests

Carter can review every pull request in GitHub Actions and put the review in the job summary.
This is **CI context E: review only**. The run reads the change, reports findings and **makes no
commits**: it has `contents: read` and nothing else, no push, no comment (unless you opt in),
no edit. Commits in CI (contexts C and D) do not exist yet.

You do not need this to use Carter. It is for teams that want a second pair of eyes on every PR
without handing a model any write access.

> [!NOTE]
> The review is advice from an AI model. It can be wrong and it can be steered by the text of a
> pull request. That is why the model gets no tool that could do harm; see
> [What it cannot do](#what-it-cannot-do).

## Set it up (about five minutes, in your own terminal)

1. In the repository, run `carter ci install review --dry-run` and read the workflow. Then run
   `carter ci install review`. It writes **one file**, `.github/workflows/carter-review.yml`, and
   nothing else. It refuses in an agent shell and without a terminal: a workflow is executable
   config, so a person installs it, never an agent.
2. Commit and push the file yourself. Carter changes nothing on GitHub.
3. On GitHub, create the **environment** `carter-review` (Settings → Environments) and add the
   **secret** `LLM_API_KEY` to it: a provider key that is throwaway or has a spending limit. It is
   the only secret the workflow reads.
4. Optional **repository variables** (Settings → Secrets and variables → Actions → Variables, not
   secrets): `CARTER_CI_MODEL` (`provider/model`) and `CARTER_CI_KEY_ENV` (the variable name the
   provider reads, default `ANTHROPIC_API_KEY`).
5. Add `/.github/workflows/ @your-team` to `CODEOWNERS` and require review for it.

Open a pull request from a branch **in the same repository**. The job `review` runs, finishes
under 15 minutes and writes the review to the run's summary page.

Run `carter ci install review` again after upgrading Carter to refresh the file. If you edited the
file, Carter keeps your version and says so; `--dry-run` shows what it would write, `--force`
replaces yours.

## What the workflow does

| Rule | How |
|------|-----|
| Runs on `pull_request` only | Never `pull_request_target` (it would run fork code with your secrets) and never `workflow_run` |
| `contents: read` | At workflow and job level; there is no `write` anywhere unless you opt in to comments |
| Pinned | Every action is pinned to a commit SHA with its version in a comment; `actions/checkout` does not keep credentials |
| Bounded | `timeout-minutes: 15` and `concurrency` with `cancel-in-progress` (a new push cancels the old review) |
| One secret | `LLM_API_KEY`, in the environment `carter-review`, read only in a step's `env` |
| Forks | A pull request from a fork is **skipped, not failed**: the job's `if:` compares the head repository with this one, and a first step skips the review when the secret is empty (Dependabot, or no secret set). Fork PRs never get secrets from GitHub, and Carter does not try to get around that |
| No script injection | No `${{ }}` expression inside a `run:` script; the pull request's values go through `env` |
| Output | `$GITHUB_STEP_SUMMARY` |

`carter ci check FILE` applies the same rules to any workflow file (it is what Carter's own tests
and CI use, together with `actionlint` when it is installed).

## What it cannot do

The reviewer is a headless OpenCode with a **static profile**: one agent that may `read`, `glob`
and `grep` the checkout, and nothing else. No shell, no edit or write, no web, no sub-agents, no
`carter_*` tools, no files outside the checkout (so not `/proc/self/environ`, not your home). It
runs without `--auto`, so anything that would need a yes is refused. The key is passed to it under
one variable name, built into a from-scratch environment, and masked in everything Carter prints
or writes. The title, branch names, file names and diff of the pull request are data inside one
message, never arguments.

On top of that, Carter's identity resolver refuses commits in a review run: with `CI` or
`GITHUB_ACTIONS` set, or `CARTER_IDENTITY_MODE=review`, `carter commit` stops with `E-CI-REVIEW`,
the `identity env` answer carries no signing key, and `carter ops config --emit` says `mode: review`
and `commits: refused`.

## Opt in to a comment (this widens the scope)

`carter ci install review --comment` adds a second job, `comment`, whose only permission is
`pull-requests: write`. It has no checkout, no Carter and no model: it downloads the review text
the first job saved and posts it as **one comment** with `gh`. The `review` job itself stays
`contents: read`. Model text can contain `@mentions`; Carter inserts an invisible character so they
do not notify anyone. If you do not want any write permission, do not use `--comment`; the summary
page is enough. Running the command again without `--comment` removes the job (if you did not
edit the file).

## Modes

`mode` resolves from `CARTER_IDENTITY_MODE`, then `[identity] mode` in `~/.carter/config.toml`,
then `auto`. Values: `auto`, `interactive`, `review`. `auto` is `review` when a CI is detected
(`GITHUB_ACTIONS=true`, or `CI` set to a true value) and `interactive` otherwise. Carter never
works out that it may commit: in a detected CI even an explicit `interactive` is refused (that
would be context C), and so are `commit` and `scheduled` (contexts C and D, not built). An unknown
value is `E-CONFIG`, with no fallback.

> [!WARNING]
> If you export `CI=true` in your own shell, `carter commit` and the agents' commits are refused
> with `E-CI-REVIEW` until you unset it. That is the rule working as designed.

## Residuals

- A pull request can still try to talk the model into saying something misleading in the review.
  The review is advice; a person decides.
- The workflow installs Carter and OpenCode from PyPI and npm by **version**, not by hash. A
  compromised release would run with your provider key in that job (and `contents: read`). Pin
  and review upgrades like any dependency.
- The key you give the environment can be spent by anyone who can open a pull request from a
  branch in your repository. Use a key with a spending limit and consider required reviewers on the
  environment.
- GitHub shows a first-time contributor's workflow as "needs approval"; that setting is yours.
- The first real run on GitHub (fork skip, summary, timeout) is checked by hand; CI cannot do it.

See also: [Safety and permissions](safety-and-permissions.md), [Push tool](push-and-pr-tools.md).
