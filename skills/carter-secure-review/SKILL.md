---
name: carter-secure-review
description: Security-focused code review — injection, authz, secrets, crypto-misuse, deserialization, SSRF
---

<objective>
Perform a security-focused review of code or a diff, covering the vulnerability classes
most commonly exploited in production applications.
Framework cells:
- OWASP **ASVS V1/V5/V6** (Architecture, Validation, Cryptography) — <https://owasp.org/www-project-application-security-verification-standard/>
- OWASP Top 10 **A01** (Broken Access Control), **A03** (Injection), **A08** (Software and Data Integrity) — <https://owasp.org/www-project-top-ten/>

Pairs with `carter-code-review` (quality) — run secure-review after code-review or alongside it.
</objective>

<methodology>

## Checklist

### A03 / Injection
- [ ] SQL: parameterized queries / ORM used; no string interpolation into queries
- [ ] Command injection: shell calls use argument arrays, not interpolated strings
- [ ] Template injection: user input is never passed to a template engine unsanitized
- [ ] LDAP, XPath, NoSQL: input validated and escaped for the target query language
- [ ] Log injection: user input sanitized before logging (strip/escape CRLF, ANSI)

### A01 / Broken Access Control
- [ ] Every endpoint enforces authentication and authorization; no missing `@auth` / middleware
- [ ] Horizontal privilege checks: user can only access their own resources
- [ ] IDOR: object references are not directly user-controlled without authz check
- [ ] Admin-only routes are protected; role checks are server-side, not client-side

### A08 / Secrets and Supply-Chain Integrity
- [ ] No secrets hardcoded (API keys, tokens, passwords, certs)
- [ ] Secrets loaded from environment / secrets manager, not config files committed to VCS
- [ ] Dependencies pinned to a specific version/digest; no `*` or unpinned ranges for security-sensitive packages

### ASVS V6 / Cryptography
- [ ] No use of MD5/SHA1 for integrity or password hashing
- [ ] Passwords hashed with bcrypt/scrypt/Argon2; no home-grown hashing
- [ ] TLS termination is enforced; no self-signed certs in production paths
- [ ] Key material not logged, not written to disk in plaintext

### SSRF (ASVS V5)
- [ ] Outbound HTTP calls validate/allowlist the target URL scheme and host
- [ ] No user-supplied URLs passed directly to HTTP client without validation
- [ ] Internal metadata endpoints (cloud IMDS) cannot be reached via user-controlled URLs

### Deserialization (A08 / ASVS V5)
- [ ] Untrusted data is never passed to deserializers (pickle, yaml.load, Java ObjectInputStream)
- [ ] Safe deserializer variants used (`yaml.safe_load`, typed deserializers)

## Severity Rating
- **Critical**: exploitable without authentication; data exfiltration or RCE
- **High**: exploitable with low privilege; significant data exposure
- **Medium**: exploitable with specific conditions; limited impact
- **Low**: defense-in-depth; negligible direct impact

## Output Format
```
## Secure Review: <scope>

### Critical (N)
[file:line] — finding + concrete fix

### High (N)
...

### Medium / Low (N)
...

**Verdict**: [Clean | Fix N critical/high issues before merge]
```

</methodology>

<guidelines>
- Report findings at the code level (`file:line`), not as abstract categories.
- Provide a concrete fix for every Critical and High finding.
- Do not emit working exploit code — describe the vulnerability class and a proof-of-concept path.
- Outward distribution of findings → hand off to narrator → devops.
</guidelines>
