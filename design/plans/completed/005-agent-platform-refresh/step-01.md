---
step: 1
status: done
depends_on: []
files_modified: [agents/carter-maestro.md, skills/carter-triage/SKILL.md, templates/agents/carter-maestro.md.j2, tests/test_parity.py, instructions/copilot-instructions.md, skills/carter-plan/SKILL.md, skills/carter-rfc/SKILL.md, skills/carter-adr/SKILL.md, README.md]
---

## Step 1 — P0: staleness purge + time-awareness (no behaviour change)

Pure correctness. Lands first so review of everything else is honest. Includes time-awareness
(moved up per ADR-0010 D6 / RFC R1 — it fixes a live bug: dated artifacts are wrong today).

### Tasks
- **Delete `runSubagent`** at both sites ([agents/carter-maestro.md:41], [skills/carter-triage/SKILL.md:27]);
  re-sync the static maestro body with the template (they drifted).
- **Drop `temperature` emission wholesale** (D7) on all agents/templates AND remove its parity
  assertion ([tests/test_parity.py:141]). Document effort/temperature as runtime-owned.
- **Document `mode:` as OpenCode-scoped** (kept for OpenCode, ignored on VS Code) — do NOT remove it.
- **Reconcile README** per RFC-0005 §6c claims-commitment: orchestration story becomes accurate (not
  deleted); narrator reframed first-class WITHOUT dropping the redaction promise; flat-chain
  over-claims dropped; leave the correct `~/.copilot/agents/` troubleshooting line untouched.
- **Stop citing `notes/`**; re-evaluate `_TARGET_ENFORCES_GATES` (Copilot CLI `hooks` enforces now);
  drop the unsourced OpenCode `tools`-deprecation version.
- **Time-awareness (D6):** add a required date-fetch checklist item to the carter-plan / carter-rfc /
  carter-adr skills + global instructions ("obtain the current date from a tool/the environment before
  writing any dated frontmatter"); verify per target whether a native current-date var exists and
  prefer it where present; audit Carter-side stamping for gaps; verify no template bakes a literal date.

### Done when (TDD red → green)
- A `runSubagent`-absent body-parity test ([tests/test_parity.py]) is added and green; `grep -rn
  runSubagent` is clean across agents/skills/templates.
- A `temperature`-absent parity assertion replaces the old required-present one; `temperature` appears
  in no emitted frontmatter.
- `grep -rn 'notes/HANDOFF'` is absent from shipped docs/templates; the README orchestration section
  matches what Step 4 will emit (no contradiction).
- The three authoring skills contain the date-fetch checklist item (asserted by a skill-content check
  or a doc test); no template contains a literal `Today is`.
- `python -m pytest tests/ -q -p no:cacheprovider` green.
