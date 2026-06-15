# RFC-0004 — Verification results

Records the §4 Verification Protocol runs. Referenced by the RFC `README.md`
(revision 3). Method mirrors P2: serialized JSON schema **bytes/4 ≈ tokens**, the
quantity the model pays for at the context prefix (per engineer review B3 — measure
schema bytes, not tool count).

**Run:** 2026-06-15 · **By:** spike (local) · **Host:** macOS, Docker 27.4.0, node v25.2.1,
npx 11.12.0 · **Probe:** MCP stdio `initialize` → `tools/list` (paginated), no token
required for `tools/list` (only tool *calls* need a valid PAT).

---

## V1 — Billing magnitude (class already resolved)

- **Class: token-metered**, settled — Copilot AI Credits price input+output+cached
  tokens × model rate, 1 credit = $0.01 [B1]. OpenCode BYO-key is token-metered by
  definition. Both meters reward token reduction.
- **Magnitude (per-model token→credit rates):** NOT captured here — requires the live
  GitHub billing dashboard + *Models and pricing* for the plan in use. **Open** (does
  not block §5; the saving is sized in tokens below and converts linearly to credits).
- Allowances for reference [B1]: Pro 1,500 · Pro+ 7,000 · Max 20,000 credits/mo.

## V2 — Static baseline (regression anchor)

Re-confirmed unchanged from P2 (method `os.path.getsize//4`):

- Agents total ~4,908 tok · `copilot-instructions.md` ~535 · skill descriptions
  (always-on) ~660 · 23 SKILL.md bodies ~25,927 (on-demand) · 11 sub-refs ~12,705 (lazy).
- Carter per-request static cost ≈ **1.6k–2.5k tok** (one agent + instructions + skill
  descriptions). Unchanged; baseline for future drift checks.

## V3 — MCP tool-schema token weight (THE decisive measurement)

GitHub MCP server, serialized `tools` array, bytes/4:

| Config | tools | schema bytes | ~tokens | tok/tool | Δ vs status quo |
|---|---|---|---|---|---|
| **archived `@modelcontextprotocol/server-github` (status quo)** | 26 | 15,854 | **3,963** | ~152 | — |
| official `github-mcp-server` **default** | 43 | 106,151 | 26,537 | ~617 | **+22,574 (+570%)** |
| official **scoped** `context,repos,issues,pull_requests` | 40 | 97,359 | 24,339 | ~608 | +20,376 (+514%) |
| official **scoped + `READ_ONLY`** | 24 | 55,909 | 13,977 | ~582 | +10,014 (+253%) |
| official **surgical `--tools` (10 read-only)** | 10 | 26,602 | 6,650 | ~665 | **+2,687 (+68%)** |
| official **context-only + read-only (floor)** | 3 | 5,978 | 1,494 | ~498 | −2,469 (only sub-archived config; 3 tools = unusable) |

**Findings (load-bearing — these invert the RFC's original §5 premise):**

1. **The archived server is the leanest at any useful tool count.** Its schemas are
   ~152 tok/tool vs the official server's ~580–665 tok/tool (**~4× more verbose** — richer
   descriptions + parameter docs).
2. **Swapping to the official server INCREASES the token surface**, not decreases it. The
   only official config below the archived footprint is context-only (3 tools, useless).
   The leanest *useful* official config (surgical 10-tool read-only) is still **+68%**.
3. **The "shrink the surface" rationale for §5 is FALSIFIED.** Migration is a token
   **cost** (+2.7k to +22.6k/request), not a saving. What survives is **security** (read-only
   genuinely removes write tools from the model surface — the archived server has no such
   switch and exposes all 26 incl. writes) and **maintenance** (the reference server is
   archived/unmaintained).
4. **Tool-count vs verbosity is a real trade-off** for accuracy: the official surgical
   config exposes **fewer** tools (10 vs 26 → better tool-choice per [A1]) but **more**
   tokens. Token-minimization and tool-choice-accuracy point in *opposite* directions here.

## V4 — Transport feasibility (engineer review B1)

- **Archived server (status quo):** `npx -y @modelcontextprotocol/server-github` over
  stdio — starts, handshakes, lists 26 tools. ✔ (current `npx` shape works.)
- **Official server:** `docker run -i --rm … ghcr.io/github/github-mcp-server` over stdio
  — image pulled (sha256:5c83…), starts, handshakes, lists tools across all configs. ✔
  **Docker transport proven on this host.** Implies a **new hard prereq** (Docker daemon)
  vs today's `uv`+Python+`npx` baseline — confirms engineer B1/OQ6 as a real gate.
- **Remote HTTP** (`https://api.githubcopilot.com/mcp/`) — NOT tested (needs OAuth/PAT +
  host remote-MCP support); still open as the Docker-free alternative.
- **Per-target wiring** (actually editing `mcp/copilot/*.json` + `mcp/opencode/*.json` and
  running `carter install`) — NOT exercised; this was a server-level transport probe only.

## V5 — Hop cost — NOT measured

Per-hop token overhead of a maestro multi-agent chain not instrumented this run
(needs live harness tracing). Remains open; sizes lever 5 / OQ3.

---

## Net consequence for the RFC

The verification gate did its job: **it caught a falsified premise before any code.** §5
must be **reframed from a "token-shrink" play to a security/maintenance trade-off** that
*costs* tokens — and the cheapest defensible official config is **surgical `--tools` +
read-only (~6,650 tok, +68%)**, not the scoped-toolset config the RFC originally proposed
(~13,977, +253%). Pure token-minimization argues to **stay on the archived server**; the
counter-argument is that it is unmaintained (a non-token risk). This is now a genuine
decision, not a foregone "swap to official." Carried into README revision 3.
