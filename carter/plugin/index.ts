// Carter plugin for OpenCode. The only file that imports the
// OpenCode plugin API, and the only one `carter guard install` renders: two placeholders below
// become the sha256 of ~/.carter/isolation.json and the Carter version. All logic is in core.ts.
// The broker tool (broker.ts) is registered only while isolation.json says so.
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
    // The session directory is only visible through the session API.
    const sessionDir = async (sessionID: string) => (await ctx.session.get({ sessionID }))?.location?.directory
    // the parent of a session (null for a root); an unreadable session throws, which the scope test
    // treats as "may belong to Carter".
    const sessionParent = async (sessionID: string) => {
      const info = await ctx.session.get({ sessionID })
      if (!info) throw new Error("session not found")
      return info.parentID ? String(info.parentID) : null
    }
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
      sessionParent,
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
