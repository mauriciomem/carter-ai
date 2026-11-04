import { Plugin } from "@opencode/plugin"
import { Schema } from "effect"
import { appendFileSync, existsSync, readFileSync } from "node:fs"

// Spike probe for plan 007 (steps 2-3): stand-ins for carter_push / carter_pr that run NOTHING.
// They record what the tool context carries, what the permission ask looks like, how long the
// approval takes, and what happens when the tool gives up. Names and timings only, no secrets.
// "__LOGS__" is replaced by the rig. `b-status.json` ({"selftest": "failed"}) switches the
// registration off, the way Carter's plugin will couple B to its self-test.
const LOGS = "__LOGS__"
const w = (o: Record<string, unknown>) =>
  appendFileSync(`${LOGS}/broker-probe.log`, JSON.stringify({ t: Date.now(), ...o }) + "\n")
const status = () => {
  try {
    return JSON.parse(readFileSync(`${LOGS}/b-status.json`, "utf8")).selftest ?? "unproven"
  } catch {
    return "unproven"
  }
}
let transforms = 0
let counter = 0
const tag = (e: any) => e?._tag ?? e?.name ?? typeof e

export default Plugin.define({
  id: "brokerprobe",
  setup(ctx: any) {
    w({ ev: "setup", ctx_keys: Object.keys(ctx).sort(), permission_keys: Object.keys(ctx.permission ?? {}).sort(), tool_keys: Object.keys(ctx.tool ?? {}).sort() })

    ctx.permission.hook("evaluate", (e: any) => {
      if (!String(e.action).startsWith("carter_")) return
      const forced = e.effect !== "deny"
      w({ ev: "evaluate", action: e.action, effect_in: e.effect, forced, agent: e.agent, session: e.sessionID, keys: Object.keys(e).sort() })
      if (forced) e.effect = "ask"
    })
    ctx.tool.hook("execute.before", (e: any) => {
      if (String(e.tool).startsWith("carter_") || e.tool === "bp_ctl") w({ ev: "execute.before", tool: e.tool, agent: e.agent, session: e.sessionID })
    })

    ctx.tool.transform((tools: any) => {
      transforms++
      const st = status()
      w({ ev: "transform", n: transforms, status: st, before: tools.list().map((t: any) => t.id).filter((id: string) => /^(carter_|bp_)/.test(id)) })
      tools.add({
        name: "bp_ctl",
        options: { codemode: false },
        description: "Spike control tool. Never call it.",
        input: Schema.Struct({ op: Schema.String, session: Schema.optional(Schema.String) }),
        output: Schema.Struct({ text: Schema.String }),
        execute: async (input: any, tctx: any) => {
          let text = "?"
          try {
            if (input.op === "reload") {
              // awaiting reload() inside a running tool call never returns (observed); schedule it
              setTimeout(() => ctx.tool.reload().then(() => w({ ev: "reloaded" }), (e: any) => w({ ev: "reload.fail", msg: String(e?.message).slice(0, 100) })), 300)
              text = "reload scheduled"
            } else if (input.op === "list") {
              text = JSON.stringify((await ctx.tool.list()).map((t: any) => t.id).filter((id: string) => /^(carter_|bp_)/.test(id)))
            } else if (input.op === "family") {
              const chain: any[] = []
              let id: any = input.session ?? tctx.sessionID
              for (let i = 0; i < 6 && id; i++) {
                const info: any = await ctx.session.get({ sessionID: id })
                chain.push({ id: String(id).slice(0, 14), parentID: info?.data?.parentID ?? info?.parentID ?? null, keys: Object.keys(info ?? {}).slice(0, 6) })
                id = info?.data?.parentID ?? info?.parentID
              }
              text = JSON.stringify(chain)
            } else if (input.op === "pending") {
              text = JSON.stringify(await ctx.permission.list({ sessionID: input.session ?? tctx.sessionID }))
            }
          } catch (err: any) {
            text = `error ${tag(err)} ${String(err?.message).slice(0, 120)}`
          }
          w({ ev: "ctl", op: input.op, text: text.slice(0, 400) })
          return { output: { text }, content: text }
        },
      })
      if (st === "failed") return
      for (const [name, codemode] of [["carter_push", false], ["carter_pr", true]] as const) {
        tools.add({
          name,
          options: { codemode },
          description: `Spike: ${name} stand-in. Runs nothing.`,
          input: Schema.Struct({
            mode: Schema.optional(Schema.String), // assert | noassert
            timeout_ms: Schema.optional(Schema.Number),
            own_id: Schema.optional(Schema.Boolean),
            reject_on_timeout: Schema.optional(Schema.Boolean),
            min_dwell_ms: Schema.optional(Schema.Number),
            max_dwell_ms: Schema.optional(Schema.Number),
            note: Schema.optional(Schema.String),
          }),
          output: Schema.Struct({ text: Schema.String }),
          execute: async (input: any, tctx: any) => {
            const t0 = performance.now()
            const ms = () => Math.round(performance.now() - t0)
            w({ ev: "tool.execute", name, ctx_keys: Object.keys(tctx).sort(), agent: tctx.agent, agent_type: typeof tctx.agent, session: tctx.sessionID, has_signal: !!tctx.signal, input })
            tctx.signal?.addEventListener("abort", () => w({ ev: "signal.abort", name, ms: ms() }))
            if (input.mode === "noassert") return { output: { text: "noassert" }, content: "noassert" }
            const rid = input.own_id ? `per_bp${Date.now()}x${++counter}` : undefined
            const request = {
              sessionID: tctx.sessionID,
              agent: tctx.agent,
              action: name,
              ...(rid ? { id: rid } : {}),
              resources: [`o/r feat/x aaaaaaa..bbbbbbb`],
              metadata: { caller: String(tctx.agent), session: String(tctx.sessionID), note: input.note ?? "" },
              source: { type: "tool", messageID: tctx.messageID, id: tctx.id },
            }
            const asserted = ctx.permission.assert(request)
            asserted.then(
              () => w({ ev: "assert.settled", name, ok: true, ms: ms() }),
              (e: any) => w({ ev: "assert.settled", name, ok: false, tag: tag(e), msg: String(e?.message).slice(0, 100), ms: ms() }),
            )
            try {
              if (input.timeout_ms) {
                let timer: any
                await Promise.race([
                  asserted,
                  new Promise((_, rej) => (timer = setTimeout(() => rej(new Error("BP_TIMEOUT")), input.timeout_ms))),
                ])
                clearTimeout(timer)
              } else {
                await asserted
              }
            } catch (err: any) {
              if (String(err?.message) === "BP_TIMEOUT") {
                let pending: any = null
                try {
                  pending = (await ctx.permission.list({ sessionID: tctx.sessionID })).map((r: any) => ({ id: r.id, action: r.action }))
                } catch (e: any) {
                  pending = `list-failed ${tag(e)} ${String(e?.message).slice(0, 100)}`
                }
                w({ ev: "timeout", name, ms: ms(), own_id: !!rid, pending })
                if (input.reject_on_timeout) {
                  const target = rid ?? (Array.isArray(pending) ? pending[0]?.id : undefined)
                  try {
                    const r = await ctx.permission.reply({ sessionID: tctx.sessionID, requestID: target, decision: "reject" })
                    w({ ev: "timeout.reject", ok: true, r: r === undefined ? "undefined" : JSON.stringify(r).slice(0, 80) })
                  } catch (e: any) {
                    w({ ev: "timeout.reject", ok: false, tag: tag(e), msg: String(e?.message).slice(0, 200) })
                  }
                }
              }
              throw err
            }
            const dwell = ms()
            w({ ev: "assert.ok", name, dwell_ms: dwell })
            if (input.min_dwell_ms && dwell < input.min_dwell_ms) {
              throw new Error(`${name} refused: approval in ${dwell} ms (< ${input.min_dwell_ms})`)
            }
            if (input.max_dwell_ms && dwell > input.max_dwell_ms) {
              throw new Error(`${name} refused: approval after ${dwell} ms (> ${input.max_dwell_ms})`)
            }
            const text = `${name} ran after ${dwell} ms`
            return { output: { text }, content: text }
          },
        })
      }
    })
  },
})
