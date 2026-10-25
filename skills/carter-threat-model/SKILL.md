---
name: carter-threat-model
description: STRIDE / attack-tree threat modeling of a design or change
---

<objective>
Produce a structured threat model for a design, architecture, or pending change.
Framework cell: NIST CSF 2.0 **ID.RA** (Risk Assessment) — <https://www.nist.gov/cyberframework>
</objective>

<methodology>

## 1. Scope
Define what is in scope: system boundary, data flows, trust boundaries, entry points, assets.
Ask the user to confirm scope before proceeding.

## 2. Data Flow Diagram (DFD)
Map the components and data flows. Identify:
- External entities (users, third-party services, APIs)
- Processes (services, functions, handlers)
- Data stores (databases, caches, files, secrets)
- Trust boundaries (network zones, auth checkpoints)

## 3. STRIDE Analysis
For each data flow and component, evaluate the six threat categories:

| Category | Question |
|----------|----------|
| **S**poofing | Can an attacker impersonate a user, service, or component? |
| **T**ampering | Can data in transit or at rest be modified without detection? |
| **R**epudiation | Can actors deny their actions? Are audit logs tamper-evident? |
| **I**nformation Disclosure | Can sensitive data leak to unauthorized parties? |
| **D**enial of Service | Can availability be degraded or disrupted? |
| **E**levation of Privilege | Can an attacker gain capabilities beyond their authorization? |

## 4. Attack Tree (high-risk paths)
For the top 2–3 findings, expand into an attack tree:
- Root: the attacker goal
- Branches: attack steps / prerequisites
- Leaves: concrete exploitable conditions

## 5. Risk Rating
Rate each finding: **Likelihood** × **Impact** → Critical / High / Medium / Low.
Use CVSS base score if a CVE maps to the finding.

## 6. Mitigations
For each Critical/High finding, propose a concrete mitigation with an owner:
- Engineering control (code change, library replacement)
- Configuration control (policy, header, permission)
- Operational control (monitoring, alerting, rotation)

## 7. Output
Produce a threat model document:
```
# Threat Model: <system/change>
## Scope
## Data Flow Summary
## STRIDE Findings
| ID | Threat | STRIDE | Likelihood | Impact | Severity | Mitigation |
## Attack Trees (top findings)
## Recommendations
```
Save locally as `docs/security/threat-model-<slug>.md` unless the user specifies otherwise.
Outward distribution (filing an issue, sharing externally) → hand off to narrator → devops.

</methodology>

<guidelines>
- Ask clarifying questions before generating the model; a threat model built on wrong assumptions is noise.
- Prefer concrete, actionable findings over exhaustive theoretical threats.
- Do not emit exploit code or payloads — describe the threat class and attack vector.
</guidelines>
