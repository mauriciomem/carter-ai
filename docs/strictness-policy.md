# Tutorial: Risk-Based Strictness Policy

Carter's safety posture is **enforced where the runtime allows it**, not just
described in prose. This tutorial shows how to turn the policy on, what each level
does, and how to customize, audit, and override it.

> Background: the decision is recorded in
> [ADR-0005](../design/adr/0005-risk-based-strictness-policy.md); the canonical config
> schema lives in [reference/frontmatter.md](reference/frontmatter.md).

---

## The mental model

Three ideas work together:

1. **Risk categories (R0–R6)** — every tool or command maps to a risk band, from
   harmless reads to irreversible/destructive actions.
2. **A strictness level** — one knob (`loose` / `guarded` / `strict`) decides
   whether each category is allowed, asks for confirmation, gates behind a
   handoff, or is denied.
3. **A per-agent allowlist** — independent of level, each agent may only act in
   categories it's allowed. A category not on an agent's list is **denied** for
   that agent, always (deny-by-default).

The effective gate for any action is the **most restrictive** of the level's gate
and the agent's allowlist.

### The risk categories

| Category | Meaning | Examples |
|----------|---------|----------|
| **R0** read | reads, never mutates | file read, `git status/log/diff`, MCP GET |
| **R1** local-write | local-only changes | file edit, `git add/commit`, run tests |
| **R2** remote-write | publishes to a remote | `git push`, PR/issue create·merge, MCP POST/PATCH/DELETE |
| **R3** infra-mutate | changes live infrastructure | `terraform apply/destroy`, `kubectl apply`, `helm upgrade` |
| **R4** secret-access | reads secrets | `.env`/secret files, vault reads |
| **R5** destructive | irreversible | `rm -rf`, `git reset --hard`, `git push --force` |
| **R6** external-publish | outward content (overlay) | Slack, PR descriptions, release notes, Jira comments |

### The gate vocabulary

- **allow** — runs silently.
- **ask** — confirm with the human first.
- **gate** — `ask` **plus** a required handoff to the owning agent / a checkpoint.
- **deny** — blocked; a deliberate single-action override is required.

### How the levels map categories to gates

| Category | `loose` | `guarded` | `strict` |
|----------|---------|-----------|----------|
| R0 read | allow | allow | allow |
| R1 local-write | allow | allow | allow |
| R2 remote-write | allow | ask | gate |
| R3 infra-mutate | allow | gate | **deny** |
| R4 secret-access | allow | ask | gate |
| R5 destructive | allow | gate | **deny** |
| R6 external-publish | allow | gate | gate |

`loose` is exactly today's behaviour — advisory only, nothing blocks.

### Who can do what (the shipped allowlist)

| Agent | Allowed categories | In plain terms |
|-------|--------------------|----------------|
| maestro, architect, learner | R0 | read only |
| engineer, pm | R0, R1 | read + local work |
| **devops** | R0, R1, R2, R3, R4, R5 | the **only** pusher / infra-mutator |
| **narrator** | R0, R1, R6 | the **only** external author |

So even at `loose`, an engineer asking to `terraform apply` is out of scope — that
is devops's category. The level tunes *how hard* the in-scope gates bite.

---

## Step 1 — Choose a level

The policy lives in a `policy` block in `carter.yaml`:

```yaml
policy:
  level: guarded        # loose | guarded | strict
  unknown_tool: ask     # gate for a tool not in the risk map: allow | ask | deny
  overrides: {}         # category -> gate, e.g. {R2: deny}
  audit_overrides: true # log escape-hatch overrides via `carter ops`
```

**Defaults (no surprises):**

- A **new** install (`carter init`) defaults to **`guarded`**.
- An **existing** config that omits the `policy` block resolves to **`loose`** —
  so upgrading Carter never changes your behaviour until you opt in.

Pick by context:

| Level | Use it when |
|-------|-------------|
| `loose` | You want advice, not gates (or you're preserving legacy behaviour). |
| `guarded` | Day-to-day default — remote/infra/destructive actions pause for you. |
| `strict` | Regulated or prod-critical work — infra-mutate and destructive are denied outright. |

After editing `carter.yaml`, re-emit the agents:

```bash
carter update .
```

You'll see the migration notice when enforcement is real:

```
ℹ  Strictness policy is 'guarded': remote-write, infra-mutate, secret-access,
   destructive, and external-publish actions are now gated per the risk taxonomy.
```

---

## Step 2 — Understand how it's enforced (per target)

Carter is a **scaffolder, not a runtime** — it can't intercept a tool call itself.
What it *can* do is emit each target's native enforcement, and honestly label the
rest. Every agent's frontmatter carries a deterministic `policy:` block (the
source of truth), plus native keys where the target supports them:

| Target | What's emitted | Enforcement |
|--------|----------------|-------------|
| **OpenCode** | `permission:` (edit / bash command-globs / webfetch) | **runtime** — OpenCode honors `permission` |
| **Copilot / VS Code** | enforced `tools:` allowlist + per-agent MCP scope | tool allowlist enforced; per-category gating is advisory + `hooks` |
| **all** | both of the above | each runtime reads the keys it understands |

A guarded devops agent on OpenCode, for example, emits:

```yaml
policy:
  level: guarded
  allow: [R0, R1, R2, R3, R4, R5]
  gates: {R0: allow, R1: allow, R2: ask, R3: gate, R4: ask, R5: gate}
permission:
  edit: allow
  bash: {"*": allow, "git push*": ask, "terraform apply*": ask, "rm -rf*": ask}
  webfetch: allow
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

It reports an error if an agent's emitted `policy`/`permission`/`tools` has
drifted from the model (e.g. someone hand-edited a gate), and:

- **Hard ack for `strict` on a non-enforcing target.** If you set `strict` but the
  target can't natively enforce per-category gates (Copilot/VS Code), `carter
  check` **fails closed** — you must acknowledge the degradation explicitly:

  ```bash
  carter check . --accept-degraded     # also valid on `carter install`
  ```

  Without the flag in a non-interactive context, the command fails rather than
  silently shipping a weaker guarantee than `strict` implies.

- **Redaction contradiction warning.** At `guarded`/`strict`, the redaction pass
  is forced (see Step 5); if you've also set `redaction.enabled: false`,
  `carter check` warns about the contradiction.

---

## Step 4 — Customize (optional)

Everything is dict-shaped so your overrides **merge** with the shipped defaults
(they never wipe them). All three keys are validated at load time.

**Tighten or loosen a category** with `overrides`:

```yaml
policy:
  level: guarded
  overrides:
    R2: deny      # make every remote-write a hard deny, beyond guarded's `ask`
```

**Add a custom tool to the risk map** with `tool_risk`:

```yaml
policy:
  tool_risk:
    my_deploy_script: R3   # treat it as infra-mutate
```

**Adjust an agent's allowlist** with `allowlist` (use with care — it can break the
single-pusher invariant):

```yaml
policy:
  allowlist:
    engineer:
      R2: true     # let engineer remote-write directly (normally a devops handoff)
```

Invalid values fail fast: an unknown `level`, an override gate that isn't
`allow|ask|gate|deny`, or an override category outside `R0–R6` raises a clear
config error.

---

## Step 5 — External content & redaction (R6)

R6 is special: it's a **content overlay** that composes with whatever transport
carries it. A `gh pr comment` is both R2 (remote-write transport) and R6 (outward
content) — they compose, they don't collide.

- **narrator authors and redacts** the content (R6); **devops transmits** it
  (R2). This keeps the single-pusher invariant: narrator never pushes directly.
- **Short-form, low-risk** outward content (a one-line PR comment) needs only an
  inline redaction check; **substantive** content (release notes, Jira bodies, PR
  descriptions) goes through the full narrator gate.
- At **`guarded` and `strict`**, the narrator's redaction rules are rendered
  **regardless of `redaction.enabled`** — disabling redaction at an enforcing
  level can't silently ship a rule-less narrator. (At `loose`, disabling redaction
  with the narrator enabled prints a setup warning instead.)

---

## Step 6 — The escape hatch

When a gate blocks something you genuinely need to do, record a deliberate
single-action override. **Override ≠ authorization** — the ledger *records* your
decision; it cannot lift a platform `deny`.

```bash
carter ops policy-override \
  --category R3 \
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
| Set the level | `policy.level: loose\|guarded\|strict` in `carter.yaml` |
| Re-emit agents after a change | `carter update .` |
| Validate the install | `carter check .` |
| Accept a degraded `strict` target | `carter check . --accept-degraded` |
| Tighten/loosen a category | `policy.overrides: {R3: deny}` |
| Map a custom tool | `policy.tool_risk: {tool: R2}` |
| Record an override | `carter ops policy-override --category … --action … --tier …` |

## See also

- [ADR-0005](../design/adr/0005-risk-based-strictness-policy.md) — the decision and its rationale
- [reference/frontmatter.md](reference/frontmatter.md) — canonical `policy` schema
- [carter-ops.md](carter-ops.md) — the override ledger + write-operation protocol
- [getting-started.md](getting-started.md) — overall setup walkthrough
