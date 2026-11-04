// Helper for tests/test_plugin_entry_roundtrip.py (not a node test): feed the REAL `identity env`
// answer (a file) through the plugin core and print what the plugin would do to an agent shell's env.
import { readFileSync } from "node:fs"
import { applyIsolation, applySigning, tierDecision } from "../../carter/plugin/core.ts"

const vectors = JSON.parse(readFileSync(new URL("../data/plugin_vectors.json", import.meta.url), "utf8"))
const iso = vectors.isolation.doc
const stdout = readFileSync(process.argv[2], "utf8")
const base = JSON.parse(process.argv[3] ?? "{}")
const decision = tierDecision({ kind: "exit", code: 0, stdout }, iso)
const applied = applyIsolation(base, iso, undefined, decision.block)
const final = decision.signing ? applySigning(applied.env, decision.signing).env : applied.env
console.log(JSON.stringify({ decision, env: final }))
