import { Plugin } from "@opencode/plugin"
import { Schema } from "effect"
import { appendFileSync } from "node:fs"

// Spike D probe (plan 004, step 5): a plugin tool named like Carter's broker tools plus a
// permission `evaluate` hook. Logs which stages a call reaches; names and effects only.
// "__LOGS__" is replaced by the harness.
const LOGS = "__LOGS__"
const w = (o: Record<string, unknown>) =>
  appendFileSync(`${LOGS}/deny-probe.log`, JSON.stringify({ t: Date.now(), ...o }) + "\n")

export default Plugin.define({
  id: "denyprobe",
  setup(ctx: any) {
    w({ ev: "setup" })
    ctx.permission.hook("evaluate", (e: any) => {
      w({
        ev: "evaluate",
        action: e.action,
        effect_in: e.effect,
        keys: Object.keys(e).sort(),
        agent: typeof e.agent === "string" ? e.agent : null,
      })
    })
    ctx.tool.hook("execute.before", (e: any) => w({ ev: "execute.before", tool: e.tool, agent: e.agent }))
    ctx.tool.transform((tools: any) => {
      for (const name of ["carter_push", "carter_pr"]) {
        tools.add({
          name,
          options: { codemode: false },
          description: `Spike: ${name} stand-in. Runs nothing.`,
          input: Schema.Struct({ ref: Schema.optional(Schema.String) }),
          output: Schema.Struct({ text: Schema.String }),
          execute: async (_input: any, tctx: any) => {
            w({ ev: "tool.execute", name, agent: String(tctx.agent) })
            try {
              await ctx.permission.assert({
                sessionID: tctx.sessionID,
                agent: tctx.agent,
                action: name,
                resources: ["origin x"],
              })
              w({ ev: "assert.ok", name })
            } catch (err: any) {
              w({ ev: "assert.fail", name, tag: err?._tag ?? err?.name, msg: String(err?.message).slice(0, 100) })
              throw err
            }
            const text = `${name} ran`
            return { output: { text }, content: text }
          },
        })
      }
    })
  },
})
