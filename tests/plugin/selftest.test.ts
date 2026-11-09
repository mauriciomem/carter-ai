import { test } from "node:test"
import assert from "node:assert/strict"
import { readFileSync, statSync, mkdirSync, writeFileSync } from "node:fs"
import { join } from "node:path"
import { createCarter, createSelfTest, type Env, type State } from "../../carter/plugin/core.ts"
import { fakeClock, rig, vectors } from "./helpers.ts"

const N = 2000

function machine() {
  const clock = fakeClock()
  const changes: [State, string | null][] = []
  const st = createSelfTest(clock, N, (state, reason) => changes.push([state, reason]))
  return { clock, changes, st }
}

test("starts unproven and the first marked round trip makes it passed", () => {
  const { st, changes } = machine()
  assert.equal(st.state(), "unproven")
  st.arm()
  st.roundTrip()
  assert.equal(st.state(), "passed")
  assert.deepEqual(changes, [["passed", null]])
})

test("a missing round trip fails at exactly N ms, not before", () => {
  const { st, clock, changes } = machine()
  st.arm()
  clock.advance(N - 1)
  assert.equal(st.state(), "unproven")
  clock.advance(1)
  assert.equal(st.state(), "failed")
  assert.equal(st.reason(), "timeout")
  assert.deepEqual(changes, [["failed", "timeout"]])
})

test("failed is terminal: a late marked round trip does not resurrect it", () => {
  const { st, clock } = machine()
  st.arm()
  clock.advance(N)
  st.roundTrip()
  assert.equal(st.state(), "failed")
  st.arm()
  st.roundTrip()
  assert.equal(st.state(), "failed")
})

test("timers live in every state: a miss after passed also fails", () => {
  const { st, clock } = machine()
  st.arm()
  st.roundTrip()
  st.arm()
  clock.advance(N)
  assert.equal(st.state(), "failed")
})

test("two concurrent calls match first-in first-out and never race", () => {
  const { st, clock } = machine()
  st.arm()
  st.arm()
  assert.equal(st.pending(), 2)
  st.roundTrip()
  st.roundTrip()
  assert.equal(st.pending(), 0)
  clock.advance(10 * N)
  assert.equal(st.state(), "passed")
  assert.equal(clock.timers(), 0)
})

test("one of two calls missing still fails when its own timer expires", () => {
  const { st, clock } = machine()
  st.arm()
  clock.advance(100)
  st.arm()
  st.roundTrip() // the first call arrives; the second never does
  assert.equal(st.pending(), 1)
  clock.advance(N)
  assert.equal(st.state(), "failed")
})

test("dispose clears the timers and nothing fires afterwards", () => {
  const { st, clock, changes } = machine()
  st.arm()
  st.arm()
  st.dispose()
  assert.equal(clock.timers(), 0)
  clock.advance(10 * N)
  assert.deepEqual(changes, [])
  st.arm()
  assert.equal(clock.timers(), 0)
})

// ---- the assembled plugin: marker, tags and the status record ----------------------------

const event = (cmd: string, env: Env = {}) => ({ command: cmd, cwd: "/work", env })
const shell = (cmd: string) => ({ tool: "shell", sessionID: "ses_1", input: { command: cmd } })

test("a shell tool call is marked and its create.before round trip passes the self-test", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const call = shell("echo hi")
  await carter.executeBefore(call)
  assert.match(call.input.command, new RegExp(`^: carter_agent_${carter.nonce()}_1\\necho hi$`))
  assert.equal(carter.pending(), 1)
  const ev = event(call.input.command, { SSH_AUTH_SOCK: "/s", PATH: "/usr/bin" })
  await carter.createBefore(ev)
  assert.equal(ev.command, "echo hi")
  assert.equal(carter.state(), "passed")
  assert.equal(ev.env.CARTER_AGENT_SHELL, "1")
  assert.equal(ev.env.SSH_AUTH_SOCK, undefined)
  r.clock.advance(10 * N)
  assert.equal(carter.state(), "passed")
  carter.dispose()
  r.cleanup()
})

test("the status record is names and states only, atomic, 0600 in a 0700 directory", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const file = join(r.iso.plugin.status_dir, "4242.json")
  const first = JSON.parse(readFileSync(file, "utf8"))
  assert.deepEqual(Object.keys(first), vectors.status.keys)
  assert.equal(first.state, "unproven")
  assert.equal(first.failed_reason, null)
  assert.equal(first.opencode_version, "2.1.4")
  assert.equal(first.plugin_version, "0.0.0-test")
  assert.equal(first.pid, 4242)
  assert.equal(first.isolation_sha256, r.deps.isolationSha256)
  assert.notEqual(first.instance, carter.nonce())
  assert.equal(first.boot, 1_700_000_000_000 - 1000)
  assert.equal(statSync(file).mode & 0o777, 0o600)
  assert.equal(statSync(r.iso.plugin.status_dir).mode & 0o777, 0o700)
  const call = shell("true")
  await carter.executeBefore(call)
  await carter.createBefore(event(call.input.command))
  assert.equal(JSON.parse(readFileSync(file, "utf8")).state, "passed")
  assert.ok(!JSON.stringify(first).includes("SSH_AUTH_SOCK"))
  carter.dispose()
  r.cleanup()
})

test("a timeout writes failed with its reason, and every shell then becomes an agent shell", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const call = shell("true")
  await carter.executeBefore(call)
  r.clock.advance(N)
  assert.equal(carter.state(), "failed")
  const record = JSON.parse(readFileSync(join(r.iso.plugin.status_dir, "4242.json"), "utf8"))
  assert.deepEqual([record.state, record.failed_reason], ["failed", "timeout"])
  assert.match(r.logs.join("\n"), /own check failed on OpenCode 2\.1\.4/)
  const bang = event("echo from-bang", { SSH_AUTH_SOCK: "/s" }) // unmarked: would be a human shell
  await carter.createBefore(bang)
  assert.equal(bang.env.CARTER_AGENT_SHELL, "1")
  assert.equal(bang.env.CARTER_HUMAN_SHELL, undefined)
  assert.equal(bang.env.SSH_AUTH_SOCK, undefined) // isolated
  await carter.createBefore(event(call.input.command)) // a late marked create.before
  assert.equal(carter.state(), "failed")
  carter.dispose()
  r.cleanup()
})

test("while unproven an unmarked shell gets no tag; after a pass it is human; during a pending call it is not", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const early = event("echo early", { PATH: "/usr/bin" })
  await carter.createBefore(early)
  assert.deepEqual([early.env.CARTER_HUMAN_SHELL, early.env.CARTER_AGENT_SHELL], [undefined, undefined])
  assert.equal(carter.state(), "unproven")
  const call = shell("true")
  await carter.executeBefore(call)
  const during = event("echo during", {})
  await carter.createBefore(during) // a timer is pending: could be an agent shell whose marker was lost
  assert.equal(during.env.CARTER_HUMAN_SHELL, undefined)
  await carter.createBefore(event(call.input.command))
  const late = event("echo late", { PATH: "/usr/bin" })
  await carter.createBefore(late)
  assert.equal(late.env.CARTER_HUMAN_SHELL, "1")
  carter.dispose()
  r.cleanup()
})

test("a polluted server environment: no human tag, one warning, a status flag, nothing stripped", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const call = shell("true")
  await carter.executeBefore(call)
  await carter.createBefore(event(call.input.command))
  const polluted = { AGENT: "1", OPENCODE_SESSION_ID: "ses_x" }
  const first = event("echo", { ...polluted })
  await carter.createBefore(first)
  await carter.createBefore(event("echo", { ...polluted }))
  assert.equal(first.env.CARTER_HUMAN_SHELL, undefined)
  assert.equal(first.env.AGENT, "1")
  assert.equal(r.logs.filter((l) => l.includes("restart OpenCode from a clean terminal")).length, 1)
  assert.deepEqual(carter.flags().includes("polluted"), true)
  carter.dispose()
  r.cleanup()
})

test("a status write failure never blocks a shell", async () => {
  const r = rig()
  mkdirSync(join(r.home, ".carter", "run"), { recursive: true })
  writeFileSync(r.iso.plugin.status_dir, "a file where the directory should be")
  const carter = createCarter(r.deps)
  const call = shell("true")
  await carter.executeBefore(call)
  const ev = event(call.input.command)
  await carter.createBefore(ev)
  assert.equal(ev.env.CARTER_AGENT_SHELL, "1")
  carter.dispose()
  r.cleanup()
})

test("dispose (hot reload or delete) stops the timers and the writes", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const file = join(r.iso.plugin.status_dir, "4242.json")
  await carter.executeBefore(shell("true"))
  carter.dispose()
  assert.equal(r.clock.timers(), 0)
  const before = readFileSync(file, "utf8")
  r.clock.advance(10 * N)
  assert.equal(readFileSync(file, "utf8"), before) // no failed written by a dead instance
  r.cleanup()
})

test("the self-test timeout comes from isolation.json", async () => {
  const r = rig({}, (iso) => {
    iso.plugin.self_test_ms = 500
  })
  const carter = createCarter(r.deps)
  await carter.executeBefore(shell("true"))
  r.clock.advance(499)
  assert.equal(carter.state(), "unproven")
  r.clock.advance(1)
  assert.equal(carter.state(), "failed")
  carter.dispose()
  r.cleanup()
})

test("a rejected call (gate deny, gate failure, broken isolation) never arms the timer: no false failed", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  r.respond(() => ({ kind: "exit", code: 1, stdout: JSON.stringify({ decision: "deny", rule: "push-verbs", message: "no" }) }))
  await assert.rejects(carter.executeBefore(shell("git push")), /no/)
  r.respond(() => ({ kind: "timeout" }))
  await assert.rejects(carter.executeBefore(shell("ls")), /E-GATE-FAIL/)
  assert.equal(carter.pending(), 0)
  r.clock.advance(10 * N)
  assert.equal(carter.state(), "unproven")
  carter.dispose()
  r.cleanup()
})

test("the marker is added only after the gate allowed the call, and the timer is armed last", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const call = shell("git status")
  let seen = ""
  r.respond((_argv, input) => {
    seen = input
    assert.equal(carter.pending(), 0) // not armed while the gate runs
    return { kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }
  })
  await carter.executeBefore(call)
  assert.equal(seen, "git status", "the gate sees the plain command, not the marker")
  assert.equal(carter.pending(), 1)
  carter.dispose()
  r.cleanup()
})

test("a failed self-test tells the adapter once, so the broker tools can drop out", async () => {
  let told = 0
  const r = rig({ onFailed: () => void told++ })
  const carter = createCarter(r.deps)
  assert.equal(carter.brokerOn(), false) // the default golden isolation.json has b_enabled false
  await carter.executeBefore(shell("echo hi"))
  assert.equal(told, 0)
  r.clock.advance(N)
  assert.equal(carter.state(), "failed")
  assert.equal(told, 1)
  r.clock.advance(10 * N)
  assert.equal(told, 1)
  carter.dispose()
  r.cleanup()
})

test("brokerOn needs b_enabled in the validated file and a self-test that is not failed", async () => {
  const r = rig({}, (iso) => {
    iso.plugin.b_enabled = true
    iso.plugin.b_git = "/usr/bin/git"
  })
  const carter = createCarter(r.deps)
  assert.equal(carter.brokerOn(), true)
  await carter.executeBefore(shell("echo hi"))
  r.clock.advance(N)
  assert.equal(carter.brokerOn(), false)
  carter.dispose()
  r.cleanup()
})
