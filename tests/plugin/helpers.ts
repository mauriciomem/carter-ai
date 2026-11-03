// Shared test helpers for the plugin core tests (not a test file itself).
import { readFileSync, mkdtempSync, mkdirSync, writeFileSync, chmodSync, rmSync } from "node:fs"
import * as fs from "node:fs"
import { createHash } from "node:crypto"
import { tmpdir } from "node:os"
import { join } from "node:path"
import type { Clock, Deps, Env, Iso, Run, RunResult } from "../../carter/plugin/core.ts"

export const vectors = JSON.parse(readFileSync(new URL("../data/plugin_vectors.json", import.meta.url), "utf8"))
export const isoDoc: Iso = vectors.isolation.doc

// `$expand` is the vector file's shorthand for N identical GIT_CONFIG entries.
export function expand(env: Record<string, unknown>): Env {
  const out: Env = {}
  for (const [k, v] of Object.entries(env)) if (k !== "$expand") out[k] = v as string
  const spec = env["$expand"] as { entries: number; key: string; value: string } | undefined
  if (spec) {
    for (let i = 0; i < spec.entries; i++) {
      out[`GIT_CONFIG_KEY_${i}`] = spec.key
      out[`GIT_CONFIG_VALUE_${i}`] = spec.value
    }
  }
  return out
}

export interface FakeClock extends Clock {
  advance(ms: number): void
  timers(): number
}
export function fakeClock(start = 1_700_000_000_000): FakeClock {
  let now = start
  let next = 1
  const timers = new Map<number, { at: number; fn: () => void }>()
  return {
    now: () => now,
    setTimeout(fn, ms) {
      const id = next++
      timers.set(id, { at: now + ms, fn })
      return id
    },
    clearTimeout(handle) {
      timers.delete(handle as number)
    },
    advance(ms) {
      const target = now + ms
      for (;;) {
        const due = [...timers.entries()].filter(([, t]) => t.at <= target).sort((a, b) => a[1].at - b[1].at)[0]
        if (!due) break
        timers.delete(due[0])
        now = due[1].at
        due[1].fn()
      }
      now = target
    },
    timers: () => timers.size,
  }
}

export function canonical(doc: unknown): Buffer {
  return Buffer.from(JSON.stringify(doc) + "\n", "utf8")
}
export const sha256 = (data: Buffer | string) => createHash("sha256").update(data).digest("hex")

export interface Rig {
  home: string
  deps: Deps
  clock: FakeClock
  calls: { argv: string[]; opts: { cwd: string; input: string; timeoutMs: number; env: Env } }[]
  logs: string[]
  iso: Iso
  respond: (fn: (argv: string[], input: string) => RunResult) => void
  cleanup: () => void
}

// A temp HOME holding a rendered isolation.json (paths rewritten into the temp dir) and a fake runner.
export function rig(over: Partial<Deps> = {}, isoEdit: (iso: Iso) => void = () => {}): Rig {
  const home = mkdtempSync(join(tmpdir(), "carter-core-"))
  const iso: Iso = JSON.parse(JSON.stringify(isoDoc))
  iso.plugin.python_path = "/opt/carter/bin/python"
  iso.plugin.status_dir = join(home, ".carter", "run", "plugin-status")
  iso.plugin.pat_file = join(home, ".carter", "secrets", "gh-read.token")
  isoEdit(iso)
  mkdirSync(join(home, ".carter"), { recursive: true })
  const bytes = canonical(iso)
  writeFileSync(join(home, ".carter", "isolation.json"), bytes)
  const clock = fakeClock()
  const calls: Rig["calls"] = []
  const logs: string[] = []
  let responder: (argv: string[], input: string) => RunResult = () => ({ kind: "exit", code: 0, stdout: '{"decision":"allow","rule":null,"message":null}' })
  const run: Run = async (argv, opts) => {
    calls.push({ argv, opts })
    return responder(argv, opts.input)
  }
  const deps: Deps = {
    fs,
    run,
    clock,
    env: { PATH: "/usr/bin" },
    home,
    pluginVersion: "0.0.0-test",
    isolationSha256: sha256(bytes),
    opencodeVersion: "2.1.4",
    pid: 4242,
    uptimeSec: () => 1,
    random: (() => {
      let i = 0
      return () => ((i += 7) % 36) / 36
    })(),
    euid: process.geteuid?.(),
    sessionDir: async () => undefined,
    log: (line) => logs.push(line),
    ...over,
  }
  return { home, deps, clock, calls, logs, iso, respond: (fn) => (responder = fn), cleanup: () => rmSync(home, { recursive: true, force: true }) }
}

export function writePat(home: string, text: string, mode = 0o600): string {
  const dir = join(home, ".carter", "secrets")
  mkdirSync(dir, { recursive: true })
  const file = join(dir, "gh-read.token")
  writeFileSync(file, text + "\n")
  chmodSync(file, mode)
  return file
}
