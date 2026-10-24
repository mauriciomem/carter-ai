# Tutorial: Risk-Based Strictness Policy

Carter's safety posture is **enforced where the runtime allows it**, not just
described in prose. This tutorial shows how to turn the policy on, what each level
does, and how to customize, audit, and override it.

> Background: the decision is recorded in
> [ADR-0005](adr/0005-risk-based-strictness-policy.md); the canonical config
> schema lives in [reference/frontmatter.md](reference/frontmatter.md).

---

## The mental model

Three ideas work together:

1. **Risk categories (4)** — every tool or command maps to a risk band:
   `read`, `local-write`, `remote-write`, `dangerous` (ADR-0010 D4).
2. **A strictness level** — one knob (`guarded` / `strict`) decides whether each
   category is allowed, asks for confirmation, gates behind a handoff, or is denied.
3. **A per-agent allowlist** — independent of level, each agent may only act in
   categories it's allowed. A category not on an agent's list is **denied** for
   that agent, always (deny-by-default).

The effective gate for any action is the **most restrictive** of the level's gate
and the agent's allowlist.

### The risk categories

| Category | Meaning | Examples |
|----------|---------|----------|
| **read** | reads, never mutates | file read, `git status/log/diff`, MCP GET |
| **local-write** | local-only changes | file edit, `git add/commit`, run tests |
| **remote-write** | publishes to a remote / reads secrets | `git push`, PR/issue create·merge, MCP POST/PATCH/DELETE, `vault read`, `.env` reads |
| **dangerous** | infra-mutating or irreversible | `terraform apply/destroy`, `kubectl apply`, `helm upgrade`, `rm -rf`, `git reset --hard`, `git push --force` |

Secret reads fold into `remote-write` (they gate identically). Outward content is
**not** a category — it is an enforced redaction handoff (see Step 5).

### The gate vocabulary

- **allow** — runs silently.
- **ask** — confirm with the human first.
- **gate** — `ask` **plus** a required handoff to the owning agent / a checkpoint.
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

## Step 2 — Understand how it's enforced (per target)

Carter is a **scaffolder, not a runtime** — it can't intercept a tool call itself.
What it *can* do is emit each target's native enforcement, and honestly label the
rest. Every agent file carries a deterministic `<!-- carter:policy {...} -->` comment
right after the frontmatter (the source of truth `carter check` lints), plus native
frontmatter keys where the target supports them:

| Target | What's emitted | Enforcement |
|--------|----------------|-------------|
| **OpenCode** | `permission:` (edit / bash command-globs / webfetch) | **runtime** — OpenCode honors `permission` |
| **Copilot / VS Code** | enforced `tools:` allowlist + per-agent MCP scope | tool allowlist enforced; per-category gating is advisory (prose) |
| **all** | both of the above | each runtime reads the keys it understands |

A guarded devops agent on OpenCode, for example, emits:

```markdown
---
mode: subagent
model: anthropic/claude-sonnet-5-5
permission:
  edit: allow
  bash: {'*': allow, git push*: ask, terraform apply*: ask, rm -rf*: ask, ...}
  webfetch: allow
---
<!-- carter:policy {"level":"guarded","allow":["dangerous","local-write","read","remote-write"],"gates":{"dangerous":"gate","local-write":"allow","read":"allow","remote-write":"ask"}} -->
```

Local shell stays open (so the agent can run tests and local `git`), while
remote/destructive commands carry their gate — and commands in a category the
agent doesn't hold are denied.

---

## Step 3 — Validate with `carter check`

`carter check` lints that the **installed** agent files still match the declared
policy, and surfaces honest gaps:

```bash
carter check .
```

It reports an error if an agent's emitted policy comment / `permission` / `tools` /
`model` has
drifted from the model (e.g. someone hand-edited a gate), and:

- **Hard ack for `strict` on a non-enforcing target.** If you set `strict` but the
  target can't natively enforce per-category gates (Copilot/VS Code), `carter
  check` **fails closed** — you must acknowledge the degradation explicitly:

  ```bash
  carter check . --accept-degraded
  ```

  Without the flag the command fails rather than silently shipping a weaker
  guarantee than `strict` implies.

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

## Step 5 — External content & redaction (enforced handoff)

Outward content is **not** a risk category — it is an **enforced `gate`-tier
redaction handoff** (ADR-0010 D5). The narrator is the external-content specialist
(first-class, like the architect for design); it holds `read` + `local-write` only.

- **narrator authors and redacts** the content locally; **devops transmits** it (it
  is the sole `remote-write` holder). The single-pusher invariant is structural:
  narrator never pushes directly.
- **Substantive** outward content (release notes, Jira bodies, PR descriptions,
  announcements) **must** pass the narrator's full redaction pass before that
  handoff — a `gate`-tier step encoded in the allowlist, not a convention.
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
  (you proceeded on trust where no native gate exists).
- One entry per action — there is no blanket or session-wide override.
- Every entry carries `"authorized": false` and lands in `~/.carter/audit.log`.

---

## Quick reference

| Task | Command / setting |
|------|-------------------|
| Set the level | `policy.level: guarded\|strict` in `carter.yaml` |
| Re-emit agents after a change | `carter update .` |
| Validate the install | `carter check .` |
| Accept a degraded `strict` target | `carter check . --accept-degraded` |
| Tighten/loosen a category | `policy.overrides: {dangerous: deny}` |
| Record an override | `carter ops policy-override --category … --action … --tier …` |
| Pin a per-agent model | `models.overrides: {engineer: {copilot: "Claude Haiku 5.5"}}` |
| Set reasoning effort | global on the harness (`copilot --effort high`); default `high`, raise to `xhigh` for thinker-heavy work — Carter emits no per-agent effort |

## See also

- [ADR-0005](adr/0005-risk-based-strictness-policy.md) — the decision and its rationale
- [reference/frontmatter.md](reference/frontmatter.md) — canonical `policy` schema
- [carter-ops.md](carter-ops.md) — the override ledger + write-operation protocol
- [getting-started.md](getting-started.md) — overall setup walkthrough
