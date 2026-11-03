import { Plugin } from "@opencode/plugin"
import { appendFileSync } from "node:fs"
import { execFileSync } from "node:child_process"

// Spike B probe (plan 004, step 3). Logs hook shapes, env KEY NAMES and timings. Never env values.
// Behaviour is driven by words in the shell command (the mock model sends them):
//   PROBE_THROW_EXEC    -> throw in execute.before
//   PROBE_THROW_CREATE  -> throw in create.before
//   PROBE_NOMARK        -> do not add the marker (the create.before side then sees an unmarked shell)
// "__LOGS__" is replaced by the harness with the rig's log directory.

const LOGS = "__LOGS__"
const w = (o: Record<string, unknown>) =>
  appendFileSync(`${LOGS}/plugin.log`, JSON.stringify({ t: Date.now(), p: Math.round(performance.now() * 1000) / 1000, ...o }) + "\n")

const NONCE = Math.random().toString(36).slice(2, 12)
const MARK = `: carter_probe_${NONCE}\n`
const INTEREST = /^(AGENT|AI_AGENT|OPENCODE|OPENCODE_[A-Z_]+|CARTER_[A-Z_]+|SSH_AUTH_SOCK|GITHUB_TOKEN|GH_TOKEN|PROBE_[A-Z_]+|TERM)$/
const names = (env: Record<string, unknown>) => Object.keys(env).filter((k) => INTEREST.test(k)).sort()
const kinds = (env: Record<string, unknown>) =>
  Object.fromEntries(Object.keys(env).filter((k) => INTEREST.test(k)).sort().map((k) => [k, typeof env[k]]))
const prefix = (v: unknown) => (typeof v === "string" ? v.slice(0, 8) : typeof v)

export default Plugin.define({
  id: "groundtruth",
  setup(ctx: any) {
    const t0 = performance.now()
    let childProcessOk = false
    try {
      childProcessOk = execFileSync("echo", ["ok"]).toString().trim() === "ok"
    } catch {}
    const g = globalThis as any
    w({
      ev: "setup",
      ctx_keys: Object.keys(ctx).sort(),
      app: ctx.app,
      options_keys: Object.keys(ctx.options ?? {}),
      bun: typeof g.Bun,
      bun_version: g.Bun?.version ?? null,
      node_version: process.version,
      platform: process.platform,
      pid: process.pid,
      argv: process.argv.slice(1).map((a) => (a.length > 50 ? a.slice(0, 50) + "..." : a)),
      cwd: process.cwd(),
      fs_ok: typeof appendFileSync === "function",
      child_process_ok: childProcessOk,
      server_env_names: names(process.env),
      process_uptime_s: process.uptime(),
      setup_ms: performance.now() - t0,
      nonce_len: NONCE.length,
    })

    ctx.tool.hook("execute.before", (e: any) => {
      const cmd = e.tool === "shell" && typeof e.input?.command === "string" ? e.input.command : null
      w({
        ev: "execute.before",
        tool: e.tool,
        keys: Object.keys(e).sort(),
        agent: e.agent,
        sid: prefix(e.sessionID),
        mid: prefix(e.messageID),
        id: prefix(e.id),
        input_type: typeof e.input,
        input_keys: e.input && typeof e.input === "object" ? Object.keys(e.input).sort() : null,
        cmd: cmd === null ? null : cmd.slice(0, 80),
        workdir: e.input?.workdir ?? null,
        background: e.input?.background ?? null,
      })
      if (cmd === null) return
      if (cmd.includes("PROBE_THROW_EXEC")) throw new Error("probe: execute.before refused this command (rule R-PROBE)")
      if (!cmd.includes("PROBE_NOMARK")) e.input.command = MARK + cmd
    })

    ctx.tool.hook("execute.after", (e: any) => {
      w({
        ev: "execute.after",
        tool: e.tool,
        keys: Object.keys(e).sort(),
        id: prefix(e.id),
        status: e.status,
        error: e.status === "error" ? String(e.error?.message).slice(0, 80) : null,
      })
    })

    ctx.shell.hook("create.before", (e: any) => {
      const marker = String(e.command).startsWith(MARK)
      w({
        ev: "create.before",
        keys: Object.keys(e).sort(),
        marker,
        cmd: String(e.command).slice(marker ? MARK.length : 0, 80 + (marker ? MARK.length : 0)),
        cwd: e.cwd,
        timeout: e.timeout,
        shell: e.shell,
        env_names_before: names(e.env),
        env_kinds_before: kinds(e.env),
        env_count: Object.keys(e.env).length,
      })
      const bare = marker ? String(e.command).slice(MARK.length) : String(e.command)
      if (bare.includes("PROBE_THROW_CREATE")) throw new Error("probe: create.before refused this shell")
      if (marker) e.command = bare
      // env experiments, visible to the command through `env | cut -d= -f1`
      e.env.PROBE_SET = "1"
      delete e.env.SSH_AUTH_SOCK
      e.env.PROBE_UNDEF = undefined
      e.env.GH_TOKEN = "dummy"
      e.env.GITHUB_TOKEN = undefined
      if (marker) e.env.PROBE_AGENT_TAG = "1"
      else e.env.PROBE_HUMAN_TAG = "1"
    })
  },
})
