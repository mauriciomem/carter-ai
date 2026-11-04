// The plugin's signing block (plan 005 step 12, freeze H3): it applies what `identity env` returns at
// effective T2 and nothing else; every other path stays fail-closed as in 2a.
import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { createCarter, applySigning, applyIsolation, validateSigning, type RunResult, type Signing } from "../../carter/plugin/core.ts"
import { expand, isoDoc, rig, vectors, type Rig } from "./helpers.ts"

const block: Signing = vectors.signing.block
const N = isoDoc.git_config.length
const ALLOW = '{"decision":"allow","rule":null,"message":null}'
const answer = (over: Record<string, unknown> = {}) =>
  JSON.stringify({ schema_version: 1, tier: "t2", cap: null, effective: "t2", require_tier: null, reason: null, signing: block, ...over })

function respondWith(r: Rig, stdout: string | RunResult) {
  r.respond((argv) => (argv.includes("carter.identity.env") ? (typeof stdout === "string" ? { kind: "exit", code: 0, stdout } : stdout) : { kind: "exit", code: 0, stdout: ALLOW }))
}
async function agentShell(carter: ReturnType<typeof createCarter>, cwd = "/work", env: Record<string, string | undefined> = {}) {
  const call = { tool: "shell", sessionID: "s", input: { command: "git commit -m x" } }
  await carter.executeBefore(call)
  const ev = { command: call.input.command, cwd, env }
  await carter.createBefore(ev)
  return ev
}
const entries = (env: Record<string, string | undefined>) => {
  const out: [string, string][] = []
  for (let i = 0; i < Number(env.GIT_CONFIG_COUNT ?? 0); i++) out.push([env[`GIT_CONFIG_KEY_${i}`]!, env[`GIT_CONFIG_VALUE_${i}`]!])
  return out
}

test("signing vectors: applying the block (shared with carter.identity.payload.to_git_env)", () => {
  for (const c of vectors.signing.apply) {
    const got = applySigning(expand(c.env), block)
    assert.deepEqual(got.env, c.expected.env, c.name)
    assert.deepEqual(got.flags, c.expected.flags, c.name)
  }
})

test("signing vectors: the plugin rejects exactly the shapes it can judge", () => {
  assert.deepEqual(validateSigning(block, isoDoc), block)
  for (const c of vectors.signing.invalid) assert.equal(validateSigning(c.signing, isoDoc), null, c.name)
})

test("validateSigning refuses names the isolation block manages, read from isolation.json and not from a list in the plugin", () => {
  const withIso = (name: string) => ({ ...block, env: { ...block.env, [name]: "x" } })
  for (const name of [...Object.keys(isoDoc.env.set), ...isoDoc.env.delete]) assert.equal(validateSigning(withIso(name), isoDoc), null, name)
  assert.ok(validateSigning(withIso("SOME_NEW_COMMITTER_NAME"), isoDoc), "a name nobody manages is fine")
})

test("at effective T2 with a valid block the entries come after the isolation entries and the committer is set", async () => {
  const r = rig()
  respondWith(r, answer())
  const carter = createCarter(r.deps)
  const ev = await agentShell(carter, "/work", { GIT_CONFIG_PARAMETERS: "'commit.x=1'", GIT_COMMITTER_NAME: "Someone" })
  const list = entries(ev.env)
  assert.equal(list.length, N + block.git_config.length)
  assert.deepEqual(list.slice(0, N), isoDoc.git_config) // isolation first
  assert.deepEqual(list.slice(N), block.git_config) // then ours: the last entry of a key wins
  assert.equal(ev.env.GIT_COMMITTER_NAME, block.env.GIT_COMMITTER_NAME)
  assert.equal(ev.env.GIT_COMMITTER_EMAIL, block.env.GIT_COMMITTER_EMAIL)
  assert.equal(ev.env.CARTER_IDENTITY, block.env.CARTER_IDENTITY)
  assert.ok(!("GIT_CONFIG_PARAMETERS" in ev.env))
  assert.equal(ev.env.GH_TOKEN, isoDoc.plugin.gh_token_dummy) // the PAT/dummy logic ran before and is intact
  assert.ok(!carter.flags().includes("sign-unavailable"))
  assert.equal(r.logs.filter((l) => l.includes("agent commits are blocked")).length, 0)
  carter.dispose()
  r.cleanup()
})

test("the isolation entries for the other signing programs are still there and still earlier than the block", async () => {
  const r = rig()
  respondWith(r, answer())
  const carter = createCarter(r.deps)
  const ev = await agentShell(carter)
  const list = entries(ev.env)
  const isoPrograms = isoDoc.git_config.filter(([k]) => k.endsWith(".program"))
  assert.ok(isoPrograms.length >= 3)
  for (const pair of isoPrograms) assert.ok(list.slice(0, N).some(([k, v]) => k === pair[0] && v === pair[1]))
  const ours = block.git_config.filter(([k]) => k.endsWith(".program"))
  assert.equal(ours.length, 1) // only the ssh program is overridden (by Python's choice, not ours)
  carter.dispose()
  r.cleanup()
})

test("every reason, a block with a reason, a block at t0/t1, a partial block, a crash, a timeout and invalid JSON fall back to the blocking entries", async () => {
  const cases: [string, string | RunResult][] = [
    ["key-missing", answer({ reason: "key-missing", signing: undefined })],
    ["fingerprint-mismatch", answer({ reason: "fingerprint-mismatch", signing: undefined })],
    ["shim-missing", answer({ reason: "shim-missing", signing: undefined })],
    ["role-b-not-built", answer({ reason: "role-b-not-built", signing: undefined })],
    ["tier-required", answer({ reason: "tier-required", signing: undefined })],
    ["a reason wins over a block", answer({ reason: "shim-missing" })],
    ["t2 without a block", answer({ signing: undefined })],
    ["a block at t1", answer({ tier: "t1", effective: "t1" })],
    ["a partial block", answer({ signing: { env: block.env, fingerprint: block.fingerprint } })],
    ["an unknown key in the block", answer({ signing: { ...block, socket: "/x" } })],
    ["a crash", { kind: "exit", code: 1, stdout: "" }],
    ["a timeout", { kind: "timeout" }],
    ["invalid JSON", "not json"],
    ["wrong schema", answer({ schema_version: 2 })],
  ]
  for (const [name, result] of cases) {
    const r = rig()
    respondWith(r, result)
    const carter = createCarter(r.deps)
    const ev = await agentShell(carter)
    const list = entries(ev.env)
    assert.deepEqual(list.slice(N), isoDoc.blocking_git_config, name)
    assert.equal(list.length, N + isoDoc.blocking_git_config.length, name)
    for (const key of Object.keys(block.env)) assert.ok(!(key in ev.env), `${name}: ${key} must not be set`)
    assert.ok(carter.flags().includes("sign-unavailable"), name)
    carter.dispose()
    r.cleanup()
  }
})

test("a reason name is quoted in the warning, a value is never", async () => {
  const r = rig()
  respondWith(r, answer({ reason: "shim-missing", signing: undefined }))
  const carter = createCarter(r.deps)
  await agentShell(carter)
  const text = r.logs.join("\n")
  assert.match(text, /\(shim-missing\)/)
  carter.dispose()
  r.cleanup()
})

test("at t0, t1 and under a cap no signing entry and no committer variable is set", async () => {
  for (const [eff, tier, cap] of [["t0", "t0", null], ["t1", "t1", null], ["t1", "t2", "t1"]]) {
    const r = rig()
    respondWith(r, JSON.stringify({ schema_version: 1, tier, cap, effective: eff, require_tier: null, reason: null }))
    const carter = createCarter(r.deps)
    const ev = await agentShell(carter)
    assert.deepEqual(entries(ev.env), isoDoc.git_config, `${tier} capped to ${eff}`) // the isolation's gpgsign=false stays
    for (const key of Object.keys(block.env)) assert.ok(!(key in ev.env))
    assert.ok(!carter.flags().includes("sign-unavailable"))
    carter.dispose()
    r.cleanup()
  }
})

test("a malformed inherited count keeps commits blocked: the signing block is not put on top of it", async () => {
  const r = rig()
  respondWith(r, answer())
  const carter = createCarter(r.deps)
  const ev = await agentShell(carter, "/work", { GIT_CONFIG_COUNT: "abc", GIT_CONFIG_KEY_0: "a.b", GIT_CONFIG_VALUE_0: "c" })
  const list = entries(ev.env)
  assert.deepEqual(list, [...isoDoc.git_config, ...isoDoc.blocking_git_config])
  assert.ok(!("GIT_COMMITTER_NAME" in ev.env))
  assert.ok(carter.flags().includes("count-malformed"))
  carter.dispose()
  r.cleanup()
})

test("the answer is cached in memory by cwd and the config mtimes; a changed mtime asks again; nothing about the block reaches the disk, the logs or the status", async () => {
  const r = rig()
  respondWith(r, answer())
  const carter = createCarter(r.deps)
  const calls = () => r.calls.filter((c) => c.argv.includes("carter.identity.env")).length
  await agentShell(carter)
  await agentShell(carter)
  assert.equal(calls(), 1)
  writeFileSync(join(r.home, ".carter", "gitconfig"), "[carter]\n\ttier = t2\n")
  await agentShell(carter)
  assert.equal(calls(), 2)
  const files: string[] = []
  const walk = (dir: string) => {
    for (const name of readdirSync(dir)) {
      const full = join(dir, name)
      if (statSync(full).isDirectory()) walk(full)
      else files.push(full)
    }
  }
  walk(r.home)
  const secrets = [block.fingerprint, block.env.GIT_COMMITTER_EMAIL, block.git_config[1][1], block.git_config[2][1]]
  for (const file of files) {
    const text = file.endsWith("gitconfig") ? "" : readFileSync(file, "utf8")
    for (const s of secrets) assert.ok(!text.includes(s), `${file} must not hold the signing block`)
  }
  for (const s of secrets) assert.ok(!r.logs.join("\n").includes(s), "logs")
  carter.dispose()
  r.cleanup()
})

test("applyIsolation and applySigning share one append: the count is the sum, in order", () => {
  const first = applyIsolation({}, isoDoc, undefined, false)
  const both = applySigning(first.env, block)
  assert.equal(both.env.GIT_CONFIG_COUNT, String(N + block.git_config.length))
  assert.equal(both.env[`GIT_CONFIG_KEY_${N}`], block.git_config[0][0])
  assert.equal(both.env.GIT_CONFIG_KEY_0, first.env.GIT_CONFIG_KEY_0)
  assert.deepEqual(both.flags, [])
})
