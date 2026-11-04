import { Plugin } from "@opencode/plugin"
import { appendFileSync, readFileSync } from "node:fs"

// Spike C probe (plan 005, step 4). Stands in for the 2b signing block: it runs AFTER the 2a
// plugin (path-sorted: plugins/carter < plugins/zprobe), appends GIT_CONFIG_* entries to the
// count 2a already set, and sets the committer. It logs names and counts, never values.
// `__LOGS__/probe.json` is read at every shell creation: {sign, pairs, name, email, version}.

const LOGS = "__LOGS__"
const NONCE = Math.random().toString(36).slice(2, 8)
const w = (o: Record<string, unknown>) =>
  appendFileSync(`${LOGS}/probe.log`, JSON.stringify({ nonce: NONCE, t: Date.now(), ...o }) + "\n")

export default Plugin.define({
  id: "signprobe",
  setup(ctx: any) {
    const cfg = () => {
      try {
        return JSON.parse(readFileSync(`${LOGS}/probe.json`, "utf8"))
      } catch {
        return { sign: false }
      }
    }
    w({ ev: "setup", version: cfg().version ?? null })
    ctx.shell.hook("create.before", (e: any) => {
      const c = cfg()
      const agent = e.env.CARTER_AGENT_SHELL === "1"
      const before = parseInt(e.env.GIT_CONFIG_COUNT ?? "0", 10)
      w({ ev: "create", agent, count_before: before, sign: !!c.sign })
      if (!agent || !c.sign) return
      let n = before
      for (const [k, v] of c.pairs as [string, string][]) {
        e.env[`GIT_CONFIG_KEY_${n}`] = k
        e.env[`GIT_CONFIG_VALUE_${n}`] = v
        n++
      }
      e.env.GIT_CONFIG_COUNT = String(n)
      e.env.GIT_COMMITTER_NAME = c.name
      e.env.GIT_COMMITTER_EMAIL = c.email
    })
    return () => w({ ev: "cleanup" })
  },
})
