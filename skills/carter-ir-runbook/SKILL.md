---
name: carter-ir-runbook
description: Incident-response runbook — scope → contain → eradicate → recover → lessons
---

<objective>
Draft or execute an incident-response runbook for a security incident.
Framework cells:
- NIST CSF 2.0 **RS.MI** (Mitigation) and **RC.RP** (Recovery Planning) — <https://www.nist.gov/cyberframework>
- MITRE D3FEND **Eviction** and **Restore** tactics — <https://d3fend.mitre.org/>
</objective>

<methodology>

## Phase 0: Declare and Scope
**Trigger**: any confirmed or suspected security event.
- Assign an incident commander (IC) and a scribe
- Open a dedicated incident channel (Slack/Teams/etc.)
- Set initial severity: P1 (critical) / P2 (high) / P3 (medium)
- Record: incident ID, timestamp, initial description, affected systems

## Phase 1: Contain
Stop the bleeding without destroying evidence.
- [ ] Isolate affected systems (network ACL, security group, firewall rule) — devops executes
- [ ] Revoke or rotate compromised credentials immediately
- [ ] Preserve logs before any remediation that could overwrite them (snapshot, export)
- [ ] Notify legal / compliance if PII or regulated data is involved
- [ ] For web: consider emergency WAF block rule

## Phase 2: Investigate
Understand the full scope.
- [ ] Identify initial access vector (log analysis, SAST findings, alert chain)
- [ ] Map lateral movement: what other systems did the attacker reach?
- [ ] Identify data accessed or exfiltrated
- [ ] Establish timeline: first compromise → detection → containment
- [ ] Document attacker TTPs (reference MITRE ATT&CK if applicable)

## Phase 3: Eradicate
Remove the threat from the environment.
- [ ] Patch the exploited vulnerability or disable the vulnerable code path
- [ ] Remove malicious artifacts (backdoors, scheduled tasks, unauthorized accounts)
- [ ] Re-image or restore from known-good snapshot if system integrity is uncertain
- [ ] Confirm no persistence mechanisms remain

## Phase 4: Recover
Restore normal operation safely.
- [ ] Bring systems back online in a controlled sequence
- [ ] Monitor closely for 24–72 h post-recovery (anomaly alerts, access logs)
- [ ] Confirm data integrity before resuming normal data processing
- [ ] Notify affected parties per legal/compliance requirements — narrator drafts, devops transmits

## Phase 5: Lessons Learned
Prevent recurrence.
- [ ] Hold a blameless post-mortem within 5 business days
- [ ] Document: timeline, root cause, contributing factors, detection gap
- [ ] Action items with owners and due dates
- [ ] Update detection rules, runbooks, and training as needed
- [ ] File a post-mortem document (→ narrator for external/customer communication)

## Output Template
```
# IR Runbook: <incident-id> — <title>
**Severity**: P<N>  **IC**: <name>  **Declared**: <timestamp>

## Scope
<affected systems, data, users>

## Timeline
| Time | Event |
|------|-------|

## Containment Steps
- [ ] ...

## Eradication Steps
- [ ] ...

## Recovery Steps
- [ ] ...

## Lessons Learned
<post-mortem summary>
```

</methodology>

<guidelines>
- This runbook is a local document; external communications (customer notices, regulatory filings) go through narrator → devops.
- Preserve evidence before eradication steps — log snapshots, memory dumps, disk images as appropriate.
- All infrastructure changes (isolating instances, rotating credentials in prod) are executed by devops.
</guidelines>
