// The thin adapter (index.ts) with a fake OpenCode ctx, a real node:child_process spawn and a fake
// python interpreter (a shell script), so the gate protocol of freeze G6 is tested end to end.
import { test } from "node:test"
import assert from "node:assert/strict"
import { copyFileSync, chmodSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs"
import { tmpdir } from "node:os"
import { join } from "node:path"
import { pathToFileURL } from "node:url"
import { canonical, isoDoc, sha256, vectors } from "./helpers.ts"

const SRC = new URL("../../carter/plugin/", import.meta.url)
const ALLOW = '{"decision":"allow","rule":null,"message":null}'
const DENY = (rule: string, message: string) => JSON.stringify({ decision: "deny", rule, message })
let counter = 0

interface Fixture {
  dir: string
  home: string
  python: string
  ctx: any
  hooks: Record<string, (e: any) => any>
  sessions: string[]
  setup: () => any
  gate: (stdout: string, rc?: number, sleep?: number) => void
  tier: (stdout: string, rc?: number) => void
  recorded: (name: string) => string
  cleanup: () => void
  restore: () => void
}

function fixture(opts: { sha?: string; isoEdit?: (d: any) => void; sessionDir?: string | undefined } = {}): Fixture {
  const dir = mkdtempSync(join(tmpdir(), "carter-adapter-"))
  const home = join(dir, "home")
  const plugin = join(dir, "plugins", "carter")
  const stub = join(dir, "node_modules", "@opencode", "plugin")
  mkdirSync(stub, { recursive: true })
  writeFileSync(join(stub, "package.json"), '{"name":"@opencode/plugin","type":"module","main":"index.js"}')
  writeFileSync(join(stub, "index.js"), "export const Plugin = { define: (p) => p }\n")
  mkdirSync(plugin, { recursive: true })
  mkdirSync(join(dir, "bin"))
  const python = join(dir, "bin", "python")
  const scratch = join(dir, "scratch")
  mkdirSync(scratch)
  writeFileSync(
    python,
    `#!/bin/sh
S=${scratch}
case "$*" in
  *carter.identity.env*) printf '%s\\n' "$@" > $S/env.args; pwd > $S/env.cwd; cat $S/tier.out; exit $(cat $S/tier.rc) ;;
esac
printf '%s\\n' "$@" > $S/gate.args
pwd > $S/gate.cwd
cat > $S/gate.stdin
env | grep -c '^SSH_AUTH_SOCK=' > $S/gate.sshsock || true
[ -f $S/gate.sleep ] && sleep $(cat $S/gate.sleep)
cat $S/gate.out
exit $(cat $S/gate.rc)
`,
  )
  chmodSync(python, 0o755)
  const iso: any = JSON.parse(JSON.stringify(isoDoc))
  iso.plugin.python_path = python
  iso.plugin.status_dir = join(home, ".carter", "run", "plugin-status")
  iso.plugin.pat_file = join(home, ".carter", "secrets", "gh-read.token")
  iso.plugin.gate_timeout_ms = 400
  opts.isoEdit?.(iso)
  mkdirSync(join(home, ".carter"), { recursive: true })
  const bytes = canonical(iso)
  writeFileSync(join(home, ".carter", "isolation.json"), bytes)
  const rendered = readFileSync(new URL("index.ts", SRC), "utf8")
    .replace("__CARTER_ISOLATION_SHA256__", opts.sha ?? sha256(bytes))
    .replace("__CARTER_VERSION__", "9.9.9-test")
  writeFileSync(join(plugin, "index.ts"), rendered)
  copyFileSync(new URL("core.ts", SRC), join(plugin, "core.ts"))
  const f = {
    gate: (stdout: string, rc = 0, sleep = 0) => {
      writeFileSync(join(scratch, "gate.out"), stdout)
      writeFileSync(join(scratch, "gate.rc"), String(rc))
      if (sleep) writeFileSync(join(scratch, "gate.sleep"), String(sleep))
    },
    tier: (stdout: string, rc = 0) => {
      writeFileSync(join(scratch, "tier.out"), stdout)
      writeFileSync(join(scratch, "tier.rc"), String(rc))
    },
  }
  f.gate(ALLOW)
  f.tier(JSON.stringify({ schema_version: 1, tier: "t0", cap: null, effective: "t0", require_tier: null, reason: null }))
  const hooks: Fixture["hooks"] = {}
  const sessions: string[] = []
  // Anything the plugin must NOT touch in 2a (tool registration, permission hooks) throws.
  const forbid = (name: string) => new Proxy({}, { get: () => { throw new Error(`2a must not use ctx.${name}`) } })
  const ctx = {
    app: { name: "cli", version: "2.1.4", channel: "latest" },
    tool: { hook: (name: string, fn: any) => (hooks[`tool.${name}`] = fn), transform: forbid("tool.transform") },
    shell: { hook: (name: string, fn: any) => (hooks[`shell.${name}`] = fn) },
    session: {
      get: async ({ sessionID }: { sessionID: string }) => {
        sessions.push(sessionID)
        return opts.sessionDir === undefined ? undefined : { id: sessionID, location: { directory: opts.sessionDir } }
      },
    },
    permission: forbid("permission"),
  }
  const previousHome = process.env.HOME
  process.env.HOME = home
  return {
    dir, home, python, ctx, hooks, sessions, ...f,
    setup: () => import(pathToFileURL(join(plugin, "index.ts")).href + `?${counter++}`).then((m) => m.default.setup(ctx)),
    recorded: (name) => (existsSync(join(scratch, name)) ? readFileSync(join(scratch, name), "utf8") : ""),
    cleanup: () => rmSync(dir, { recursive: true, force: true }),
    restore: () => {
      if (previousHome === undefined) delete process.env.HOME
      else process.env.HOME = previousHome
    },
  } // prettier-ignore
}

async function withPlugin(opts: Parameters<typeof fixture>[0], body: (f: Fixture) => Promise<void>) {
  const f = fixture(opts)
  const dispose = await f.setup()
  try {
    await body(f)
  } finally {
    dispose()
    f.restore()
    f.cleanup()
  }
}
const call = (command: string, extra: Record<string, unknown> = {}, tool = "shell") => ({ tool, sessionID: "ses_1", input: { command, ...extra } })

test("it registers exactly the two hooks and touches nothing else of ctx", async () => {
  await withPlugin({}, async (f) => {
    assert.deepEqual(Object.keys(f.hooks).sort(), ["shell.create.before", "tool.execute.before"])
  })
})

test("the gate is called by absolute python_path with gate_args, the command on stdin, cwd = home, env unchanged", async () => {
  await withPlugin({ sessionDir: "/work/repo" }, async (f) => {
    process.env.SSH_AUTH_SOCK = "/run/agent.sock" // the server env goes to the gate as it is
    const e = call("git status -s")
    await f.hooks["tool.execute.before"](e)
    delete process.env.SSH_AUTH_SOCK
    assert.equal(f.recorded("gate.stdin"), "git status -s")
    assert.deepEqual(f.recorded("gate.args").trim().split("\n"), ["-I", "-m", "carter.gate", "--json", "--cwd", "/work/repo", "--skip-groups", "sudo-docker"])
    assert.equal(f.recorded("gate.cwd").trim(), f.home)
    assert.equal(f.recorded("gate.sshsock").trim(), "1")
    assert.match(e.input.command, /^: carter_agent_[0-9a-z]{12}\ngit status -s$/)
  })
})

test("declined groups are passed unchanged and omitted when there are none", async () => {
  await withPlugin({ isoEdit: (d) => (d.plugin.declined_groups = []), sessionDir: undefined }, async (f) => {
    await f.hooks["tool.execute.before"](call("ls"))
    assert.deepEqual(f.recorded("gate.args").trim().split("\n"), ["-I", "-m", "carter.gate", "--json"])
  })
})

test("a deny (exit 1 + deny JSON) refuses the call with the gate's own message and does not arm the self-test", async () => {
  await withPlugin({ sessionDir: "/w" }, async (f) => {
    const message = "Refused by the Carter command gate (rule `push-verbs`): There is no push from an agent shell."
    f.gate(DENY("push-verbs", message), 1)
    const e = call("git push")
    await assert.rejects(f.hooks["tool.execute.before"](e), (err: Error) => err.message === message)
    assert.equal(e.input.command, "git push", "the command is not marked")
  })
})

test("every other combination fails closed with E-GATE-FAIL", async () => {
  const cases: [string, string, number][] = [
    ["exit 0 but deny", DENY("x", "m"), 0],
    ["exit 1 but allow", ALLOW, 1],
    ["exit 2", ALLOW, 2],
    ["non-JSON output", "boom", 0],
    ["empty output", "", 0],
    ["JSON without a decision", "{}", 0],
    ["crash (exit 139)", "", 139],
  ]
  for (const [name, out, rc] of cases) {
    await withPlugin({}, async (f) => {
      f.gate(out, rc)
      await assert.rejects(f.hooks["tool.execute.before"](call("ls")), /^Error: E-GATE-FAIL: Command gate unavailable; command refused \(fail closed\)\./, name)
    })
  }
})

test("a gate that does not answer within gate_timeout_ms is killed and refused", async () => {
  await withPlugin({}, async (f) => {
    f.gate(ALLOW, 0, 5)
    const started = Date.now()
    await assert.rejects(f.hooks["tool.execute.before"](call("ls")), /E-GATE-FAIL/)
    assert.ok(Date.now() - started < 3000, "the 400 ms timeout, not the 5 s sleep")
  })
})

test("a python interpreter that cannot be started is a gate failure, never an allow", async () => {
  await withPlugin({ isoEdit: (d) => (d.plugin.python_path = "/nonexistent/python") }, async (f) => {
    await assert.rejects(f.hooks["tool.execute.before"](call("ls")), /E-GATE-FAIL/)
  })
})

test("non-shell tools and malformed shell input pass untouched without spawning", async () => {
  await withPlugin({}, async (f) => {
    const read = call("/etc/hosts", {}, "read")
    await f.hooks["tool.execute.before"](read)
    await f.hooks["tool.execute.before"]({ tool: "shell", sessionID: "s", input: { command: 5 } })
    await f.hooks["tool.execute.before"]({ tool: "shell", sessionID: "s", input: undefined })
    assert.equal(f.recorded("gate.args"), "")
    assert.equal(read.input.command, "/etc/hosts")
  })
})

test("a broken isolation file refuses the shell call before the gate is even asked", async () => {
  await withPlugin({ sha: "__CARTER_ISOLATION_SHA256__" }, async (f) => {
    await assert.rejects(f.hooks["tool.execute.before"](call("ls")), /E-ISOLATION-MISSING/)
    assert.equal(f.recorded("gate.args"), "")
    const agent = { command: ": carter_agent_zzz\nls", cwd: "/w", env: {} }
    const human = { command: "ls", cwd: "/w", env: { SSH_AUTH_SOCK: "/s" } as Record<string, string | undefined> }
    await f.hooks["shell.create.before"](human) // a `!` shell is never blocked
    assert.equal(human.env.SSH_AUTH_SOCK, "/s")
    assert.equal(typeof agent.command, "string")
  })
})

// ---- effective directory (freeze G6, erratum E3) -------------------------------------------

test("workdir: absolute is used as given; relative is resolved against the session directory", async () => {
  await withPlugin({ sessionDir: "/work/repo" }, async (f) => {
    await f.hooks["tool.execute.before"](call("ls", { workdir: "/tmp/elsewhere" }))
    assert.ok(f.recorded("gate.args").includes("/tmp/elsewhere"))
    await f.hooks["tool.execute.before"](call("ls", { workdir: "sub/dir" }))
    assert.ok(f.recorded("gate.args").includes("/work/repo/sub/dir"))
    await f.hooks["tool.execute.before"](call("ls"))
    assert.ok(f.recorded("gate.args").includes("/work/repo"))
  })
})

test("the session directory is looked up through ctx.session.get once per session", async () => {
  await withPlugin({ sessionDir: "/work/repo" }, async (f) => {
    await f.hooks["tool.execute.before"](call("ls"))
    await f.hooks["tool.execute.before"](call("pwd"))
    await f.hooks["tool.execute.before"](call("pwd", { workdir: "/abs" }))
    assert.deepEqual(f.sessions, ["ses_1"])
  })
})

test("no known directory: the gate runs without --cwd (it fails closed where it needs one)", async () => {
  await withPlugin({ sessionDir: undefined }, async (f) => {
    await f.hooks["tool.execute.before"](call("ls"))
    assert.ok(!f.recorded("gate.args").includes("--cwd"))
    await f.hooks["tool.execute.before"](call("ls", { workdir: "relative" }))
    assert.ok(!f.recorded("gate.args").includes("--cwd"))
  })
})

// ---- create.before through the adapter --------------------------------------------------------

test("a marked shell is stripped, round-trips, tagged and isolated; the tier entry runs in the shell's cwd", async () => {
  await withPlugin({ sessionDir: "/w" }, async (f) => {
    const e = call("git commit -m x")
    await f.hooks["tool.execute.before"](e)
    const env: Record<string, string | undefined> = { SSH_AUTH_SOCK: "/s", GITHUB_TOKEN: "t", PATH: "/usr/bin" }
    const ev = { command: e.input.command, cwd: f.home, env }
    await f.hooks["shell.create.before"](ev)
    assert.equal(ev.command, "git commit -m x")
    assert.equal(env.CARTER_AGENT_SHELL, "1")
    assert.equal(env.SSH_AUTH_SOCK, undefined)
    assert.equal(env.GITHUB_TOKEN, undefined)
    assert.equal(env.GH_TOKEN, isoDoc.plugin.gh_token_dummy)
    assert.equal(env.GIT_CONFIG_COUNT, String(isoDoc.git_config.length))
    assert.equal(f.recorded("env.cwd").trim(), f.home)
    assert.deepEqual(f.recorded("env.args").trim().split("\n"), ["-I", "-m", "carter.identity.env", "--json"])
  })
})

test("an unmarked (human `!`) shell is not isolated, and gets no human tag until a round trip passed", async () => {
  await withPlugin({}, async (f) => {
    const env: Record<string, string | undefined> = { SSH_AUTH_SOCK: "/s" }
    await f.hooks["shell.create.before"]({ command: "ls", cwd: "/w", env })
    assert.deepEqual(env, { SSH_AUTH_SOCK: "/s" })
    assert.equal(f.recorded("env.args"), "")
  })
})

test("the status file is written under run/plugin-status/<pid>.json with the baked version", async () => {
  await withPlugin({}, async (f) => {
    const file = join(f.home, ".carter", "run", "plugin-status", `${process.pid}.json`)
    const record = JSON.parse(readFileSync(file, "utf8"))
    assert.deepEqual(Object.keys(record), vectors.status.keys)
    assert.equal(record.plugin_version, "9.9.9-test")
    assert.equal(record.opencode_version, "2.1.4")
    assert.equal(record.isolation_sha256, sha256(canonical(JSON.parse(readFileSync(join(f.home, ".carter", "isolation.json"), "utf8")))))
  })
})

test("the cleanup returned by setup disposes the instance (hot reload)", async () => {
  const f = fixture({})
  const dispose = await f.setup()
  await f.hooks["tool.execute.before"](call("ls")) // arms a timer
  dispose()
  const file = join(f.home, ".carter", "run", "plugin-status", `${process.pid}.json`)
  const before = readFileSync(file, "utf8")
  await new Promise((r) => setTimeout(r, 2300)) // longer than self_test_ms (2000): a dead instance must not fail
  assert.equal(readFileSync(file, "utf8"), before)
  f.restore()
  f.cleanup()
})
