// Carter plugin core.
//
// Pure logic with injected dependencies: no OpenCode import, `node:*` modules only, erasable
// TypeScript only (Node type stripping and Bun load this file as written). The plugin holds the
// marker, the shell tagging, a read of the static `isolation.json`, the call of the Python gate
// and the identity entry. Every list and flag it applies comes from `isolation.json`, which
// Python renders from `g2_rules.json`; shared golden vectors keep this file and the Python
// oracles equal (`tests/data/plugin_vectors.json`).
import { createHash } from "node:crypto"
import { dirname, join, resolve, isAbsolute } from "node:path"

// ---- types ---------------------------------------------------------------------------------
export type Env = Record<string, string | undefined>
export type State = "unproven" | "passed" | "failed"
export type Pair = [string, string]
export interface Iso {
  schema_version: number
  env: { set: Record<string, string>; delete: string[] }
  git_config: Pair[]
  blocking_git_config: Pair[]
  pollution: {
    agent_signals: string[]
    human_signals: string[]
    markers: { env: [string, string, string][]; git_config: Pair[] }
  }
  plugin: {
    python_path: string
    carter_path: string
    gate_args: string[]
    env_args: string[]
    pat_file: string
    pat_prefix: string
    gh_token_dummy: string
    declined_groups: string[]
    self_test_ms: number
    gate_timeout_ms: number
    env_timeout_ms: number
    status_dir: string
    b_enabled: boolean // the broker tool registers only while this is true
    b_caller: string // the one agent id allowed to use them (devops)
    broker_args: string[] // `-I -m carter.broker_cli`, after python_path
    b_git: string // absolute paths fixed at install ("" = not found)
    b_gh: string
  }
}
export interface Signing {
  env: Record<string, string>
  git_config: Pair[]
  fingerprint: string
}
export interface Decision {
  block: boolean
  flags: string[]
  signing: Signing | null
  reason: string | null // a name from the entry (never a value), for the warning text
}
export type RunResult = { kind: "exit"; code: number | null; stdout: string } | { kind: "timeout" } | { kind: "error" }
export type Run = (argv: string[], opts: { cwd: string; input: string; timeoutMs: number; env: Env }) => Promise<RunResult>
export interface Clock {
  now(): number
  setTimeout(fn: () => void, ms: number): unknown
  clearTimeout(handle: unknown): void
}
export interface Deps {
  fs: typeof import("node:fs")
  run: Run
  clock: Clock
  env: Env // the server environment, passed to the gate and the identity entry unchanged
  home: string
  pluginVersion: string
  isolationSha256: string // baked at install; anything but 64 hex digits means "not rendered"
  opencodeVersion: string
  pid: number
  uptimeSec: () => number
  random: () => number
  euid: number | undefined
  sessionDir: (sessionID: string) => Promise<string | undefined>
  // The parent of a session, null for a root session. Throws when the session cannot be read.
  sessionParent: (sessionID: string) => Promise<string | null>
  log: (line: string) => void
  onFailed?: () => void // the self-test failed: the adapter reloads the tool list so B drops out
}

// Registry texts (carter/identity/errors.json); a pytest parity test compares them.
export const MESSAGES: Record<string, string> = {
  "E-ISOLATION-MISSING":
    "Carter isolation file is missing, invalid, or doesn't match its install-time hash; agent shells are disabled. Run `carter guard install` in your terminal.",
  "E-GATE-FAIL": "Command gate unavailable; command refused (fail closed). Run `carter check --host`.",
  "E-SELFTEST":
    "Carter plugin self-test failed on OpenCode <v>: all shells are treated as agent shells and the push tool is disabled. See `carter check --host`.",
  "E-SIGN-UNAVAILABLE":
    "The LLM signing identity is unavailable (<reason>); agent commits are blocked, not downgraded. Changes are still staged. Run `carter check --host`.",
  "E-CONFIG": "config.toml is invalid; agent commits are disabled until fixed.",
  "E-B-CALLER": "`carter_push` is devops-only.",
}
export class CarterError extends Error {
  code: string
  constructor(code: string, text?: string) {
    super(`${code}: ${text ?? MESSAGES[code]}`)
    this.code = code
  }
}

// ---- marker (with the scope bit) --------------------------------
// `: carter_agent_<nonce>_<1|0>\n`: 1 = the shell is in Carter's scope (a Carter agent or a Carter
// workspace), 0 = it is not and create.before leaves it untouched. Every shell call is marked, so the
// self-test and the `!` human tag stay correct whatever the scope.
export const MARK_PREFIX = ": carter_agent_"
export function newNonce(random: () => number): string {
  return Array.from({ length: 12 }, () => Math.floor(random() * 36).toString(36)).join("")
}
export function mark(nonce: string, command: string, scope = true): string {
  return `${MARK_PREFIX}${nonce}_${scope ? 1 : 0}\n${command}`
}
export function detect(nonce: string, command: string): { marked: boolean; scope: boolean | null; command: string } {
  const head = `${MARK_PREFIX}${nonce}_`
  if (command.startsWith(head) && (command[head.length] === "1" || command[head.length] === "0") && command[head.length + 1] === "\n") {
    return { marked: true, scope: command[head.length] === "1", command: command.slice(head.length + 2) }
  }
  return { marked: false, scope: null, command }
}

// ---- scope ----------------------------------------------------------------------------
// A shell is in Carter's scope when (A) the calling agent is a Carter agent (`carter-*`, workspace
// suffixes included), or a subagent of one, or (B) its directory is inside a Carter workspace.
export const WORKSPACE_LEVELS = 32 // directories walked upwards from the shell's directory
export const SESSION_HOPS = 5 // parent sessions followed to find a Carter agent
const CARTER_AGENT = /^carter-/
export function isCarterAgent(agent: unknown): boolean {
  return typeof agent === "string" && CARTER_AGENT.test(agent)
}
// The nearest ancestor holding `.carter/carter.yaml` is the workspace root; it counts only if it also
// holds a Carter agent file (`carter init` renders both), so `.carter/` alone (a global install that
// keeps plans in a repo) does not.
export function inCarterWorkspace(fs: Deps["fs"], dir: string | undefined): boolean {
  if (!dir || !isAbsolute(dir)) return false
  let cur = resolve(dir)
  for (let i = 0; i < WORKSPACE_LEVELS; i++) {
    let root = false
    try {
      root = fs.statSync(join(cur, ".carter", "carter.yaml")).isFile()
    } catch {
      root = false
    }
    if (root) {
      try {
        return fs.readdirSync(join(cur, ".opencode", "agents")).some((n) => /^carter-.*\.md$/.test(n))
      } catch {
        return false
      }
    }
    const up = dirname(cur)
    if (up === cur) return false
    cur = up
  }
  return false
}

// ---- pollution and the GIT_CONFIG_COUNT state (shared vectors with carter.identity.pollution) -
export function isPolluted(env: Env, p: Iso["pollution"]): boolean {
  if ([...p.agent_signals, ...p.human_signals].some((name) => env[name] !== undefined)) return true
  for (const [name, how, value] of p.markers.env) {
    const v = env[name]
    if (v !== undefined && (how === "equals" ? v === value : v.includes(value))) return true
  }
  const wanted = new Set(p.markers.git_config.map(([k, v]) => `${k}\u0000${v}`))
  for (const name of Object.keys(env)) {
    const m = /^GIT_CONFIG_KEY_([0-9]+)$/.exec(name)
    const value = m ? env[`GIT_CONFIG_VALUE_${m[1]}`] : undefined
    if (m && value !== undefined && wanted.has(`${env[name]}\u0000${value}`)) return true
  }
  return false
}
export const COUNT_CAP = 1000
export function countState(env: Env): { state: "ok" | "polluted"; n: number; reason: string } {
  const raw = env.GIT_CONFIG_COUNT
  const ok = (n: number) => ({ state: "ok" as const, n, reason: "" })
  const bad = (reason: string) => ({ state: "polluted" as const, n: 0, reason })
  if (raw === undefined) return ok(0)
  if (raw === "") return Object.keys(env).some((k) => /^GIT_CONFIG_(KEY|VALUE)_/.test(k)) ? bad("empty-with-keys") : ok(0)
  if (!/^[0-9]+$/.test(raw)) return bad("malformed")
  if (raw.replace(/^0+/, "").length > String(COUNT_CAP).length || Number(raw) > COUNT_CAP) return bad("over-cap")
  const n = Number(raw)
  for (let i = 0; i < n; i++) {
    const key = env[`GIT_CONFIG_KEY_${i}`]
    if (key === undefined || env[`GIT_CONFIG_VALUE_${i}`] === undefined) return bad("missing-entry")
    if (!key.includes(".")) return bad("bad-key")
  }
  return ok(n)
}

// ---- self-test state machine  ------------------------
// unproven -> passed on the first marked round trip; a marked execute.before that is not followed
// by a marked create.before within N ms -> failed (terminal, in every state). Timers are armed
// LAST in execute.before and live in every state.
export function createSelfTest(clock: Clock, ms: number, onChange: (state: State, reason: string | null) => void) {
  let state: State = "unproven"
  let reason: string | null = null
  const pending: { handle: unknown }[] = []
  let disposed = false
  return {
    state: (): State => state,
    reason: (): string | null => reason,
    pending: (): number => pending.length,
    arm(): void {
      if (disposed) return
      const entry: { handle: unknown } = { handle: undefined }
      entry.handle = clock.setTimeout(() => {
        const i = pending.indexOf(entry)
        if (i >= 0) pending.splice(i, 1)
        if (state !== "failed" && !disposed) {
          state = "failed"
          reason = "timeout"
          onChange(state, reason)
        }
      }, ms)
      pending.push(entry)
    },
    roundTrip(): void {
      const first = pending.shift()
      if (first) clock.clearTimeout(first.handle)
      if (state === "unproven") {
        state = "passed"
        onChange(state, null)
      }
    },
    dispose(): void {
      disposed = true
      for (const entry of pending.splice(0)) clock.clearTimeout(entry.handle)
    },
  }
}

// ---- tagging --------------------------------------------------------------------------------
const AGENT_TAG = "CARTER_AGENT_SHELL"
const HUMAN_TAG = "CARTER_HUMAN_SHELL"
export type Tag = "agent" | "human" | "none"
// Pollution is judged on the inherited environment, BEFORE our own tags are deleted.
export function tagShell(
  env: Env,
  p: Iso["pollution"] | undefined,
  agent: boolean,
  state: State,
  pending: number,
): { tag: Tag; polluted: boolean } {
  const polluted = p === undefined ? true : isPolluted(env, p)
  delete env[AGENT_TAG]
  delete env[HUMAN_TAG]
  if (agent) {
    env[AGENT_TAG] = "1"
    return { tag: "agent", polluted }
  }
  if (state === "passed" && pending === 0 && !polluted) {
    env[HUMAN_TAG] = "1"
    return { tag: "human", polluted }
  }
  return { tag: "none", polluted }
}

// ---- isolation.json --------------------------------------------------------------------
const TOP = ["schema_version", "env", "git_config", "blocking_git_config", "pollution", "plugin"]
const PLUGIN_KEYS = [
  "python_path", "carter_path", "gate_args", "env_args", "pat_file", "pat_prefix", "gh_token_dummy",
  "declined_groups", "self_test_ms", "gate_timeout_ms", "env_timeout_ms", "status_dir",
  "b_enabled", "b_caller", "broker_args", "b_git", "b_gh",
] // prettier-ignore
const isObj = (v: unknown): v is Record<string, unknown> => typeof v === "object" && v !== null && !Array.isArray(v)
const sameKeys = (o: Record<string, unknown>, keys: string[]) =>
  Object.keys(o).length === keys.length && keys.every((k) => k in o)
const strs = (v: unknown) => Array.isArray(v) && v.every((x) => typeof x === "string")
const pairs = (v: unknown) => Array.isArray(v) && v.every((p) => Array.isArray(p) && p.length === 2 && strs(p))
const posInt = (v: unknown) => typeof v === "number" && Number.isInteger(v) && v > 0

export function validateIso(doc: unknown): Iso {
  const bad = () => new CarterError("E-ISOLATION-MISSING")
  if (!isObj(doc) || !sameKeys(doc, TOP) || doc.schema_version !== 2) throw bad()
  const { env, pollution: pol, plugin: pl } = doc
  if (!isObj(env) || !sameKeys(env, ["set", "delete"]) || !isObj(env.set) || !strs(env.delete)) throw bad()
  if (!Object.values(env.set).every((v) => typeof v === "string")) throw bad()
  if (!pairs(doc.git_config) || !pairs(doc.blocking_git_config)) throw bad()
  if (!isObj(pol) || !sameKeys(pol, ["agent_signals", "human_signals", "markers"])) throw bad()
  if (!strs(pol.agent_signals) || !strs(pol.human_signals) || !isObj(pol.markers)) throw bad()
  const mk = pol.markers
  if (!sameKeys(mk, ["env", "git_config"]) || !pairs(mk.git_config)) throw bad()
  if (!Array.isArray(mk.env) || !mk.env.every((m) => Array.isArray(m) && m.length === 3 && strs(m))) throw bad()
  if (!isObj(pl) || !sameKeys(pl, PLUGIN_KEYS)) throw bad()
  for (const k of ["python_path", "carter_path", "status_dir"]) if (typeof pl[k] !== "string" || !isAbsolute(pl[k])) throw bad()
  if (typeof pl.pat_file !== "string" || (pl.pat_file !== "" && !isAbsolute(pl.pat_file))) throw bad()
  if (!strs(pl.gate_args) || !strs(pl.env_args) || !strs(pl.declined_groups)) throw bad()
  if (typeof pl.pat_prefix !== "string" || !pl.pat_prefix || typeof pl.gh_token_dummy !== "string" || !pl.gh_token_dummy) throw bad()
  if (!posInt(pl.self_test_ms) || !posInt(pl.gate_timeout_ms) || !posInt(pl.env_timeout_ms)) throw bad()
  if (typeof pl.b_enabled !== "boolean" || typeof pl.b_caller !== "string" || !pl.b_caller || !strs(pl.broker_args)) throw bad()
  for (const k of ["b_git", "b_gh"]) if (typeof pl[k] !== "string" || (pl[k] !== "" && !isAbsolute(pl[k]))) throw bad()
  if (pl.b_enabled && pl.b_git === "") throw bad()
  return doc as unknown as Iso
}

// Refuse, never skip: a missing, unreadable, invalid or hash-mismatched file (or a plugin whose
// hash was never rendered) is E-ISOLATION-MISSING.
export function loadIsolation(fs: Deps["fs"], path: string, expectedSha256: string): Iso {
  if (!/^[0-9a-f]{64}$/.test(expectedSha256)) throw new CarterError("E-ISOLATION-MISSING")
  let bytes: Buffer
  try {
    bytes = fs.readFileSync(path)
  } catch {
    throw new CarterError("E-ISOLATION-MISSING")
  }
  if (createHash("sha256").update(bytes).digest("hex") !== expectedSha256) throw new CarterError("E-ISOLATION-MISSING")
  try {
    return validateIso(JSON.parse(bytes.toString("utf8")))
  } catch (err) {
    throw err instanceof CarterError ? err : new CarterError("E-ISOLATION-MISSING")
  }
}

// The GitHub read token: a regular file, no symlink, owned by us, mode 0600, `github_pat_...`.
// Read at each shell creation, held in memory only, never logged or written to a config value.
export function readPat(fs: Deps["fs"], iso: Iso, euid: number | undefined): string | undefined {
  const { pat_file: file, pat_prefix: prefix } = iso.plugin
  if (!file) return undefined
  try {
    const st = fs.lstatSync(file)
    if (!st.isFile() || st.isSymbolicLink() || (st.mode & 0o777) !== 0o600) return undefined
    if (euid !== undefined && st.uid !== euid) return undefined
    const text = fs.readFileSync(file, "utf8").trim()
    return text.startsWith(prefix) ? text : undefined
  } catch {
    return undefined
  }
}

// Write entries as GIT_CONFIG_KEY_i/VALUE_i from `start` and set the count. Shared by the isolation
// block and the signing block (Python: isolation_apply.append_git_config), so they cannot drift.
function appendEntries(out: Env, start: number, entries: Pair[]): void {
  let n = start
  for (const [key, value] of entries) {
    out[`GIT_CONFIG_KEY_${n}`] = key
    out[`GIT_CONFIG_VALUE_${n}`] = value
    n++
  }
  out.GIT_CONFIG_COUNT = String(n)
}
function dropEntries(out: Env): void {
  for (const name of Object.keys(out)) if (/^GIT_CONFIG_(KEY|VALUE)_/.test(name)) delete out[name]
}

// Reference port of carter.identity.isolation_apply.apply_isolation (same golden vectors).
export function applyIsolation(env: Env, iso: Iso, pat: string | undefined, blockCommits: boolean) {
  const out: Env = { ...env }
  const flags: string[] = []
  const counted = countState(env) // judged before any change
  for (const name of iso.env.delete) delete out[name]
  Object.assign(out, iso.env.set)
  out.GH_TOKEN = pat ?? iso.plugin.gh_token_dummy
  if (!pat) flags.push("pat-dummy")
  if (counted.state === "polluted") {
    dropEntries(out)
    flags.push("count-malformed")
  }
  const entries = [...iso.git_config]
  if (counted.state === "polluted" || blockCommits) entries.push(...iso.blocking_git_config)
  appendEntries(out, counted.n, entries)
  return { env: out, flags }
}

// Port of carter.identity.payload.to_git_env: the signing block (identity entry) goes on top of
// the isolation entries, so Carter's later entries win. It adds the committer variables and the
// git entries and deletes an inherited GIT_CONFIG_PARAMETERS; it decides nothing.
export function applySigning(env: Env, signing: Signing) {
  const out: Env = { ...env }
  const flags: string[] = []
  const counted = countState(env)
  if (counted.state === "polluted") {
    dropEntries(out)
    flags.push("count-malformed")
  }
  delete out.GIT_CONFIG_PARAMETERS
  Object.assign(out, signing.env)
  appendEntries(out, counted.n, signing.git_config)
  return { env: out, flags }
}

// The `signing` object must be exactly what the entry sends: three keys, plain strings. Names the
// isolation block manages (its `set` and `delete` lists) and the shell tags cannot be set through it.
// What the values mean (which keys, which program) is Python's business, not the plugin's.
const SIGNING_TOP = ["env", "git_config", "fingerprint"]
const plain = (v: unknown, max = 1024) => typeof v === "string" && v.length > 0 && v.length <= max && !/[\n\r\0]/.test(v)
export function validateSigning(v: unknown, iso: Iso): Signing | null {
  if (!isObj(v) || !sameKeys(v, SIGNING_TOP) || !plain(v.fingerprint)) return null
  const { env, git_config: cfg } = v
  const taken = new Set([...Object.keys(iso.env.set), ...iso.env.delete, "CARTER_AGENT_SHELL", "CARTER_HUMAN_SHELL"])
  if (!isObj(env) || Object.keys(env).length < 1 || Object.keys(env).length > 8) return null
  for (const [name, value] of Object.entries(env)) {
    if (!/^[A-Z][A-Z0-9_]*$/.test(name) || name === "GIT_CONFIG_COUNT" || name.startsWith("GIT_CONFIG_KEY_") || name.startsWith("GIT_CONFIG_VALUE_") || taken.has(name) || !plain(value)) return null
  }
  if (!Array.isArray(cfg) || cfg.length < 1 || cfg.length > 16) return null
  for (const pair of cfg) {
    if (!Array.isArray(pair) || pair.length !== 2 || !plain(pair[0], 256) || !/^[A-Za-z0-9.-]+$/.test(pair[0]) || !pair[0].includes(".")) return null
    if (typeof pair[1] !== "string" || pair[1].includes("\0")) return null
  }
  return { env: env as Record<string, string>, git_config: cfg as Pair[], fingerprint: v.fingerprint as string }
}

// ---- identity entry: decide whether agent commits must be blocked ---------------------
const TIERS = ["t0", "t1", "t2"]
export function tierDecision(res: RunResult, iso: Iso): Decision {
  const failed: Decision = { block: true, flags: ["sign-unavailable"], signing: null, reason: null }
  if (res.kind !== "exit" || res.code !== 0) return failed
  try {
    const v = JSON.parse(res.stdout)
    const shape = isObj(v) && v.schema_version === 1 && TIERS.includes(v.tier as string)
    if (!shape || !TIERS.includes(v.effective as string) || !("cap" in v) || !("require_tier" in v)) return failed
    if (v.reason === "config-error") return { ...failed, flags: ["config-error"], reason: "config-error" }
    if (v.reason !== null) {
      // any other reason (and any value that is not a name) blocks: nothing from the answer is applied
      return { ...failed, reason: typeof v.reason === "string" && /^[a-z-]{1,40}$/.test(v.reason) ? v.reason : null }
    }
    if (v.effective !== "t2") return "signing" in v ? failed : { block: false, flags: [], signing: null, reason: null }
    const signing = "signing" in v ? validateSigning(v.signing, iso) : null
    return signing ? { block: false, flags: [], signing, reason: null } : failed
  } catch {
    return failed
  }
}

// ---- process runner (the only place that spawns) --------------------------------------------
export type SpawnFn = typeof import("node:child_process").spawn
export function makeRunner(spawn: SpawnFn): Run {
  return (argv, opts) =>
    new Promise((done) => {
      let settled = false
      let timer: ReturnType<typeof setTimeout> | undefined
      const finish = (r: RunResult) => {
        if (settled) return
        settled = true
        if (timer) clearTimeout(timer)
        done(r)
      }
      let child: ReturnType<SpawnFn>
      try {
        child = spawn(argv[0], argv.slice(1), { cwd: opts.cwd, env: opts.env as NodeJS.ProcessEnv, stdio: ["pipe", "pipe", "ignore"] })
      } catch {
        return finish({ kind: "error" })
      }
      let out = ""
      child.stdout?.on("data", (d: Buffer) => (out = out.length < 1 << 20 ? out + d.toString("utf8") : out))
      child.on("error", () => finish({ kind: "error" }))
      child.on("close", (code: number | null) => finish({ kind: "exit", code, stdout: out }))
      timer = setTimeout(() => {
        child.kill("SIGKILL")
        finish({ kind: "timeout" })
      }, opts.timeoutMs)
      child.stdin?.on("error", () => {})
      child.stdin?.end(opts.input)
    })
}

// ---- the assembled plugin (everything index.ts needs) ---------------------------------------
export interface ExecuteBefore {
  tool: string
  sessionID: string
  input: unknown
  agent?: string // the calling agent's id (OpenCode 2.1 reports it on every tool call)
}
export interface CreateBefore {
  command: string
  cwd: string
  env: Env
}
const DEFAULT_SELF_TEST_MS = 2000 // used only while isolation.json cannot be read
export function createCarter(deps: Deps) {
  const { fs, clock } = deps
  const nonce = newNonce(deps.random)
  const instance = newNonce(deps.random) + newNonce(deps.random) // never the nonce
  const isoPath = join(deps.home, ".carter", "isolation.json")
  const flags = new Set<string>()
  const warned = new Set<string>()
  const sessions = new Map<string, string>()
  const tierCache = new Map<string, Decision>()
  let since = new Date(clock.now()).toISOString()
  let disposed = false
  let statusDir = join(deps.home, ".carter", "run", "plugin-status")

  const warn = (kind: string, line: string) => {
    if (!warned.has(kind)) {
      warned.add(kind)
      deps.log(`carter: ${line}`)
    }
  }
  const writeStatus = () => {
    if (disposed) return
    const record = {
      schema_version: 1, pid: deps.pid, boot: Math.round(clock.now() - deps.uptimeSec() * 1000), instance,
      plugin_version: deps.pluginVersion, opencode_version: deps.opencodeVersion, state: selfTest.state(), since,
      failed_reason: selfTest.reason(), isolation_sha256: deps.isolationSha256, flags: [...flags].sort(),
    } // prettier-ignore
    try {
      fs.mkdirSync(statusDir, { recursive: true, mode: 0o700 })
      const target = join(statusDir, `${deps.pid}.json`)
      const tmp = `${target}.tmp`
      fs.writeFileSync(tmp, JSON.stringify(record) + "\n", { mode: 0o600 })
      fs.renameSync(tmp, target)
    } catch {
      // a status write never blocks a shell
    }
  }
  const setFlag = (name: string, on: boolean) => {
    if (on === flags.has(name)) return
    if (on) flags.add(name)
    else flags.delete(name)
    writeStatus()
  }
  const load = () => loadIsolation(fs, isoPath, deps.isolationSha256)

  let selfTestMs = DEFAULT_SELF_TEST_MS
  try {
    const first = load()
    statusDir = first.plugin.status_dir
    selfTestMs = first.plugin.self_test_ms
  } catch {
    // keep the defaults; the first agent shell reports the problem
  }
  const selfTest = createSelfTest(clock, selfTestMs, (state, reason) => {
    since = new Date(clock.now()).toISOString()
    if (state === "failed") warn("selftest", `${MESSAGES["E-SELFTEST"].replace("<v>", deps.opencodeVersion)} (${reason})`)
    writeStatus()
    if (state === "failed") deps.onFailed?.()
  })
  writeStatus()

  // (A): sessions in which a `carter-*` agent called a tool, and the parent of each session read so
  // far (null = root). A subagent (`general`, `explore`) reports its own id, so its session is covered
  // through its ancestors. Both maps are bounded; forgetting a session only costs one more lookup.
  const carterSessions = new Set<string>()
  const parents = new Map<string, string | null>()
  const CAP = 5000
  const remember = <K, V>(map: Map<K, V>, key: K, value: V) => {
    if (map.size >= CAP) map.delete(map.keys().next().value as K)
    map.set(key, value)
  }
  const agentInScope = async (sessionID: string, agent: unknown): Promise<boolean> => {
    if (isCarterAgent(agent)) {
      if (!carterSessions.has(sessionID)) {
        if (carterSessions.size >= CAP) carterSessions.delete(carterSessions.values().next().value as string)
        carterSessions.add(sessionID)
      }
      return true
    }
    let id = sessionID
    for (let hop = 0; hop <= SESSION_HOPS; hop++) {
      if (carterSessions.has(id)) return true
      let parent = parents.get(id)
      if (parent === undefined) {
        try {
          parent = await deps.sessionParent(id)
        } catch {
          return true // the chain cannot be read: it may lead to a Carter session (fail closed)
        }
        remember(parents, id, parent)
      }
      if (parent === null) return typeof agent !== "string" // a root session of another agent: out
      id = parent
    }
    return true // too deep to follow: fail closed
  }

  const effectiveDir = async (e: ExecuteBefore): Promise<string | undefined> => {
    const given = isObj(e.input) && typeof e.input.workdir === "string" ? e.input.workdir : undefined
    let session = sessions.get(e.sessionID)
    if (session === undefined && (given === undefined || !isAbsolute(given))) {
      try {
        session = await deps.sessionDir(e.sessionID)
      } catch {
        session = undefined
      }
      if (session) sessions.set(e.sessionID, session)
    }
    if (given !== undefined) return isAbsolute(given) ? given : session ? resolve(session, given) : undefined
    return session
  }

  async function gate(iso: Iso, command: string, dir: string | undefined): Promise<void> {
    const p = iso.plugin
    const argv = [p.python_path, ...p.gate_args]
    if (dir) argv.push("--cwd", dir)
    if (p.declined_groups.length) argv.push("--skip-groups", p.declined_groups.join(","))
    const res = await deps.run(argv, { cwd: deps.home, input: command, timeoutMs: p.gate_timeout_ms, env: deps.env })
    let verdict: { decision?: unknown; rule?: unknown; message?: unknown } | undefined
    if (res.kind === "exit") {
      try {
        verdict = JSON.parse(res.stdout)
      } catch {
        verdict = undefined
      }
    }
    const allow = res.kind === "exit" && res.code === 0 && isObj(verdict) && verdict.decision === "allow"
    const deny = res.kind === "exit" && res.code === 1 && isObj(verdict) && verdict.decision === "deny"
    if (allow) return
    if (deny && verdict) {
      const rule = typeof verdict.rule === "string" ? verdict.rule : "unknown"
      const text = typeof verdict.message === "string" ? verdict.message : `Refused by the Carter command gate (rule \`${rule}\`).`
      throw new Error(text)
    }
    throw new CarterError("E-GATE-FAIL")
  }

  async function tier(iso: Iso, cwd: string): Promise<Decision> {
    const stamp = (name: string) => {
      try {
        return String(fs.statSync(join(deps.home, ".carter", name)).mtimeMs)
      } catch {
        return "-"
      }
    }
    const key = [cwd, stamp("config.toml"), stamp("gitconfig"), deps.pluginVersion].join("|")
    const cached = tierCache.get(key)
    if (cached) return cached
    const res = await deps.run([iso.plugin.python_path, ...iso.plugin.env_args], {
      cwd, input: "", timeoutMs: iso.plugin.env_timeout_ms, env: deps.env,
    }) // prettier-ignore
    const decision = tierDecision(res, iso)
    tierCache.set(key, decision)
    return decision
  }

  return {
    state: (): State => selfTest.state(),
    // The validated isolation.json (throws E-ISOLATION-MISSING): the broker tools read their
    // switches and absolute tool paths from it, never from the environment.
    isolation: (): Iso => load(),
    // The broker tools register only while this is true (b_enabled and the self-test not failed).
    brokerOn: (): boolean => {
      try {
        return load().plugin.b_enabled && selfTest.state() !== "failed"
      } catch {
        return false
      }
    },
    pending: (): number => selfTest.pending(),
    flags: (): string[] => [...flags].sort(),
    nonce: (): string => nonce,

    // The only hook that may reject a call. Order: scope -> isolation -> gate -> mark -> arm the timer.
    // Every tool call records a Carter agent's session (A); only a shell is gated, and only in scope.
    async executeBefore(e: ExecuteBefore): Promise<void> {
      const carterAgent = isCarterAgent(e.agent)
      if (e.tool !== "shell" || !isObj(e.input) || typeof e.input.command !== "string") {
        if (carterAgent) await agentInScope(e.sessionID, e.agent) // fills the map, no lookup
        return
      }
      const dir = await effectiveDir(e)
      // a failed self-test cannot tell the scope: every shell counts (conservative, RED in check --host)
      const inScope =
        selfTest.state() === "failed" || (await agentInScope(e.sessionID, e.agent)) || inCarterWorkspace(fs, dir)
      if (inScope) {
        const iso = load()
        await gate(iso, e.input.command, dir)
      }
      e.input.command = mark(nonce, e.input.command, inScope)
      selfTest.arm()
    },

    async createBefore(e: CreateBefore): Promise<void> {
      const seen = detect(nonce, e.command)
      if (seen.marked) {
        e.command = seen.command
        selfTest.roundTrip()
      }
      // a marked shell is Carter's when the mark says so, or its own directory is a Carter
      // workspace; a failed self-test cannot tell, so every shell is. Otherwise it is left alone.
      const agent = selfTest.state() === "failed" || (seen.marked && (seen.scope === true || inCarterWorkspace(fs, e.cwd)))
      if (seen.marked && !agent) {
        delete e.env.CARTER_AGENT_SHELL // no tag at all: neither agent nor human
        delete e.env.CARTER_HUMAN_SHELL
        return
      }
      let iso: Iso | undefined
      try {
        iso = load()
      } catch (err) {
        if (agent) throw err // an agent shell is never created without a valid isolation file
      }
      const { polluted } = tagShell(e.env, iso?.pollution, agent, selfTest.state(), selfTest.pending())
      if (!agent) {
        if (polluted && selfTest.state() === "passed") {
          setFlag("polluted", true)
          warn("polluted", "the server environment looks like an agent shell; restart OpenCode from a clean terminal")
        }
        return
      }
      if (!iso) throw new CarterError("E-ISOLATION-MISSING")
      const decision = await tier(iso, e.cwd)
      const pat = readPat(fs, iso, deps.euid)
      const applied = applyIsolation(e.env, iso, pat, decision.block)
      // The signing block goes on top, but never over a malformed inherited count: that stays blocked.
      const final = decision.signing && !applied.flags.includes("count-malformed") ? applySigning(applied.env, decision.signing).env : applied.env
      for (const name of Object.keys(e.env)) if (!(name in final)) delete e.env[name]
      Object.assign(e.env, final)
      setFlag("pat-dummy", applied.flags.includes("pat-dummy"))
      if (applied.flags.includes("count-malformed")) {
        setFlag("count-malformed", true)
        warn("count", "the inherited GIT_CONFIG_COUNT is malformed; starting a fresh count and blocking commits")
      }
      for (const name of ["sign-unavailable", "config-error"]) setFlag(name, decision.flags.includes(name))
      if (decision.block) {
        warn("sign", MESSAGES["E-SIGN-UNAVAILABLE"].replace("<reason>", decision.reason ?? "signing unavailable"))
      }
    },

    dispose(): void {
      disposed = true
      selfTest.dispose()
    },
  }
}
