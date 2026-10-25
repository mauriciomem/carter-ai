---
name: carter-vuln-triage
description: CVE / advisory / scanner-finding triage — reachability, severity, remediation, FP filtering
---

<objective>
Triage a CVE, dependency advisory, or SAST/DAST scanner finding to determine:
real vs. false positive, actual severity in context, and the right remediation action.
Framework cells:
- NIST CSF 2.0 **DE.CM** (Continuous Monitoring) — <https://www.nist.gov/cyberframework>
- NIST CSF 2.0 **RS.AN** (Incident Analysis) — <https://www.nist.gov/cyberframework>
</objective>

<methodology>

## 1. Gather the input
Collect from the user:
- CVE ID / advisory URL / scanner output
- Affected package name and version currently in use
- How the package is used in the codebase (direct call, transitive dep, test-only)

## 2. Confirm affected version
- Verify the reported vulnerable version range against the CVE/advisory
- If the currently pinned version is outside the vulnerable range → likely false positive; confirm

## 3. Reachability analysis
Determine whether the vulnerable code path is actually exercised:
- Is the vulnerable function called (directly or transitively)?
- Is it reachable from an external entry point (HTTP handler, queue consumer, etc.)?
- Is it reachable only in tests, build scripts, or dev-only code?

**Not reachable → downgrade severity to Informational; document the rationale.**

## 4. Context-adjusted severity
Start from the CVSS base score, then adjust:
| Factor | Effect |
|--------|--------|
| Not reachable from external input | Downgrade 2 levels |
| Requires authentication | Downgrade 1 level |
| Mitigated by WAF / network control | Downgrade 1 level |
| Exploited in the wild (CISA KEV) | Upgrade 1 level |
| Data exfiltration or RCE possible | Keep Critical |

## 5. Remediation options (prioritized)
1. **Patch**: upgrade to the fixed version — always first choice if available
2. **Workaround**: disable the vulnerable feature/code path with a config flag
3. **Compensating control**: WAF rule, input sanitization, network restriction
4. **Accept and document**: if not reachable and patch is not yet available

## 6. Output
```
## Vuln Triage: <CVE / finding>

**Package**: <name> <version>
**CVSS base**: <score> (<severity>)
**Context-adjusted severity**: <severity>
**Reachable from external input**: Yes / No / Unknown

### Finding
<description>

### Recommendation
<patch / workaround / accept>

### Rationale
<why this severity, why this recommendation>
```

</methodology>

<guidelines>
- Always check reachability before recommending an urgent patch; not every CVE in a dep tree is exploitable.
- Cite the advisory source (NVD URL, GitHub advisory, vendor bulletin).
- Filing the tracked issue or advisory is a handoff to devops.
</guidelines>
