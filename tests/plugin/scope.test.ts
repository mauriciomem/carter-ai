// the plugin acts only for Carter agents (a global install) and in Carter workspaces. Anything
// else is left alone: no gate, no isolation and no tag, but the marker still goes on every shell call.
import { test } from "node:test"
import assert from "node:assert/strict"
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { SESSION_HOPS, WORKSPACE_LEVELS, createCarter, detect, inCarterWorkspace, isCarterAgent } from "../../carter/plugin/core.ts"
import * as fs from "node:fs"
import { rig } from "./helpers.ts"

const DENY = JSON.stringify({ decision: "deny", rule: "push-verbs", message: "no" })

function workspace(root: string, { agents = true, yaml = true } = {}) {
  mkdirSync(join(root, ".carter"), { recursive: true })
  if (yaml) writeFileSync(join(root, ".carter", "carter.yaml"), "version: '2'\n")
  if (agents) {
    mkdirSync(join(root, ".opencode", "agents"), { recursive: true })
    writeFileSync(join(root, ".opencode", "agents", "carter-engineer-local.md"), "---\n---\n")
  }
}
const shell = (command: string, over: Record<string, unknown> = {}) => ({ tool: "shell", sessionID: "ses_1", input: { command }, ...over })

function sessions(tree: Record<string, string | null | "unreadable">) {
  const looked: string[] = []
  const sessionParent = async (id: string) => {
    looked.push(id)
    const parent = tree[id]
    if (parent === "unreadable" || parent === undefined) throw new Error("session not found")
    return parent
  }
  return { sessionParent, looked }
}

test("only ids that start with carter- are Carter agents (workspace suffixes included)", () => {
  for (const id of ["carter-engineer", "carter-engineer-local", "carter-devops"]) assert.equal(isCarterAgent(id), true, id)
  for (const id of ["build", "plan", "general", "explore", "my-carter-x", "Carter-x", "", undefined, 5, null]) assert.equal(isCarterAgent(id), false, String(id))
})

test("a Carter agent's shell is gated, marked in scope and isolated", async () => {
  const r = rig()
  const carter = createCarter(r.deps)
  const e = shell("git push", { agent: "carter-engineer" })
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(e), /no/)
  r.respond(() => ({ kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }))
  const ok = shell("ls", { agent: "carter-engineer-local" })
  await carter.executeBefore(ok)
  assert.equal(detect(carter.nonce(), (ok.input as any).command).scope, true)
  const env: Record<string, string | undefined> = { SSH_AUTH_SOCK: "/s", PATH: "/usr/bin" }
  await carter.createBefore({ command: (ok.input as any).command, cwd: r.home, env })
  assert.equal(env.CARTER_AGENT_SHELL, "1")
  assert.equal(env.SSH_AUTH_SOCK, undefined)
  carter.dispose()
  r.cleanup()
})

test("another agent's root-session shell is untouched: no gate, no isolation, no tag, but marked out of scope", async () => {
  const tree = sessions({ ses_1: null })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY })) // would refuse everything
  const e = shell("git push origin main", { agent: "build" })
  await carter.executeBefore(e) // not refused
  const command = (e.input as any).command
  assert.equal(r.calls.length, 0, "the gate was never called")
  assert.deepEqual([detect(carter.nonce(), command).marked, detect(carter.nonce(), command).scope], [true, false])
  const env: Record<string, string | undefined> = { SSH_AUTH_SOCK: "/s", GITHUB_TOKEN: "t", CARTER_AGENT_SHELL: "1", CARTER_HUMAN_SHELL: "1", PATH: "/usr/bin" }
  const ev = { command, cwd: "/home/me/project", env }
  await carter.createBefore(ev)
  assert.equal(ev.command, "git push origin main", "the marker is stripped")
  assert.deepEqual(env, { SSH_AUTH_SOCK: "/s", GITHUB_TOKEN: "t", PATH: "/usr/bin" }, "nothing isolated, no tag of either kind")
  assert.equal(r.calls.length, 0, "no identity entry either")
  assert.equal(carter.state(), "passed", "the round trip still proves the hook order")
  carter.dispose()
  r.cleanup()
})

test("a generic subagent of a Carter agent is covered through its parent session", async () => {
  const tree = sessions({ ses_parent: null, ses_child: "ses_parent" })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  // the parent calls the task tool first: that fills the map
  await carter.executeBefore({ tool: "task", sessionID: "ses_parent", input: {}, agent: "carter-maestro" })
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(shell("git push", { sessionID: "ses_child", agent: "general" })), /no/)
  carter.dispose()
  r.cleanup()
})

test("a grandchild is covered up to five hops, deeper than that fails closed", async () => {
  const chain: Record<string, string | null> = { s0: null }
  for (let i = 1; i <= SESSION_HOPS + 2; i++) chain[`s${i}`] = `s${i - 1}`
  const tree = sessions(chain)
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  await carter.executeBefore({ tool: "read", sessionID: "s0", input: {}, agent: "carter-pm" })
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(shell("x", { sessionID: `s${SESSION_HOPS}`, agent: "explore" })), /no/)
  await assert.rejects(carter.executeBefore(shell("x", { sessionID: `s${SESSION_HOPS + 2}`, agent: "explore" })), /no/, "too deep: fail closed")
  carter.dispose()
  r.cleanup()
})

test("an unreadable parent chain is in scope (fail closed)", async () => {
  const tree = sessions({ ses_1: "ses_gone", ses_gone: "unreadable" })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(shell("git push", { agent: "general" })), /no/)
  carter.dispose()
  r.cleanup()
})

test("a child of a session no Carter agent ever used stays out of scope", async () => {
  const tree = sessions({ ses_root: null, ses_kid: "ses_root" })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await carter.executeBefore(shell("git push", { sessionID: "ses_kid", agent: "general" }))
  assert.equal(r.calls.length, 0)
  carter.dispose()
  r.cleanup()
})

test("parent lookups are memoized per session", async () => {
  const tree = sessions({ ses_1: null })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  for (const c of ["a", "b", "c"]) await carter.executeBefore(shell(c, { agent: "build" }))
  assert.deepEqual(tree.looked, ["ses_1"])
  carter.dispose()
  r.cleanup()
})

test("no agent id in the event: a root session cannot be told apart, so it is in scope", async () => {
  const r = rig({ sessionParent: async () => null })
  const carter = createCarter(r.deps)
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(shell("git push")), /no/)
  carter.dispose()
  r.cleanup()
})

test("a Carter workspace puts every agent's shell in scope; outside it nothing is", async () => {
  const root = mkdtempSync(join(tmpdir(), "carter-ws-"))
  const outside = mkdtempSync(join(tmpdir(), "carter-out-"))
  try {
    workspace(root)
    mkdirSync(join(root, "repo", "src"), { recursive: true })
    const tree = sessions({ ses_1: null })
    const r = rig({ sessionParent: tree.sessionParent, sessionDir: async () => outside })
    const carter = createCarter(r.deps)
    r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
    await assert.rejects(carter.executeBefore(shell("git push", { agent: "build", input: { command: "git push", workdir: join(root, "repo", "src") } })), /no/)
    await carter.executeBefore(shell("git push", { agent: "build" })) // the session directory is outside
    assert.equal(r.calls.length, 1)
    carter.dispose()
    r.cleanup()
  } finally {
    rmSync(root, { recursive: true, force: true })
    rmSync(outside, { recursive: true, force: true })
  }
})

test("create.before re-tests the workspace with its own cwd", async () => {
  const root = mkdtempSync(join(tmpdir(), "carter-ws-"))
  try {
    workspace(root)
    const r = rig({ sessionParent: async () => null, sessionDir: async () => "/home/me/elsewhere" })
    const carter = createCarter(r.deps)
    const e = shell("ls", { agent: "build" })
    await carter.executeBefore(e)
    assert.equal(detect(carter.nonce(), (e.input as any).command).scope, false)
    const env: Record<string, string | undefined> = { PATH: "/usr/bin" }
    await carter.createBefore({ command: (e.input as any).command, cwd: join(root, "repo"), env })
    assert.equal(env.CARTER_AGENT_SHELL, "1", "the shell's own directory is a Carter workspace")
    carter.dispose()
    r.cleanup()
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test("workspace test: needs both carter.yaml and a carter-*.md agent file, in the nearest root only", () => {
  const base = mkdtempSync(join(tmpdir(), "carter-ws-"))
  try {
    workspace(join(base, "full"))
    workspace(join(base, "noagents"), { agents: false })
    workspace(join(base, "noyaml"), { yaml: false })
    mkdirSync(join(base, "full", "a", "b", "c"), { recursive: true })
    mkdirSync(join(base, "noagents", "x"), { recursive: true })
    mkdirSync(join(base, "plain"), { recursive: true })
    assert.equal(inCarterWorkspace(fs, join(base, "full")), true)
    assert.equal(inCarterWorkspace(fs, join(base, "full", "a", "b", "c")), true)
    assert.equal(inCarterWorkspace(fs, join(base, "noagents", "x")), false, ".carter alone (global install) is not a workspace install")
    assert.equal(inCarterWorkspace(fs, join(base, "noyaml")), false)
    assert.equal(inCarterWorkspace(fs, join(base, "plain")), false)
    assert.equal(inCarterWorkspace(fs, undefined), false)
    assert.equal(inCarterWorkspace(fs, "relative/dir"), false)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test("workspace test: walks at most 32 levels up", () => {
  const base = mkdtempSync(join(tmpdir(), "carter-ws-"))
  try {
    workspace(base)
    const deep = join(base, ...Array.from({ length: WORKSPACE_LEVELS + 2 }, (_, i) => `d${i}`))
    mkdirSync(deep, { recursive: true })
    assert.equal(inCarterWorkspace(fs, join(base, ...Array.from({ length: WORKSPACE_LEVELS - 1 }, (_, i) => `d${i}`))), true)
    assert.equal(inCarterWorkspace(fs, deep), false)
  } finally {
    rmSync(base, { recursive: true, force: true })
  }
})

test("a failed self-test treats every shell as in scope", async () => {
  const r = rig({ sessionParent: async () => null })
  const carter = createCarter(r.deps)
  await carter.executeBefore(shell("ls", { agent: "build" })) // armed, never created: times out
  r.clock.advance(r.iso.plugin.self_test_ms + 1)
  assert.equal(carter.state(), "failed")
  const e = shell("git push", { agent: "build" })
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(e), /no/)
  const env: Record<string, string | undefined> = { SSH_AUTH_SOCK: "/s" }
  await carter.createBefore({ command: "echo hi", cwd: r.home, env }) // even an unmarked shell
  assert.equal(env.CARTER_AGENT_SHELL, "1")
  carter.dispose()
  r.cleanup()
})

test("a human shell (not marked) is still tagged human in any directory, scope bit or not", async () => {
  const r = rig({ sessionParent: async () => null })
  const carter = createCarter(r.deps)
  const e = shell("ls", { agent: "build" })
  r.respond(() => ({ kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' }))
  await carter.executeBefore(e)
  await carter.createBefore({ command: (e.input as any).command, cwd: "/x", env: {} }) // proves the hook order
  const env: Record<string, string | undefined> = { PATH: "/usr/bin" }
  await carter.createBefore({ command: "ls", cwd: "/x", env })
  assert.equal(env.CARTER_HUMAN_SHELL, "1")
  carter.dispose()
  r.cleanup()
})

test("any tool call of a Carter agent records its session, not only a shell", async () => {
  const tree = sessions({ ses_p: null, ses_c: "ses_p" })
  const r = rig({ sessionParent: tree.sessionParent })
  const carter = createCarter(r.deps)
  await carter.executeBefore({ tool: "subagent", sessionID: "ses_p", input: { agent: "general" }, agent: "carter-maestro" })
  r.respond(() => ({ kind: "exit", code: 1, stdout: DENY }))
  await assert.rejects(carter.executeBefore(shell("git push", { sessionID: "ses_c", agent: "general" })), /no/)
  assert.deepEqual(tree.looked, ["ses_c"], "the parent is in the map: one lookup")
  carter.dispose()
  r.cleanup()
})
