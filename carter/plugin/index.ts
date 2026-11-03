// Carter plugin for OpenCode (RFC-0007 §4.3; plan 004 step 16). The only file that imports the
// OpenCode plugin API, and the only one `carter guard install` renders: two placeholders below
// become the sha256 of ~/.carter/isolation.json and the Carter version. All logic is in core.ts.
// 2a registers no tool and no permission hook (the broker tools are a later slice).
import { Plugin } from "@opencode/plugin"
import * as fs from "node:fs"
import { spawn } from "node:child_process"
import { homedir } from "node:os"
import { createCarter, makeRunner } from "./core.ts"

const ISOLATION_SHA256 = "__CARTER_ISOLATION_SHA256__"
const CARTER_VERSION = "__CARTER_VERSION__"

export default Plugin.define({
  id: "carter",
  setup(ctx: any) {
    const carter = createCarter({
      fs,
      run: makeRunner(spawn),
      clock: {
        now: () => Date.now(),
        setTimeout: (fn, ms) => setTimeout(fn, ms),
        clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
      },
      env: process.env,
      home: homedir(),
      pluginVersion: CARTER_VERSION,
      isolationSha256: ISOLATION_SHA256,
      opencodeVersion: String(ctx.app?.version ?? "unknown"),
      pid: process.pid,
      uptimeSec: () => process.uptime(),
      random: Math.random,
      euid: process.geteuid?.(),
      // The session directory is only visible through the session API (spike B 3a, G6).
      sessionDir: async (sessionID) => (await ctx.session.get({ sessionID }))?.location?.directory,
      log: (line) => console.error(line),
    })
    ctx.tool.hook("execute.before", (e: any) => carter.executeBefore(e))
    ctx.shell.hook("create.before", (e: any) => carter.createBefore(e))
    return () => carter.dispose() // hot reload or delete: stop the timers and the writes
  },
})
