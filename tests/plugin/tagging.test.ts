import { test } from "node:test"
import assert from "node:assert/strict"
import { MARK_PREFIX, countState, detect, isPolluted, mark, newNonce, tagShell } from "../../carter/plugin/core.ts"
import { expand, isoDoc, vectors } from "./helpers.ts"

test("the marker format is the App C.2 one", () => {
  assert.equal(MARK_PREFIX, vectors.marker.prefix)
})

test("marker vectors: detect strips only our own nonce at the very start", () => {
  const { nonce, cases } = vectors.marker
  for (const c of cases) {
    assert.deepEqual(detect(nonce, c.command), { marked: c.marked, scope: c.scope, command: c.stripped }, c.name)
  }
})

test("marker vectors: mark prefixes the command and carries the scope bit", () => {
  for (const c of vectors.marker.mark) assert.equal(mark(vectors.marker.nonce, c.command, c.scope), c.marked)
})

test("the nonce is per instance, alphanumeric and never equal across draws", () => {
  let n = 0
  const a = newNonce(() => ((n += 0.137) % 1))
  const b = newNonce(() => ((n += 0.311) % 1))
  assert.match(a, /^[0-9a-z]{12}$/)
  assert.notEqual(a, b)
})

test("a forged marker with another nonce is not a marker", () => {
  assert.equal(detect("abc123", ": carter_agent_zzz999_1\ngit status").marked, false)
})

test("pollution vectors (shared with carter.identity.pollution)", () => {
  for (const c of vectors.pollution) {
    assert.equal(isPolluted(c.env, isoDoc.pollution), c.polluted, c.name)
  }
})

test("GIT_CONFIG_COUNT vectors (shared with carter.identity.pollution)", () => {
  for (const c of vectors.count) {
    const got = countState(expand(c.env))
    assert.deepEqual([got.state, got.n, got.reason], [c.state, c.n, c.reason], c.name)
  }
})

const P = isoDoc.pollution

test("tagging: inherited tags are deleted first, a marked shell gets the agent tag", () => {
  const env = { CARTER_HUMAN_SHELL: "1", CARTER_AGENT_SHELL: "0", PATH: "/usr/bin" }
  const r = tagShell(env, P, true, "passed", 0)
  assert.equal(r.tag, "agent")
  assert.deepEqual(env, { CARTER_AGENT_SHELL: "1", PATH: "/usr/bin" })
})

test("tagging: an unmarked shell gets no tag while unproven or failed", () => {
  for (const state of ["unproven", "failed"] as const) {
    const env = { CARTER_AGENT_SHELL: "1" }
    assert.equal(tagShell(env, P, false, state, 0).tag, "none")
    assert.deepEqual(env, {})
  }
})

test("tagging: in passed, an unmarked shell is human only if nothing is polluted and no timer is pending", () => {
  const clean: Record<string, string> = { PATH: "/usr/bin" }
  assert.equal(tagShell(clean, P, false, "passed", 0).tag, "human")
  assert.equal(clean.CARTER_HUMAN_SHELL, "1")
  const pendingEnv: Record<string, string> = {}
  assert.equal(tagShell(pendingEnv, P, false, "passed", 1).tag, "none") // an agent call may be in flight
  assert.deepEqual(pendingEnv, {})
})

test("tagging: a polluted server environment gets no human tag and nothing is stripped but our own tags", () => {
  const env: Record<string, string> = { AGENT: "1", OPENCODE_SESSION_ID: "ses_x", CARTER_AGENT_SHELL: "1" }
  const r = tagShell(env, P, false, "passed", 0)
  assert.deepEqual([r.tag, r.polluted], ["none", true])
  assert.deepEqual(env, { AGENT: "1", OPENCODE_SESSION_ID: "ses_x" }) // pollution judged before deleting CARTER_*
})

test("tagging: without isolation data the shell is treated as polluted (no human tag)", () => {
  assert.equal(tagShell({}, undefined, false, "passed", 0).tag, "none")
})
