import { Plugin } from "@opencode/plugin"
import { appendFileSync } from "node:fs"

// Spike C probe (plan 004, step 4): the self-test state machine of RFC-0007 App C.2.
//   unproven -> passed   on the first marked round trip (execute.before marks, create.before sees it)
//   any      -> failed   when a marked execute.before is not followed by a marked create.before in N ms
// Server env knobs (set by the tests): PROBE_N_MS (default 2000), PROBE_VARIANT:
//   ok              the design
//   strip_in_exec   the marker is removed again inside execute.before (a broken hook order)
//   skip_create     create.before ignores the marker (as if it never ran)
//   arm_first       arms the timer BEFORE a possible rejection (the bug the spike warns about)
// States, timings and env variable NAMES only are logged to <logs>/selftest.log.

const LOGS = "__LOGS__"
const N_MS = Number(process.env.PROBE_N_MS ?? 2000)
const VARIANT = process.env.PROBE_VARIANT ?? "ok"
const NONCE = Math.random().toString(36).slice(2, 12)
const MARK = `: carter_agent_${NONCE}\n`
const AGENT_SIGNALS = ["CARTER_AGENT_SHELL", "AGENT", "AI_AGENT", "OPENCODE", "OPENCODE_SESSION_ID"]

type State = "unproven" | "passed" | "failed"
let state: State = "unproven"
let warned = false
const pending: { t0: number; timer: ReturnType<typeof setTimeout> }[] = []

const w = (o: Record<string, unknown>) =>
  appendFileSync(`${LOGS}/selftest.log`, JSON.stringify({ t: Date.now(), state, ...o }) + "\n")

function arm() {
  const t0 = Date.now()
  const timer = setTimeout(() => {
    if (state !== "failed") {
      state = "failed"
      w({ ev: "state", to: "failed", after_ms: Date.now() - t0 })
    }
  }, N_MS)
  pending.push({ t0, timer })
}

export default Plugin.define({
  id: "selftest",
  setup(ctx: any) {
    w({ ev: "setup", variant: VARIANT, n_ms: N_MS, version: ctx.app?.version })

    ctx.tool.hook("execute.before", (e: any) => {
      if (e.tool !== "shell" || typeof e.input?.command !== "string") return
      if (VARIANT === "arm_first") arm()
      if (e.input.command.includes("PROBE_REJECT")) throw new Error("probe: rejected in execute.before")
      e.input.command = MARK + e.input.command
      if (VARIANT === "strip_in_exec") e.input.command = e.input.command.slice(MARK.length)
      if (VARIANT !== "arm_first") arm()
    })

    ctx.shell.hook("create.before", (e: any) => {
      const marked = typeof e.command === "string" && e.command.startsWith(MARK) && VARIANT !== "skip_create"
      if (marked) {
        e.command = e.command.slice(MARK.length)
        const first = pending.shift()
        if (first) clearTimeout(first.timer)
        if (state === "unproven") {
          state = "passed"
          w({ ev: "state", to: "passed", round_trip_ms: first ? Date.now() - first.t0 : null })
        }
      }
      // pollution is judged on the INHERITED env, so before our own markers are deleted
      const polluted = AGENT_SIGNALS.filter((k) => e.env[k] !== undefined)
      delete e.env.CARTER_AGENT_SHELL
      delete e.env.CARTER_HUMAN_SHELL
      let tag = "none"
      if (marked || state === "failed") {
        e.env.CARTER_AGENT_SHELL = "1"
        tag = "agent"
      } else if (state === "passed") {
        if (polluted.length === 0) {
          e.env.CARTER_HUMAN_SHELL = "1"
          tag = "human"
        } else if (!warned) {
          warned = true
          w({ ev: "warn", msg: "server env polluted; no human tag", names: polluted })
        }
      }
      w({ ev: "create", marked, tag, pending: pending.length })
    })
  },
})
