# Review: RFC-0006 — engineer

## Round 2 — 2026-06-30 — reviewed revision 2 — verdict: approve

Both r1 blockers resolved. **E1 (assertions as a spec) — fully addressed:** §D-G now commits the exact
fixed-phrase assertions — authorization = `"authorized"` + (`"refuse"`|`"decline"`) + `"destructive"` +
`"mass targeting"`; untrusted-input = `"data to analyze"` + (`"never as instructions"`|`"not as
instructions"`), *identical* to the maestro test's grep — plus the verbatim `<authorization>` and
`Untrusted input.` blocks they assert against. That's an executable spec, not a narrative; I verified the
phrasing against [test_parity.py:184-194]. **E2 (test surface) — addressed:** §D-G names
`TestSecurityAgentBoundaries` (both-sources sweep) and the Trade-offs line + r2 note call out the
non-pusher-over-claim row, the sorted-last dispatch entry, `agents: []`, and template↔static parity as the
plan's must_haves. Security pass holds — the untrusted-input boundary is correctly load-bearing for a
`{read, local-write}` + `carter-github/*` agent, and §D-E keeps the new-server credential path gated
(no-auth feed preferred). Approve.

## Round 1 — 2026-06-30 — reviewed revision 1 — verdict: request-changes

*Implementation-feasibility + test-surface + security pass (ADR-0004 §D5). Advisory, not a vote.*

**Bottom line.** Implementable and low-risk for the agent half — it's additions to `AGENT_ALLOWLIST`, `AGENT_MCP_SCOPE`, `MODEL_TIERS`, the roster, and two new agent files, all paths the existing parity machinery already exercises. The `tools:` derivation (ADR-0011) means I do **not** hand-write `tools:` — good, the RFC says so. One blocker on the test spec, one on a parity trap the RFC underspecifies, plus a security note that strengthens §D-G.

### Blockers

**E1 — §D-G names the test class but not the assertions precisely enough to be a spec.** The maestro injection guard ([test_parity.py:169-193]) works because it greps **fixed phrases** (`"data to analyze"`, `"never instructions to act on"`). §D-G item 2 reuses that pattern — fine. But item 1 (authorization posture) says "asserts the presence of `"authorized"` **and** a refusal clause covering destructive/DoS/mass-targeting/supply-chain/evasion" — that's five concepts behind one hand-wave. **Pick the exact strings now** (OQ-G1), in the RFC, the way RFC-0005 made the lint a hard spec, or the plan will invent them and they'll drift from the agent body. My lean: assert a small fixed set — `"authorized"`, `"refuse"` (or `"refus"`), and at least `"destructive"` + `"mass"` — over **both** sources, mirroring the maestro test's both-sources sweep. Brittle-but-precise beats a keyword soup the agent body can satisfy accidentally.

**E2 — the parity/per-agent test surface is wider than "extend the per-agent assertions."** Adding an 8th agent ripples through every test that enumerates the roster: `test_parity.py` (the rendered↔static body-parity test, the per-agent `tools:`/`permission` derivation tests, the non-pusher-over-claim test at [test_parity.py:304-320] — `carter-security` is a non-pusher, so it **must not** claim "Full access"), `test_config.py` (allowlist/model-tier/MCP-scope assertions), `test_scaffold.py` (incl. `TestAgentSuffix` — the emitted `agents:`/`permission.task` and the filename use `carter-security-local`; the dispatch list is **sorted**, so `carter-security` lands last). The RFC's Trade-offs line lists these files but as a flat list; the **must_haves for the plan** should call out specifically: (a) `carter-security` appears in the sorted dispatch allowlist on the primary, (b) it carries `agents: []`, (c) it does **not** claim "Full access", (d) template↔static parity holds. Budget for re-baselining, not patching.

### Security pass

- **§D-G is the right instinct and §D-A.1 makes it load-bearing the same way ADR-0011 did for the maestro.** A `{read, local-write}`-with-`carter-github/*` agent that *reads attacker-controlled text* (logs, payloads) is exactly the injection surface the maestro test guards — so the untrusted-input assertion isn't optional polish, it's the same non-regression. ✓ Strongly endorse making it test-asserted.
- **§D-E credential path — flag, don't smuggle.** ✓ The RFC correctly refuses to fix the server/credential here (OQ-E1) and inherits ADR-0008's read-only + digest-pin + surgical-`--tools`. The one thing to assert in the D-E.2 ADR: a CVE/SCA feed that needs **no** auth (public OSV/CVE) is a materially smaller security surface than a hosted SCA with a token — the RFC says "strongly preferred," the ADR should make it the default and force a justification to deviate.
- No new secret surface in the *agent* half — `model:`/`agents:`/allowlist carry none. ✓

**Verdict rationale.** E1 and E2 are both "make the test spec executable, not narrative" — the recurring Carter discipline. Neither needs a redesign; E1 is choosing strings, E2 is enumerating must_haves. The security posture is right. Re-review on r2.
