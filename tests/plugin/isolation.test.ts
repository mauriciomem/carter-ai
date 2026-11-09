import { test } from "node:test"
import assert from "node:assert/strict"
import { chmodSync, mkdirSync, symlinkSync, writeFileSync, rmSync } from "node:fs"
import * as fs from "node:fs"
import { join } from "node:path"
import {
  CarterError,
  MESSAGES,
  applyIsolation,
  createCarter,
  loadIsolation,
  readPat,
  validateIso,
  type Iso,
} from "../../carter/plugin/core.ts"
import { canonical, expand, isoDoc, rig, sha256, vectors, writePat } from "./helpers.ts"

const PAT = "github_pat_TEST-SENTINEL"
const clone = (): Iso => JSON.parse(JSON.stringify(isoDoc))

test("the golden document hashes like the Python renderer's canonical bytes", () => {
  assert.equal(sha256(canonical(isoDoc)), vectors.isolation.sha256)
})

// ---- refuse, never skip --------------------------------------------------------------------

function refused(fn: () => unknown) {
  assert.throws(fn, (err: unknown) => {
    assert.ok(err instanceof CarterError)
    assert.equal(err.code, "E-ISOLATION-MISSING")
    assert.ok(err.message.includes(MESSAGES["E-ISOLATION-MISSING"]))
    return true
  })
}

test("loadIsolation accepts the exact file and returns the document", () => {
  const r = rig()
  const iso = loadIsolation(fs, join(r.home, ".carter", "isolation.json"), r.deps.isolationSha256)
  assert.deepEqual(iso, r.iso)
  r.cleanup()
})

test("a missing file, an unreadable path and a directory in its place are refused", () => {
  const r = rig()
  const path = join(r.home, ".carter", "isolation.json")
  refused(() => loadIsolation(fs, join(r.home, "nope.json"), r.deps.isolationSha256))
  rmSync(path)
  mkdirSync(path)
  refused(() => loadIsolation(fs, path, r.deps.isolationSha256))
  r.cleanup()
})

test("invalid JSON and any byte change (hash mismatch) are refused", () => {
  const r = rig()
  const path = join(r.home, ".carter", "isolation.json")
  const sha = r.deps.isolationSha256
  writeFileSync(path, canonical(r.iso).toString().replace("never", "nevar"))
  refused(() => loadIsolation(fs, path, sha))
  writeFileSync(path, "not json\n")
  refused(() => loadIsolation(fs, path, sha256("not json\n")))
  r.cleanup()
})

test("a placeholder that was never rendered refuses everything", () => {
  const r = rig()
  const path = join(r.home, ".carter", "isolation.json")
  for (const baked of ["__CARTER_ISOLATION_SHA256__", "", "ABCDEF".repeat(11).slice(0, 64), "0".repeat(63)]) {
    refused(() => loadIsolation(fs, path, baked))
  }
  r.cleanup()
})

test("schema mismatches with a correct hash are refused: required keys, unknown keys, types", () => {
  const edits: [string, (d: any) => void][] = [
    ["missing top key", (d) => delete d.env],
    ["unknown top key", (d) => (d.extra = 1)],
    ["schema version (an old file)", (d) => (d.schema_version = 1)],
    ["schema version (a future file)", (d) => (d.schema_version = 3)],
    ["b_enabled type", (d) => (d.plugin.b_enabled = "yes")],
    ["b_caller empty", (d) => (d.plugin.b_caller = "")],
    ["broker_args type", (d) => (d.plugin.broker_args = "-I")],
    ["relative b_git", (d) => (d.plugin.b_git = "git")],
    ["relative b_gh", (d) => (d.plugin.b_gh = "gh")],
    ["enabled without a git", (d) => ((d.plugin.b_enabled = true), (d.plugin.b_git = ""))],
    ["missing b key", (d) => delete d.plugin.b_enabled],
    ["env keys", (d) => delete d.env.delete],
    ["env.set value type", (d) => (d.env.set.X = 1)],
    ["git_config pair", (d) => (d.git_config = [["only"]])],
    ["markers keys", (d) => delete d.pollution.markers.env],
    ["marker triple", (d) => d.pollution.markers.env.push(["a", "b"])],
    ["unknown plugin key", (d) => (d.plugin.unknown = 1)],
    ["missing plugin key", (d) => delete d.plugin.status_dir],
    ["relative python_path", (d) => (d.plugin.python_path = "python")],
    ["relative pat_file", (d) => (d.plugin.pat_file = "rel")],
    ["zero timeout", (d) => (d.plugin.gate_timeout_ms = 0)],
    ["string timeout", (d) => (d.plugin.self_test_ms = "2000")],
    ["gate_args type", (d) => (d.plugin.gate_args = "-I")],
  ]
  for (const [name, edit] of edits) {
    const r = rig()
    const doc: any = clone()
    edit(doc)
    const bytes = canonical(doc)
    writeFileSync(join(r.home, ".carter", "isolation.json"), bytes)
    assert.throws(() => loadIsolation(fs, join(r.home, ".carter", "isolation.json"), sha256(bytes)), CarterError, name)
    r.cleanup()
  }
  assert.doesNotThrow(() => validateIso(clone()))
})

test("an agent shell is never created without a valid isolation file (create.before throws)", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  rmSync(join(r.home, ".carter", "isolation.json"))
  const ev = { command: "echo hi", cwd: "/w", env: { SSH_AUTH_SOCK: "/s" } as Record<string, string | undefined> }
  await carter.executeBefore({ tool: "shell", sessionID: "s", input: { command: "echo" } }).catch(() => {})
  await assert.rejects(carter.createBefore({ ...ev, command: `: carter_agent_${carter.nonce()}_1\necho hi` }), /E-ISOLATION-MISSING/)
  assert.equal(ev.env.SSH_AUTH_SOCK, "/s") // untouched
  // a human shell is not blocked by a broken file
  await assert.doesNotReject(carter.createBefore({ command: "echo hi", cwd: "/w", env: {} }))
  carter.dispose()
  r.cleanup()
})

// ---- apply: the Python oracle's golden cases -------------------------------------------------

test("applyIsolation equals the Python reference for every golden case", () => {
  for (const c of vectors.isolation.apply) {
    const got = applyIsolation(c.env, isoDoc, c.pat ?? undefined, c.block_commits)
    assert.deepEqual(got.env, c.expect_env, c.name)
    assert.deepEqual(got.flags, c.expect_flags, c.name)
  }
})

test("the input environment is not modified", () => {
  const env = { SSH_AUTH_SOCK: "/s", GIT_CONFIG_COUNT: "abc" }
  const before = { ...env }
  applyIsolation(env, isoDoc, undefined, false)
  assert.deepEqual(env, before)
})

test("an inherited GIT_CONFIG_PARAMETERS is deleted and our entries come last", () => {
  const out = applyIsolation({ GIT_CONFIG_PARAMETERS: "'a.b=c'", GIT_CONFIG_COUNT: "1", GIT_CONFIG_KEY_0: "u.n", GIT_CONFIG_VALUE_0: "x" }, isoDoc, PAT, false).env
  assert.equal(out.GIT_CONFIG_PARAMETERS, undefined)
  assert.equal(out.GIT_CONFIG_KEY_0, "u.n")
  assert.equal(out.GIT_CONFIG_KEY_1, "credential.helper")
  assert.equal(out.GIT_CONFIG_COUNT, String(1 + isoDoc.git_config.length))
})

test("count edge cases from the vector table keep the count consistent", () => {
  for (const c of vectors.count) {
    const out = applyIsolation(expand(c.env), isoDoc, PAT, false)
    const keep = c.state === "ok" ? c.n : 0
    assert.equal(out.env.GIT_CONFIG_COUNT, String(keep + isoDoc.git_config.length + (c.state === "ok" ? 0 : isoDoc.blocking_git_config.length)), c.name)
    assert.equal(out.flags.includes("count-malformed"), c.state === "polluted", c.name)
  }
})

// ---- the GitHub read token ---------------------------------------------------------------------

test("the token is read per shell from a 0600 regular file we own", () => {
  const r = rig()
  writePat(r.home, PAT)
  assert.equal(readPat(fs, r.iso, r.deps.euid), PAT)
  writePat(r.home, PAT + "-rotated") // read at each shell creation, never cached
  assert.equal(readPat(fs, r.iso, r.deps.euid), PAT + "-rotated")
  r.cleanup()
})

test("the token is refused (dummy used) unless every file check passes", () => {
  const r = rig()
  assert.equal(readPat(fs, r.iso, r.deps.euid), undefined, "missing file")
  const file = writePat(r.home, PAT, 0o644)
  assert.equal(readPat(fs, r.iso, r.deps.euid), undefined, "mode 0644")
  chmodSync(file, 0o600)
  assert.equal(readPat(fs, r.iso, 0xfffff), undefined, "owned by someone else")
  writePat(r.home, ["ghp", "notafinegrainedtoken"].join("_")) // built at run time: no token-shaped literal
  assert.equal(readPat(fs, r.iso, r.deps.euid), undefined, "wrong prefix")
  rmSync(file)
  const real = join(r.home, "elsewhere.token")
  writeFileSync(real, PAT + "\n", { mode: 0o600 })
  symlinkSync(real, file)
  assert.equal(readPat(fs, r.iso, r.deps.euid), undefined, "symlink")
  rmSync(file)
  mkdirSync(file)
  assert.equal(readPat(fs, r.iso, r.deps.euid), undefined, "directory")
  const none = clone()
  none.plugin.pat_file = ""
  assert.equal(readPat(fs, none, r.deps.euid), undefined, "no pat_file configured")
  r.cleanup()
})

test("with a good token GH_TOKEN is the token; otherwise the dummy and a status flag; never in a config value", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const call = { tool: "shell", sessionID: "s", input: { command: "true" } }
  await carter.executeBefore(call)
  const noToken = { command: call.input.command, cwd: "/w", env: {} as Record<string, string | undefined> }
  await carter.createBefore(noToken)
  assert.equal(noToken.env.GH_TOKEN, r.iso.plugin.gh_token_dummy)
  assert.ok(carter.flags().includes("pat-dummy"))
  writePat(r.home, PAT)
  const withToken = { command: "echo", cwd: "/w", env: {} as Record<string, string | undefined> }
  await carter.executeBefore({ ...call, input: { command: "echo" } })
  withToken.command = `: carter_agent_${carter.nonce()}_1\necho`
  await carter.createBefore(withToken)
  assert.equal(withToken.env.GH_TOKEN, PAT)
  assert.ok(!carter.flags().includes("pat-dummy"))
  const leaks = Object.entries(withToken.env).filter(([k, v]) => k !== "GH_TOKEN" && (v ?? "").includes(PAT))
  assert.deepEqual(leaks, [])
  const everything = [...r.logs, JSON.stringify(carter.flags())].join("\n")
  assert.ok(!everything.includes(PAT), "the token is never logged")
  carter.dispose()
  r.cleanup()
})
