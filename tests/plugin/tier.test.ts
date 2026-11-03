import { test } from "node:test"
import assert from "node:assert/strict"
import { utimesSync, writeFileSync, readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { createCarter, tierDecision, MESSAGES, type RunResult } from "../../carter/plugin/core.ts"
import { isoDoc, rig, vectors } from "./helpers.ts"

function outcome(o: { kind: string; stdout?: string; code?: number }): RunResult {
  if (o.kind === "timeout") return { kind: "timeout" }
  if (o.kind === "exit") return { kind: "exit", code: o.code ?? 1, stdout: o.stdout ?? "" }
  return { kind: "exit", code: 0, stdout: o.stdout ?? "" }
}

test("tier vectors: block on effective T2, any reason, a crash, a timeout or invalid output", () => {
  for (const c of vectors.tier.cases) {
    assert.deepEqual(tierDecision(outcome(c.outcome)), { block: c.block, flags: c.flags }, c.name)
  }
})

const N = isoDoc.git_config.length
const tierJson = (effective: string, reason: string | null, tier = effective) =>
  JSON.stringify({ schema_version: 1, tier, cap: null, effective, require_tier: null, reason })

async function agentShell(r: ReturnType<typeof rig>, carter: ReturnType<typeof createCarter>, cwd = "/work") {
  const call = { tool: "shell", sessionID: "s", input: { command: "git commit -m x" } }
  await carter.executeBefore(call)
  const ev = { command: call.input.command, cwd, env: {} as Record<string, string | undefined> }
  await carter.createBefore(ev)
  return ev
}
const entryCalls = (r: ReturnType<typeof rig>) => r.calls.filter((c) => c.argv.includes("carter.identity.env"))

test("effective t0 or t1 appends nothing beyond the isolation entries", async () => {
  for (const eff of ["t0", "t1"]) {
    const r = rig()
    r.respond((argv) => (argv.includes("carter.identity.env") ? { kind: "exit", code: 0, stdout: tierJson(eff, null) } : { kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }))
    const ev = await agentShell(r, createCarter(r.deps))
    assert.equal(ev.env.GIT_CONFIG_COUNT, String(N), eff)
    r.cleanup()
  }
})

test("effective T2, a crash, a timeout or invalid JSON append the commit-blocking entries and warn once", async () => {
  const cases: [string, RunResult][] = [
    ["t2", { kind: "exit", code: 0, stdout: tierJson("t2", "signing-not-built") }],
    ["crash", { kind: "exit", code: 1, stdout: "" }],
    ["timeout", { kind: "timeout" }],
    ["invalid", { kind: "exit", code: 0, stdout: "nope" }],
  ]
  for (const [name, result] of cases) {
    const r = rig()
    r.respond((argv) => (argv.includes("carter.identity.env") ? result : { kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }))
    const carter = createCarter(r.deps)
    const ev = await agentShell(r, carter)
    assert.equal(ev.env.GIT_CONFIG_COUNT, String(N + 2), name)
    assert.equal(ev.env[`GIT_CONFIG_KEY_${N}`], isoDoc.blocking_git_config[0][0])
    assert.equal(ev.env[`GIT_CONFIG_VALUE_${N}`], isoDoc.blocking_git_config[0][1])
    assert.ok(carter.flags().includes("sign-unavailable"), name)
    await agentShell(r, carter, "/other") // a second blocked shell must not warn again
    assert.equal(r.logs.filter((l) => l.includes("agent commits are blocked, not downgraded")).length, 1, name)
    carter.dispose()
    r.cleanup()
  }
})

test("a config error sets its own flag and the registry wording is used", async () => {
  const r = rig()
  r.respond((argv) => (argv.includes("carter.identity.env") ? { kind: "exit", code: 0, stdout: tierJson("t0", "config-error") } : { kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }))
  const carter = createCarter(r.deps)
  const ev = await agentShell(r, carter)
  assert.equal(ev.env.GIT_CONFIG_COUNT, String(N + 2))
  assert.ok(carter.flags().includes("config-error") && !carter.flags().includes("sign-unavailable"))
  assert.match(r.logs.join("\n"), /config-error/)
  assert.ok(MESSAGES["E-CONFIG"].includes("agent commits are disabled until fixed"))
  carter.dispose()
  r.cleanup()
})

test("the entry is called by absolute python_path with env_args, in the shell's cwd, with the env timeout", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  await agentShell(r, carter, "/work/pkg")
  const [call] = entryCalls(r)
  assert.deepEqual(call.argv, [r.iso.plugin.python_path, ...r.iso.plugin.env_args])
  assert.equal(call.opts.cwd, "/work/pkg")
  assert.equal(call.opts.timeoutMs, r.iso.plugin.env_timeout_ms)
  assert.equal(call.opts.input, "")
  carter.dispose()
  r.cleanup()
})

test("the result is cached in memory by cwd and the config mtimes, and never written to disk", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  await agentShell(r, carter, "/work")
  await agentShell(r, carter, "/work")
  assert.equal(entryCalls(r).length, 1, "same cwd and mtimes: cached")
  await agentShell(r, carter, "/elsewhere")
  assert.equal(entryCalls(r).length, 2, "another workspace: asked again")
  const config = join(r.home, ".carter", "config.toml")
  writeFileSync(config, "schema = 2\n")
  await agentShell(r, carter, "/work")
  assert.equal(entryCalls(r).length, 3, "config.toml appeared: asked again")
  utimesSync(config, new Date(), new Date(Date.now() + 5000))
  await agentShell(r, carter, "/work")
  assert.equal(entryCalls(r).length, 4, "config.toml mtime changed: asked again")
  writeFileSync(join(r.home, ".carter", "gitconfig"), "[carter]\n")
  await agentShell(r, carter, "/work")
  assert.equal(entryCalls(r).length, 5, "the carter gitconfig changed: asked again")
  const disk = readdirSync(join(r.home, ".carter")).sort()
  assert.deepEqual(disk, ["config.toml", "gitconfig", "isolation.json", "run"])
  assert.ok(!readFileSync(join(r.home, ".carter", "isolation.json"), "utf8").includes("tier_cache"))
  carter.dispose()
  r.cleanup()
})

test("a human shell never calls the identity entry", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  await carter.createBefore({ command: "echo", cwd: "/w", env: {} })
  assert.equal(r.calls.length, 0)
  carter.dispose()
  r.cleanup()
})
