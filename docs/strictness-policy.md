# Tutorial: Risk-Based Strictness Policy

Carter's safety posture is emitted as OpenCode
[`permissions:`](https://opencode.ai/v2/docs/permissions/) on every agent, so
OpenCode enforces it at runtime. This tutorial shows what each level does, how it is
emitted, where it stops, and how to customize, audit, and override it.

> Background: ADR-0014 (OpenCode-only emission) builds on the categories from
> ADR-0005 / ADR-0010. The config schema lives in
> [reference/frontmatter.md](reference/frontmatter.md).

---

## The mental model

Three ideas work together:

1. **Risk categories (4)** — every tool or command maps to a risk band:
   `read`, `local-write`, `remote-write`, `dangerous`.
2. **A strictness level** — one knob (`guarded` / `strict`) decides whether each
   category is allowed, asks for confirmation, or is denied.
3. **A per-agent allowlist** — independent of level, each agent may only act in
   categories it's allowed. A category not on an agent's list is **denied** for
   that agent, always (deny-by-default).

The effective gate for any action is the **most restrictive** of the level's gate
and the agent's allowlist.

### The risk categories

| Category | Meaning | Examples |
|----------|---------|----------|
| **read** | reads, never mutates | file read, glob/grep, `git status/log/diff` |
| **local-write** | local-only changes | file edit, `git add/commit`, run tests |
| **remote-write** | publishes to a remote / reads secrets | `git push`, PR/issue create·merge, `vault read` |
| **dangerous** | infra-mutating or irreversible | `terraform apply/destroy`, `kubectl apply`, `helm upgrade`, `rm -rf`, `git reset --hard`, `git push --force` |

Secret reads fold into `remote-write` (they gate identically); `.env` reads ask for
every agent. MCP tool calls get no category rule and always ask (see Step 2).
Outward content is **not** a category — it is an advisory redaction handoff (see Step 5).

### The gate vocabulary

- **allow** — runs silently.
- **ask** — confirm with the human first.
- **gate** — Carter's "ask, and hand off to the owning agent" tier. OpenCode has no
  such effect, so **`gate` is emitted as `ask`**; the handoff part is prompt guidance only.
- **deny** — blocked; a deliberate single-action override is required.

### How the levels map categories to gates

| Category | `guarded` | `strict` |
|----------|-----------|----------|
| read | allow | allow |
| local-write | allow | allow |
| remote-write | ask | gate |
| dangerous | gate | **deny** |

`guarded` is the floor — in-scope risky actions pause for you; nothing is silently
allowed past `read`/`local-write`.

### Who can do what (the shipped allowlist)

| Agent | Allowed categories | In plain terms |
|-------|--------------------|----------------|
| maestro, architect, learner | read | read only |
| pm, narrator, engineer, security | read, local-write | read + local work |
| **devops** | read, local-write, remote-write, dangerous | the **only** pusher / infra-mutator |

So an engineer asking to `terraform apply` is out of scope at any level — that is
devops's category. The narrator authors outward content locally but does **not**
hold `remote-write`; it reaches a remote only via the redaction handoff to devops
(Step 5). The level tunes *how hard* the in-scope gates bite.

---

## Step 1 — Choose a level

The policy lives in a `policy` block in `carter.yaml`:

```yaml
policy:
  level: guarded        # guarded | strict
  overrides: {}         # category -> gate, e.g. {remote-write: deny}
```

**Defaults (no surprises):**

- `guarded` is the floor and the default for **everything** — a new install, an
  existing config that omits the `policy` block, and any unrecognized level all
  resolve to `guarded`.

Pick by context:

| Level | Use it when |
|-------|-------------|
| `guarded` | Day-to-day default — remote/infra/destructive actions pause for you. |
| `strict` | Regulated or prod-critical work — `dangerous` (infra-mutate / destructive) actions are denied outright. |

After editing `carter.yaml`, re-emit the agents:

```bash
carter update .
```

You'll see the policy notice (both levels enforce gates):

```
ℹ  Strictness policy is 'guarded': remote-write and dangerous (infra-mutate /
   destructive) actions are gated per the risk taxonomy.
```

---

## Step 2 — Understand how it's enforced

Carter is a **scaffolder, not a runtime** — it can't intercept a tool call itself.
It writes each agent's policy as an ordered V2 `permissions:` list in the agent's
frontmatter, and OpenCode enforces it. **The last matching rule wins.** Every agent
gets these rules, in this order:

1. `*` / `*` → **ask** — the baseline. Anything not listed below prompts you.
2. `read`, `glob`, `grep`, `skill`, `question` → allow.
3. Reading `*.env` / `*.env.*` → ask again; `*.env.example` → allow.
4. `~/.carter/*` → `external_directory` + `read` allowed; agents holding
   `local-write` may also `edit` `~/.carter/memories/*`.
5. `subagent *` → deny. Maestro alone then gets `subagent carter-*` → allow (a flat
   chain: specialists never re-delegate).
6. Category rules: `edit`, `shell`, `webfetch` → allow for `local-write` holders,
   ask for read-only agents. Then risky shell globs (`git push *`, `terraform apply *`,
   `rm -rf *`, `git push --force *`, …) take their category's effect, or **deny** if
   the agent doesn't hold that category.

MCP tools, `websearch`, `execute` and any other action have no explicit rule, so
they fall to the `ask` baseline.

A guarded devops agent, abbreviated:

```yaml
---
description: "DevOps Engineer — CI/CD, infrastructure as code, ..."
mode: subagent
model: anthropic/claude-sonnet-5-5
permissions:
- {action: '*', resource: '*', effect: ask}
- {action: read, resource: '*', effect: allow}
# ... discovery, .env, ~/.carter and subagent rules ...
- {action: shell, resource: '*', effect: allow}
- {action: shell, resource: git push *, effect: ask}
- {action: shell, resource: terraform apply *, effect: ask}   # dangerous: gate -> ask
---
```

Local shell stays open (so the agent can run tests and local `git`), while remote
and destructive commands carry their gate. For a read-only agent such as the
architect, the same shell globs are `deny`.

### Known limits

Be clear about what this does **not** guarantee:

- **`gate` is `ask`.** OpenCode effects are only allow/ask/deny.
- **"Allow always" bypasses an ask.** Choosing it at a prompt saves a durable,
  project-scoped allow rule
  ([permissions](https://opencode.ai/v2/docs/permissions/)). That applies to every
  `ask`, including gated ones. Use "Allow once" for risky actions.
- **Shell globs are representative, not exhaustive.** A command that isn't in the
  list falls to the agent's `shell` rule (allow for `local-write` holders).
- **The redaction handoff is advisory** (see Step 5).

`deny` rules hold; use `strict` (or a `deny` override) where an ask is not enough.

---

## Step 3 — Validate with `carter check`

```bash
carter check .
```

It fails if:

- an agent's emitted `permissions:` or `model` differs from what `carter.yaml`
  generates (rule order counts), e.g. someone hand-edited a rule;
- an agent file carries V1 keys (`permission`, `tools`, `bash`, …) that OpenCode
  would ignore next to `permissions`;
- OpenCode doesn't load an agent, or loads it with different rules. Carter runs
  `opencode debug agents` for this; it skips the step with a warning if `opencode`
  isn't on `PATH`, and `--no-harness` skips it explicitly.

This proves what Carter wrote matches what you declared, and that OpenCode accepted
it. It cannot prove a human never clicked "Allow always".

---

## Step 4 — Customize (optional)

Everything is dict-shaped so your overrides **merge** with the shipped defaults
(they never wipe them). `overrides` is validated at load time.

**Tighten or loosen a category** with `overrides`:

```yaml
policy:
  level: guarded
  overrides:
    remote-write: deny   # make every remote-write a hard deny, beyond guarded's `ask`
```

**Adjust an agent's allowlist** with `allowlist` (use with care — it can break the
single-pusher invariant):

```yaml
policy:
  allowlist:
    engineer:
      remote-write: true   # let engineer remote-write directly (normally a devops handoff)
```

Invalid values fail fast: an override gate that isn't `allow|ask|gate|deny`, or an
override category outside `read|local-write|remote-write|dangerous`, raises a clear
config error. (An unrecognized `level` resolves to `guarded` silently.)

---

## Step 5 — External content & redaction (advisory handoff)

Outward content is **not** a risk category — it is a **redaction handoff**. The narrator is the external-content specialist
(first-class, like the architect for design); it holds `read` + `local-write` only.

- **narrator authors and redacts** the content locally; **devops transmits** it (it
  is the sole `remote-write` holder). That part is enforced: the narrator's
  `git push *` rule is `deny`.
- **Substantive** outward content (release notes, Jira bodies, PR descriptions,
  announcements) should pass the narrator's full redaction pass before that
  handoff. **This is prompt-level guidance, not harness-enforced:** nothing in
  OpenCode stops devops from transmitting unredacted content. Review what goes out.
  **Short-form, low-risk** content (a one-line PR comment) needs only an inline
  redaction check.
- The narrator's redaction rules are always rendered; `redaction.categories`
  selects which categories they cover.

---

## Step 6 — The escape hatch

When a gate blocks something you genuinely need to do, record a deliberate
single-action override. **Override ≠ authorization** — the ledger *records* your
decision; it cannot lift a platform `deny`.

```bash
carter ops policy-override \
  --category dangerous \
  --action "terraform apply -target=module.network" \
  --tier native-deny \
  --reason "approved exception, change ticket OPS-1234"
```

- `--tier` says what kind of gate you overrode: `native-deny` (you relaxed the
  emitted config), `native-ask` (you confirmed a prompt), or `prose-backstop`
  (you proceeded on trust where only prompt guidance applies, e.g. redaction).
- One entry per action — there is no blanket or session-wide override.
- Every entry carries `"authorized": false` and lands in `~/.carter/audit.log`.

---

## Quick reference

| Task | Command / setting |
|------|-------------------|
| Set the level | `policy.level: guarded\|strict` in `carter.yaml` |
| Re-emit agents after a change | `carter update .` |
| Validate the install | `carter check .` |
| Skip the OpenCode load check | `carter check . --no-harness` |
| Tighten/loosen a category | `policy.overrides: {dangerous: deny}` |
| Record an override | `carter ops policy-override --category … --action … --tier …` |
| Pin a per-agent model | `models.overrides: {engineer: anthropic/claude-haiku-5-5}` |

## See also

- ADR-0014 (emission) and ADR-0005 (categories) — the decisions and their rationale
- [reference/frontmatter.md](reference/frontmatter.md) — canonical `policy` schema
- [carter-ops.md](carter-ops.md) — the override ledger + write-operation protocol
- [getting-started.md](getting-started.md) — overall setup walkthrough
