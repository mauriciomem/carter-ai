// Carter broker tools (RFC-0007 §4.5, App C.5; plan 007 step 15, freeze B2, B6, B19).
//
// `carter_push` and `carter_pr` are THIN: schema, caller check, the approval, the timers, and
// passing JSON between OpenCode and `python -I -m carter.broker_cli`. Every rule (what may be
// pushed, the dwell, the counter, the audit, the texts of the prompt) lives in Python. The
// permission is asked WITHOUT `save`, and `permission.evaluate` forces `ask` for these tools, so
// "Always allow" cannot exist. node:* only, erasable TypeScript only (see core.ts).
import { CarterError, type Clock, type Env, type Iso, type Run } from "./core.ts"

const PREFIX = "carter_"
const VERBS = ["push", "pr"]
const CALL_MS = { plan: 60_000, exec: 300_000, record: 30_000 }
const DECLINED = "Permission.DeclinedError" // a plain reject: the turn ends (spike B2)
const CORRECTED = "Tool.Error" // a reject with a message

export interface BrokerDeps {
  permission: {
    assert(input: unknown): Promise<void>
    list(input: unknown): Promise<any[]>
    reply(input: unknown): Promise<unknown>
    hook(name: string, cb: (e: any) => void): unknown
  }
  session: { get(input: { sessionID: string }): Promise<any> }
  tool: { transform(cb: (tools: any) => void): unknown }
  carter: { isolation(): Iso; brokerOn(): boolean; state(): string }
  run: Run
  clock: Clock
  env: Env // the server environment, handed to Python unchanged (it refuses a polluted one)
  sessionDir: (sessionID: string) => Promise<string | undefined>
  schema: { input: unknown; output: unknown }
  log: (line: string) => void
}
type Doc = Record<string, any>
const tagOf = (e: any): string => e?._tag ?? e?.name ?? ""

export function registerBroker(deps: BrokerDeps): void {
  const { permission, carter, clock } = deps

  async function call(argv: string[], timeoutMs: number): Promise<Doc> {
    const res = await deps.run(argv, { cwd: "/", input: "", timeoutMs, env: deps.env })
    let doc: Doc | undefined
    if (res.kind === "exit") {
      try {
        doc = JSON.parse(res.stdout)
      } catch {
        doc = undefined
      }
    }
    if (res.kind === "exit" && res.code === 0 && doc) return doc
    const text = doc && typeof doc.message === "string" ? `${doc.message} [${doc.code}] ${doc.detail ?? ""}`.trim() : "the broker did not answer"
    throw new Error(`carter: ${text}`)
  }

  async function rootOf(sessionID: string): Promise<string> {
    let id = sessionID
    for (let i = 0; i < 8; i++) {
      const parent = (await deps.session.get({ sessionID: id }))?.parentID
      if (!parent) return id
      id = String(parent)
    }
    throw new Error("carter: the session tree is too deep to find its root")
  }

  // Reject OUR pending request (matched by the tool call id). It would otherwise stay in the
  // human's prompt after the tool gave up, and a late "yes" would do nothing (spike B4, B4c).
  async function dismiss(sessionID: string, callID: string): Promise<void> {
    try {
      const mine = (await permission.list({ sessionID })).find((r) => r?.source?.id === callID)
      if (mine) await permission.reply({ sessionID, requestID: mine.id, decision: "reject" })
    } catch (err) {
      deps.log(`carter: could not withdraw the pending request (${tagOf(err)})`)
    }
  }

  async function approve(name: string, tctx: any, plan: Doc): Promise<{ outcome: string; error?: unknown }> {
    // no `save`: the prompt offers Once or Reject only
    const asked = permission.assert({
      sessionID: tctx.sessionID, agent: tctx.agent, action: name,
      resources: plan.ask.resources, metadata: plan.ask.metadata,
      source: { type: "tool", messageID: tctx.messageID, id: tctx.id },
    }) // prettier-ignore
    const settled = asked.then(() => ({ outcome: "approved" }), (error) => ({ outcome: "rejected", error }))
    let timer: unknown
    let onAbort: (() => void) | undefined
    const clocked = new Promise<{ outcome: string }>((resolve) => {
      timer = clock.setTimeout(() => resolve({ outcome: "timeout" }), plan.approval.timeout_ms)
      onAbort = () => resolve({ outcome: "aborted" })
      if (tctx.signal?.aborted) onAbort()
      else tctx.signal?.addEventListener("abort", onAbort, { once: true })
    })
    const result = await Promise.race([settled, clocked])
    clock.clearTimeout(timer)
    if (onAbort) tctx.signal?.removeEventListener("abort", onAbort)
    if (result.outcome === "timeout" || result.outcome === "aborted") await dismiss(tctx.sessionID, tctx.id)
    return result
  }

  async function run(verb: string, input: unknown, tctx: any): Promise<{ output: Doc; content: string }> {
    void input // the tools take no input at all
    const iso = carter.isolation()
    const p = iso.plugin
    if (!p.b_enabled || carter.state() === "failed") throw new Error("carter: B is not available (see `carter check --host`)")
    if (tctx.agent !== p.b_caller) throw new CarterError("E-B-CALLER")
    const cwd = await deps.sessionDir(tctx.sessionID)
    if (!cwd) throw new Error("carter: the session directory is unknown")
    const who = ["--agent", tctx.agent, "--session", tctx.sessionID, "--root", await rootOf(tctx.sessionID)]
    const head = [p.python_path, ...p.broker_args]
    const flags = ["--cwd", cwd, ...who, "--git", p.b_git, "--gh", p.b_gh]
    const plan = await call([...head, verb, "--plan", ...flags], CALL_MS.plan)
    const askedAt = clock.now()
    const { outcome, error } = await approve(`${PREFIX}${verb}`, tctx, plan)
    const answeredAt = clock.now()
    if (outcome === "approved") {
      const done = await call([...head, verb, "--exec", ...flags, "--pinned-sha", plan.pinned_sha, "--asked-at", String(askedAt), "--answered-at", String(answeredAt)], CALL_MS.exec)
      return { output: { text: String(done.text ?? "done") }, content: String(done.text ?? "done") }
    }
    const kind = outcome === "rejected" ? (tagOf(error) === DECLINED ? "rejected" : tagOf(error) === CORRECTED && !/^Permission denied/.test(String((error as any)?.message)) ? "corrected" : "") : outcome
    if (!kind) throw error // a config deny or another failure: nothing to count
    const noted = await call([...head, "record", "--outcome", kind, ...who, "--audit", JSON.stringify(plan.audit)], CALL_MS.record).catch(() => ({}) as Doc)
    if (kind === "timeout") throw new Error(`carter: ${noted.message ?? "No approval within 120 s; refused."}`)
    if (kind === "aborted") throw new Error("carter: the request was cancelled before an answer")
    throw error // rethrown as it came: OpenCode ends the turn on a plain decline
  }

  // `ask` for exactly our two tools unless a config deny already said no (evaluate runs after it).
  // Not `carter_*`: the Carter GitHub MCP tools (`carter_github_*`) are not ours to prompt on.
  const ours = new Set(VERBS.map((verb) => `${PREFIX}${verb}`))
  permission.hook("evaluate", (e: any) => {
    if (carter.brokerOn() && ours.has(String(e.action)) && e.effect !== "deny") e.effect = "ask"
  })
  deps.tool.transform((tools: any) => {
    if (!carter.brokerOn()) return
    for (const verb of VERBS) {
      tools.add({
        name: `${PREFIX}${verb}`,
        options: { codemode: false },
        description: verb === "push" ? "Ask the human to approve pushing the current branch to origin (devops only; every use asks)." : "Ask the human to approve opening the pull request described by the handoff file (devops only; every use asks).",
        input: deps.schema.input,
        output: deps.schema.output,
        execute: (input: unknown, tctx: any) => run(verb, input, tctx),
      })
    }
  })
}
