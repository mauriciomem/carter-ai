# Review: RFC-0004 — engineer

## Round 2 — 2026-06-15 — reviewed revision 3 — verdict: approve

The verification spike addressed my measurement and feasibility concerns directly.

- **B1 (blocking, transport) — PARTIALLY RESOLVED, correctly gated.** V4 proves the
  official server runs via Docker/stdio on-host (image pulls, handshakes, lists tools)
  and the archived `npx` path still works. The remaining gap — wiring through
  `carter install` on both targets + the remote-HTTP fallback — is now an explicit
  pre-code gate (§C.5, OQ6), not a buried footnote. Acceptable: the RFC no longer
  *assumes* transport parity, it *schedules proving it*.
- **B2 (blocking, installer shape) — RESOLVED.** r3 acknowledges the installer surgery
  (parameterized emitter, the ~L786/~L948 duplicated list) and names the effort M–L.
- **B3 (V3 method) — RESOLVED.** V3 measured serialized **schema bytes/4**, not tool
  count, exactly as asked. The result (archived 152 tok/tool vs official ~580–665) is
  the kind of number that only shows up when you measure the right thing.
- **B4 (bash bypass) — RESOLVED.** §C.4 + Trade-offs now state read-only is MCP-surface
  only; shell writes stay under RFC-0002. No false-security read.
- **B5 (tests) — RESOLVED.** MCP-wiring asserts + hardcoded list flagged as explicit
  plan tasks.

**Feasibility verdict:** the change is well-understood and de-risked enough to plan once
OQ6/V4 closes. Adopting surgical `--tools` read-only (6,650 tok) over the scoped-toolset
config (13,977) is the right engineering call — it's both leaner and a smaller blast
surface. Approving r3.

Non-blocking: pin the official image by digest (not `:latest`) in the committed config —
reproducible installs + supply-chain hygiene. Note it in the plan.

## Round 1 — 2026-06-15 — reviewed revision 2 — verdict: request-changes

File:line evidence is accurate and the security direction (closing RFC-0002's
unenforceable "read-only") is sound. But the §5 change is **larger and less portable
than the RFC implies**, and one measurement method is wrong. Two blocking feasibility
items before this can become a plan.

### B1 — BLOCKING: cross-target server transport is unverified, not a detail

Today both configs use `npx` + stdio:
- [mcp/copilot/github.json](../../../mcp/copilot/github.json): `npx @modelcontextprotocol/server-github`
- [mcp/opencode/github.json](../../../mcp/opencode/github.json): `type: local`, command array

The official `github/github-mcp-server` ships as **Docker** (`ghcr.io/github/github-mcp-server`)
or **remote HTTP** (`https://api.githubcopilot.com/mcp/`). Neither is a drop-in for the
current `npx` shape:

- **Docker** ⇒ requires a running daemon on the user's machine (new hard prereq; the
  README currently only requires `uv` + Python), and the JSON command/args change shape
  on **both** targets.
- **Remote HTTP** ⇒ avoids Docker but needs OAuth/PAT and host support for remote MCP;
  OpenCode's `type: local` config path may not accept it uniformly.

OQ6 *names* this but the RFC treats it as a documentation footnote. It is a **prerequisite
gate**: pick the transport (Docker vs remote) and prove it works on **both** copilot and
opencode targets *before* §5 is planned. Recommend a tiny spike: wire the official server
on each target, confirm it starts and lists tools, record the working config shape.

### B2 — BLOCKING: read-only-default + write-opt-in is installer surgery, not a JSON tweak

`configure_mcp_servers` (`carter/installer.py` ~L786) emits **one flat entry per server**
from a hardcoded list, flat-merged into each target. Supporting "read-only by default,
write as opt-in" means either two server defs (`-ro`/`-rw`) or a parameterized emitter +
per-agent wiring — a structural change to the installer and the `MCP_SERVERS` list, plus
the uninstall path that repeats the literal list (RFC-0002 reviews noted the duplicated
triple at ~L948). The "S/M effort" in the lever table understates this; with B1 it is
**M–L**. Tie the effort estimate to the option chosen in the architect's B1.

### B3 — SHOULD-FIX: V3 measures the wrong quantity (tool *count* ≠ tokens)

V3 says "use `github-mcp-server tool-search`/tool-list to count." Token cost is the
**serialized JSON schema** injected at the context prefix, not the number of tools. Two
toolsets with equal tool counts can differ greatly in schema bytes (param descriptions,
enums, nested objects). Fix the method: capture the actual serialized `tools` array from
the MCP `tools/list` (or `initialize`) response for each config and measure **bytes/4**,
same method as P2 — so V3 is comparable to the rest of the RFC's numbers.

### B4 — SHOULD-FIX: don't let "read-only MCP" read as "no writes possible"

`--read-only` not registering write tools is genuine model-surface enforcement (good, and
stronger than the archived server). But it does **not** stop writes via the **bash/`gh`/
`git` path** against the same token — RFC-0002's universal-bypass finding still holds. The
RFC mostly gets this right (it defers credential scope to RFC-0003), but §5.3's "real
tool-surface denial" should add one clause: *"MCP write surface only; the shell path is
out of scope here and remains governed by RFC-0002."* Prevents a false-security read.

### B5 — NIT: tests will break; enumerate them in the plan
Repo memory already flags hardcoded-count fragility in `tests/test_install.py` for skills;
MCP-wiring assertions (server name/command/args) will similarly break on the transport
swap. Not blocking for the RFC, but the resulting plan must list the test files to update
as an explicit task, not discover them mid-implementation.

### Endorsements
- Evidence (`installer.py`/`mcp/*.json`/`config.py` references) verified accurate.
- Using the official, maintained server over the **archived** reference server is correct
  on security and longevity grounds independent of the token saving.
- Keeping V2–V3 as a hard gate is right; just fix the V3 method (B3).

**To clear to `approve`:** resolve B1 (transport spike) and B2 (installer-shape decision,
coupled to the architect's A′-vs-B call), fix B3's measurement, add B4's clause.
