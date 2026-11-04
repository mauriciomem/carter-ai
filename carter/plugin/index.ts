// Carter plugin for OpenCode (RFC-0007 §4.3; plan 004 step 16). The only file that imports the
// OpenCode plugin API, and the only one `carter guard install` renders: two placeholders below
// become the sha256 of ~/.carter/isolation.json and the Carter version. All logic is in core.ts.
// Slice B adds the two broker tools (broker.ts), registered only while isolation.json says so.
import { Plugin } from "@opencode/plugin"
import { Schema } from "effect"
import * as fs from "node:fs"
import { spawn } from "node:child_process"
import { homedir } from "node:os"
import { registerBroker } from "./broker.ts"
import { createCarter, makeRunner } from "./core.ts"

const ISOLATION_SHA256 = "__CARTER_ISOLATION_SHA256__"
const CARTER_VERSION = "__CARTER_VERSION__"

export default Plugin.define({
  id: "carter",
  setup(ctx: any) {
    const run = makeRunner(spawn)
    const clock = {
      now: () => Date.now(),
      setTimeout: (fn: () => void, ms: number) => setTimeout(fn, ms),
      clearTimeout: (handle: unknown) => clearTimeout(handle as ReturnType<typeof setTimeout>),
    }
    // The session directory is only visible through the session API (spike B 3a, G6).
    const sessionDir = async (sessionID: string) => (await ctx.session.get({ sessionID }))?.location?.directory
    const carter = createCarter({
      fs,
      run,
      clock,
      env: process.env,
      home: homedir(),
      pluginVersion: CARTER_VERSION,
      isolationSha256: ISOLATION_SHA256,
      opencodeVersion: String(ctx.app?.version ?? "unknown"),
      pid: process.pid,
      uptimeSec: () => process.uptime(),
      random: Math.random,
      euid: process.geteuid?.(),
      sessionDir,
      log: (line) => console.error(line),
      onFailed: () => void Promise.resolve().then(() => ctx.tool.reload()).catch(() => {}), // B drops out
    })
    ctx.tool.hook("execute.before", (e: any) => carter.executeBefore(e))
    ctx.shell.hook("create.before", (e: any) => carter.createBefore(e))
    registerBroker({
      permission: ctx.permission, session: ctx.session, tool: ctx.tool, carter, run, clock, env: process.env,
      sessionDir, schema: { input: Schema.Struct({}), output: Schema.Struct({ text: Schema.String }) },
      log: (line) => console.error(line),
    }) // prettier-ignore
    return () => carter.dispose() // hot reload or delete: stop the timers and the writes
  },
})
