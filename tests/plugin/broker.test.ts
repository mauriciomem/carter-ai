// The broker tool wrapper: thin, fake OpenCode ctx, fake Python.
import { test } from "node:test"
import assert from "node:assert/strict"
import { registerBroker, type BrokerDeps } from "../../carter/plugin/broker.ts"
import { CarterError, type Iso, type Run } from "../../carter/plugin/core.ts"
import { fakeClock, isoDoc } from "./helpers.ts"

const PLAN = {
  verb: "push", pinned_sha: "a".repeat(40),
  approval: { min_dwell_ms: 500, timeout_ms: 120000 },
  ask: { resources: ["push o/r feat/x"], metadata: { verb: "push", caller: "carter-devops" } },
  audit: { owner_repo: "o/r", branch: "feat/x", range: "a..b", commits: 1, verb: "push" },
} // prettier-ignore

function iso(over: Partial<Iso["plugin"]> = {}): Iso {
  const doc: Iso = JSON.parse(JSON.stringify(isoDoc))
  Object.assign(doc.plugin, { python_path: "/opt/py", b_enabled: true, b_git: "/usr/bin/git", b_gh: "/usr/bin/gh" }, over)
  return doc
}
const ok = (doc: object) => ({ kind: "exit" as const, code: 0, stdout: JSON.stringify(doc) })
const refusal = (code: string, message: string) => ({ kind: "exit" as const, code: 1, stdout: JSON.stringify({ code, message, detail: "" }) })

interface Rig {
  clock: ReturnType<typeof fakeClock>
  calls: string[][]
  asserts: any[]
  replies: any[]
  tools: Record<string, any>
  hooks: Record<string, (e: any) => void>
  answer: { resolve: () => void; reject: (e: unknown) => void }
  pending: any[]
  respond: (argv: string[]) => any
  tctx: (over?: any) => any
  deps: BrokerDeps
}

function rig(opts: { isoDoc?: Iso; state?: string; sessions?: Record<string, any> } = {}): Rig {
  const clock = fakeClock()
  const calls: string[][] = []
  const asserts: any[] = []
  const replies: any[] = []
  const hooks: Rig["hooks"] = {}
  const tools: Rig["tools"] = {}
  const pending: any[] = []
  const answer = { resolve: () => {}, reject: (_e: unknown) => {} }
  const doc = opts.isoDoc ?? iso()
  const r: Rig = {
    clock, calls, asserts, replies, tools, hooks, answer, pending,
    respond: (argv) => {
      if (argv.includes("--plan")) return ok(PLAN)
      if (argv.includes("--exec")) return ok({ ok: true, text: "Pushed feat/x (a..b) to o/r." })
      if (argv.includes("record")) return argv.includes("timeout") ? ok({ ok: true, code: "E-B-TIMEOUT", message: "No approval within 120 s; refused." }) : ok({ ok: true, count: 1 })
      return refusal("E-B-ARGS", "?")
    },
    tctx: (over = {}) => ({ agent: "carter-devops", sessionID: "ses_c", messageID: "msg_1", id: "call_1", signal: new AbortController().signal, ...over }),
    deps: undefined as unknown as BrokerDeps,
  } // prettier-ignore
  const run: Run = async (argv) => {
    calls.push(argv)
    return r.respond(argv)
  }
  r.deps = {
    permission: {
      assert: (input) => {
        asserts.push(input)
        return new Promise<void>((resolve, reject) => ((answer.resolve = resolve), (answer.reject = reject)))
      },
      list: async () => pending,
      reply: async (input) => void replies.push(input),
      hook: (name, cb) => void (hooks[name] = cb),
    },
    session: { get: async ({ sessionID }) => (opts.sessions ?? { ses_c: { id: "ses_c" } })[sessionID] },
    tool: { transform: (cb) => cb({ add: (t: any) => void (tools[t.name] = t) }) },
    carter: { isolation: () => doc, brokerOn: () => doc.plugin.b_enabled && (opts.state ?? "passed") !== "failed", state: () => opts.state ?? "passed" },
    run, clock, env: { SERVER: "env" }, sessionDir: async () => "/work/repo",
    schema: { input: "IN", output: "OUT" }, log: () => {},
  } // prettier-ignore
  return r
}
const flush = () => new Promise((resolve) => setImmediate(resolve))

test("it registers the one tool, direct (not Code Mode), with no input of the model's own", () => {
  const r = rig()
  registerBroker(r.deps)
  assert.deepEqual(Object.keys(r.tools).sort(), ["carter_push"])
  for (const t of Object.values(r.tools)) {
    assert.deepEqual(t.options, { codemode: false })
    assert.equal(t.input, "IN")
  }
})

test("it registers nothing while B is off or the self-test failed", () => {
  for (const r of [rig({ isoDoc: iso({ b_enabled: false, b_git: "" }) }), rig({ state: "failed" })]) {
    registerBroker(r.deps)
    assert.deepEqual(Object.keys(r.tools), [])
  }
})

test("evaluate forces ask for the broker tool except on deny, and for nothing else named carter_*", () => {
  const r = rig()
  registerBroker(r.deps)
  for (const [action, from, to] of [["carter_push", "allow", "ask"], ["carter_pr", "allow", "allow"], ["carter_push", "deny", "deny"], ["edit", "allow", "allow"], ["carter_github_search", "allow", "allow"], ["carter_other", "allow", "allow"]]) {
    const e = { action, effect: from }
    r.hooks.evaluate(e)
    assert.equal(e.effect, to, `${action} ${from}`)
  }
})

test("while B is off the evaluate hook leaves every action alone", () => {
  const r = rig({ isoDoc: iso({ b_enabled: false, b_git: "" }) })
  registerBroker(r.deps)
  const e = { action: "carter_push", effect: "allow" }
  r.hooks.evaluate(e)
  assert.equal(e.effect, "allow")
})

test("only devops: any other agent gets E-B-CALLER and Python is never run", async () => {
  const r = rig()
  registerBroker(r.deps)
  for (const agent of ["general", "build", "carter-engineer", ""]) {
    await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx({ agent })), (e: any) => e instanceof CarterError && e.code === "E-B-CALLER")
  }
  assert.equal(r.calls.length, 0)
  assert.equal(r.asserts.length, 0)
})

test("the self-test failing after registration refuses the call", async () => {
  let state = "passed"
  const r = rig()
  r.deps.carter.state = () => state
  registerBroker(r.deps)
  state = "failed"
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx()), /not available/)
  assert.equal(r.calls.length, 0)
})

test("the whole flow: plan, one ask without save, the approval, then exec with the pinned sha and raw times", async () => {
  const r = rig()
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  assert.equal(r.calls.length, 1)
  assert.deepEqual(r.calls[0].slice(0, 4), ["/opt/py", "-I", "-m", "carter.broker_cli"])
  assert.ok(r.calls[0].includes("push") && r.calls[0].includes("--plan"))
  assert.deepEqual(r.calls[0].slice(r.calls[0].indexOf("--cwd"), r.calls[0].indexOf("--cwd") + 2), ["--cwd", "/work/repo"])
  assert.equal(r.asserts.length, 1)
  const ask = r.asserts[0]
  assert.equal(ask.action, "carter_push")
  assert.ok(!("save" in ask), "never save: Once or Reject only")
  assert.deepEqual(ask.resources, PLAN.ask.resources)
  assert.deepEqual(ask.source, { type: "tool", messageID: "msg_1", id: "call_1" })
  r.clock.advance(812)
  r.answer.resolve()
  const result = await done
  assert.equal(result.content, "Pushed feat/x (a..b) to o/r.")
  const exec = r.calls[1]
  const at = (flag: string) => exec[exec.indexOf(flag) + 1]
  assert.ok(exec.includes("--exec"))
  assert.equal(at("--pinned-sha"), PLAN.pinned_sha)
  assert.equal(Number(at("--answered-at")) - Number(at("--asked-at")), 812)
  assert.deepEqual([at("--agent"), at("--session"), at("--root"), at("--git"), at("--gh")], ["carter-devops", "ses_c", "ses_c", "/usr/bin/git", "/usr/bin/gh"])
})

test("the server environment is handed to Python unchanged; the wrapper builds no environment", async () => {
  const r = rig()
  const seen: any[] = []
  const run0 = r.deps.run
  r.deps.run = async (argv, opts) => (seen.push(opts.env), run0(argv, opts))
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  r.answer.resolve()
  await done
  assert.ok(seen.length === 2 && seen.every((e) => e.SERVER === "env"))
})

test("a refusal from the plan is the model's error text and nothing is asked", async () => {
  const r = rig()
  r.respond = () => refusal("E-B-DEFAULT", "`main` is the remote default branch; the broker never pushes it.")
  registerBroker(r.deps)
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx()), /default branch.*E-B-DEFAULT/)
  assert.equal(r.asserts.length, 0)
})

test("a refusal from exec (dwell, moved, unsigned...) is the model's error text", async () => {
  const r = rig()
  const base = r.respond
  r.respond = (argv) => (argv.includes("--exec") ? refusal("E-B-DWELL", "carter_push refused: approval arrived in 3ms (< 500ms)") : base(argv))
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  r.answer.resolve()
  await assert.rejects(() => done, /arrived in 3ms/)
})

test("a plain reject is recorded as rejected and rethrown as it came", async () => {
  const r = rig()
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  const declined = Object.assign(new Error("declined"), { _tag: "Permission.DeclinedError" })
  r.answer.reject(declined)
  await assert.rejects(() => done, (e) => e === declined)
  const rec = r.calls.at(-1)!
  assert.ok(rec.includes("record") && rec[rec.indexOf("--outcome") + 1] === "rejected")
  assert.deepEqual(JSON.parse(rec[rec.indexOf("--audit") + 1]), PLAN.audit)
  assert.ok(!r.calls.some((c) => c.includes("--exec")))
})

test("a reject with a message is recorded as corrected", async () => {
  const r = rig()
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  r.answer.reject(Object.assign(new Error("no thanks"), { _tag: "Tool.Error" }))
  await assert.rejects(() => done, /no thanks/)
  assert.equal(r.calls.at(-1)![r.calls.at(-1)!.indexOf("--outcome") + 1], "corrected")
})

test("a config deny or another failure is not counted as a rejection", async () => {
  for (const err of [Object.assign(new Error("Permission denied: carter_push"), { _tag: "Tool.Error" }), new Error("boom")]) {
    const r = rig()
    registerBroker(r.deps)
    const done = r.tools.carter_push.execute({}, r.tctx())
    await flush()
    r.answer.reject(err)
    await assert.rejects(() => done, (e) => e === err)
    assert.ok(!r.calls.some((c) => c.includes("record")))
  }
})

test("after 120 s it withdraws its own request by call id, records the timeout and a late yes does nothing", async () => {
  const r = rig()
  r.pending.push({ id: "per_other", source: { id: "call_other" } }, { id: "per_mine", source: { id: "call_1" } })
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  r.clock.advance(119_999)
  await flush()
  assert.equal(r.replies.length, 0)
  r.clock.advance(2)
  await assert.rejects(() => done, /No approval within 120 s/)
  assert.deepEqual(r.replies, [{ sessionID: "ses_c", requestID: "per_mine", decision: "reject" }])
  assert.equal(r.calls.at(-1)![r.calls.at(-1)!.indexOf("--outcome") + 1], "timeout")
  r.answer.resolve() // the human says yes too late
  await flush()
  assert.ok(!r.calls.some((c) => c.includes("--exec")))
})

test("a session abort withdraws the request and records an abort", async () => {
  const r = rig()
  r.pending.push({ id: "per_mine", source: { id: "call_1" } })
  registerBroker(r.deps)
  const controller = new AbortController()
  const done = r.tools.carter_push.execute({}, r.tctx({ signal: controller.signal }))
  await flush()
  controller.abort()
  await assert.rejects(() => done, /cancelled/)
  assert.equal(r.replies[0].decision, "reject")
  assert.equal(r.calls.at(-1)![r.calls.at(-1)!.indexOf("--outcome") + 1], "aborted")
})

test("an already-aborted call does not even wait", async () => {
  const r = rig()
  registerBroker(r.deps)
  const controller = new AbortController()
  controller.abort()
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx({ signal: controller.signal })), /cancelled/)
})

test("if the request is already gone the timeout only records", async () => {
  const r = rig()
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx())
  await flush()
  r.clock.advance(120_001)
  await assert.rejects(() => done, /120 s/)
  assert.equal(r.replies.length, 0)
})

test("a subagent ask carries the child session and the root of its family", async () => {
  const sessions = { ses_child: { id: "ses_child", parentID: "ses_mid" }, ses_mid: { id: "ses_mid", parentID: "ses_root" }, ses_root: { id: "ses_root" } }
  const r = rig({ sessions })
  registerBroker(r.deps)
  const done = r.tools.carter_push.execute({}, r.tctx({ sessionID: "ses_child" }))
  await flush()
  const plan = r.calls[0]
  assert.equal(plan[plan.indexOf("--session") + 1], "ses_child")
  assert.equal(plan[plan.indexOf("--root") + 1], "ses_root")
  r.answer.resolve()
  await done
})

test("a session tree that cannot be walked fails closed", async () => {
  const r = rig({ sessions: { ses_c: { id: "ses_c", parentID: "ses_c" } } })
  registerBroker(r.deps)
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx()), /too deep/)
  const r2 = rig()
  r2.deps.session.get = async () => {
    throw new Error("gone")
  }
  registerBroker(r2.deps)
  await assert.rejects(() => r2.tools.carter_push.execute({}, r2.tctx()), /gone/)
  assert.equal(r2.asserts.length, 0)
})

test("no session directory, no run", async () => {
  const r = rig()
  r.deps.sessionDir = async () => undefined
  registerBroker(r.deps)
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx()), /directory is unknown/)
  assert.equal(r.calls.length, 0)
})

test("a broker that does not answer is a refusal, never an approval", async () => {
  const r = rig()
  r.respond = () => ({ kind: "timeout" })
  registerBroker(r.deps)
  await assert.rejects(() => r.tools.carter_push.execute({}, r.tctx()), /did not answer/)
  assert.equal(r.asserts.length, 0)
})
